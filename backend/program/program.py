import os
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from queue import Empty, Queue
from typing import Union

from apscheduler.schedulers.background import BackgroundScheduler
from program.downloaders import Downloader
from program.content import Listrr, Mdblist, Overseerr, PlexWatchlist, TraktContent
from program.indexers.trakt import TraktIndexer
from program.libraries import PlexLibrary, SymlinkLibrary
from program.media.container import MediaItemContainer
from program.media.item import Episode, MediaItem, Movie, Season, Show
from program.media.state import States
from program.scrapers import Scraping
from program.settings.manager import settings_manager
from program.updaters.plex import PlexUpdater
from utils import data_dir_path
from utils.logger import logger, scrub_logs

from .cache import hash_cache
from .pickly import Pickly
from .state_transition import process_event
from .symlink import Symlinker
from .types import Event, Service


class Program(threading.Thread):
    """Program class"""

    def __init__(self, args):
        super().__init__(name="Iceberg")
        self.running = False
        self.startup_args = args
        self.initialized = False
        self.event_queue = Queue()
        self.media_items = MediaItemContainer()
        self.services = {}

    def initialize_services(self):
        self.requesting_services = {
            Overseerr: Overseerr(),
            PlexWatchlist: PlexWatchlist(),
            Listrr: Listrr(),
            Mdblist: Mdblist(),
            TraktContent: TraktContent(),
        }
        self.indexing_services = {TraktIndexer: TraktIndexer()}
        self.processing_services = {
            Scraping: Scraping(hash_cache),
            Symlinker: Symlinker(self.media_items),
            PlexUpdater: PlexUpdater(),
            Downloader: Downloader(hash_cache)
        }

        # Depends on Symlinker having created the file structure so needs
        # to run after it
        self.library_services = {
            SymlinkLibrary: SymlinkLibrary(),
            PlexLibrary: PlexLibrary(),
        }
        if not any(s.initialized for s in self.requesting_services.values()):
            logger.error("No Requesting service initialized, you must select at least one.")

        if not self.processing_services.get(Scraping).initialized:
            logger.error("No Scraping service initialized, you must select at least one.")
        if not self.processing_services.get(Downloader).initialized:
            logger.error("No downloading service initialized, you must select at least one.")

        self.services = {
            **self.library_services,
            **self.indexing_services,
            **self.requesting_services,
            **self.processing_services,
        }

    def validate(self) -> bool:
        """Validate that all required services are initialized."""
        return all(
            (
                any(s.initialized for s in self.requesting_services.values()),
                any(s.initialized for s in self.library_services.values()),
                any(s.initialized for s in self.indexing_services.values()),
                all(s.initialized for s in self.processing_services.values()),
            )
        )

    def start(self):
        logger.log("PROGRAM", f"Iceberg v{settings_manager.settings.version} starting!")
        settings_manager.register_observer(self.initialize_services)
        os.makedirs(data_dir_path, exist_ok=True)

        if not settings_manager.settings_file.exists():
            logger.log("PROGRAM", "Settings file not found, creating default settings")
            settings_manager.save()

        try:
            self.initialize_services()
            scrub_logs()
        except Exception as e:
            logger.exception(f"Failed to initialize services: {e}")

        logger.log("PROGRAM", "----------------------------------------------")
        logger.log("PROGRAM", "Iceberg is waiting for configuration to start!")
        logger.log("PROGRAM", "----------------------------------------------")

        while not self.validate():
            time.sleep(1)

        self.initialized = True
        logger.log("PROGRAM", "Iceberg started!")

        if not self.startup_args.ignore_cache:
            self.pickly = Pickly(self.media_items, data_dir_path)
            self.pickly.start()

        if not len(self.media_items):
            # Seed initial MIC with Library State
            for item in self.services[SymlinkLibrary].run():
                self.media_items.upsert(item)

        unfinished_items = self.media_items.get_incomplete_items()
        logger.log("PROGRAM", f"Found {len(unfinished_items)} unfinished items")

        self.executor = ThreadPoolExecutor(thread_name_prefix="Worker")
        self.scheduler = BackgroundScheduler()
        self._schedule_services()
        self._schedule_functions()

        super().start()
        self.scheduler.start()
        self.running = True
        logger.success("Iceberg is running!")

    def _retry_library(self) -> None:
        """Retry any items that are in an incomplete state."""
        items_to_submit = [item for item in self.media_items.get_incomplete_items().values()]
        for item in items_to_submit:
            self.event_queue.put(Event(emitted_by=self.__class__, item=item))

    def _schedule_functions(self) -> None:
        """Schedule each service based on its update interval."""
        scheduled_functions = {
            self._retry_library: {"interval": 60 * 10},
        }
        for func, config in scheduled_functions.items():
            self.scheduler.add_job(
                func,
                "interval",
                seconds=config["interval"],
                args=config.get("args"),
                id=f"{func.__name__}",
                max_instances=1,
                replace_existing=True,
                next_run_time=datetime.now(),
            )
            logger.log("PROGRAM", f"Scheduled {func.__name__} to run every {config['interval']} seconds.")

    def _schedule_services(self) -> None:
        """Schedule each service based on its update interval."""
        scheduled_services = {**self.requesting_services, **self.library_services}
        for service_cls, service_instance in scheduled_services.items():
            if not service_instance.initialized:
                continue
            if not (update_interval := getattr(service_instance.settings, "update_interval", False)):
                continue

            self.scheduler.add_job(
                self._submit_job,
                "interval",
                seconds=update_interval,
                args=[service_cls, None],
                id=f"{service_cls.__name__}_update",
                max_instances=1,
                replace_existing=True,
                next_run_time=datetime.now() if service_cls != SymlinkLibrary else None,
            )
            logger.log("PROGRAM", f"Scheduled {service_cls.__name__} to run every {update_interval} seconds.")

    def _process_future_item(self, future: Future, service: Service, item: MediaItem) -> None:
        """Callback to add the results from a future emitted by a service to the event queue."""
        try:
            for item in future.result():
                if not isinstance(item, MediaItem):
                    logger.error(f"Service {service.__name__} emitted item {item} of type {item.__class__.__name__}, skipping")
                    continue
                self.event_queue.put(Event(emitted_by=service, item=item))
        except Exception:
            logger.exception(f"Service {service.__name__} failed with exception {traceback.format_exc()}")

    def _submit_job(self, service: Service, item: MediaItem | None) -> None:
        if item and service:
            if service.__name__ == "TraktIndexer":
                logger.log("NEW", f"Submitting service {service.__name__} to the pool with {getattr(item, 'log_string', None) or item.item_id}")
            else:
                logger.log("PROGRAM", f"Submitting service {service.__name__} to the pool with {getattr(item, 'log_string', None) or item.item_id}")
        func = self.services[service].run
        future = self.executor.submit(func) if item is None else self.executor.submit(func, item)
        future.add_done_callback(lambda f: self._process_future_item(f, service, item))

    def run(self):
        while self.running:
            if not self.validate():
                time.sleep(1)
                continue

            try:
                event: Event = self.event_queue.get(timeout=10)
            except Empty:
                continue

            existing_item = self.media_items.get(event.item.item_id, None)
            updated_item, next_service, items_to_submit = process_event(
                existing_item, event.emitted_by, event.item
            )

            if updated_item and isinstance(existing_item, (Movie, Show)) and updated_item.state == States.Symlinked:
                logger.success(f"Item has been completed: {updated_item.log_string}")

            if updated_item:
                self.media_items.upsert(updated_item)

            if items_to_submit:
                for item_to_submit in items_to_submit:
                    if isinstance(item_to_submit, Season) and next_service == Scraping:
                        if item_to_submit.scraped_times >= 3:
                            continue
                    self._submit_job(next_service, item_to_submit)

    def stop(self):
        self.running = False
        self.clear_queue()  # Clear the queue when stopping
        if hasattr(self, "executor") and not getattr(self.executor, '_shutdown', False):
            self.executor.shutdown(wait=False)
        if hasattr(self, "scheduler") and getattr(self.scheduler, 'running', False):
            self.scheduler.shutdown(wait=False)
        if hasattr(self, "pickly") and getattr(self.pickly, 'running', False):
            self.pickly.stop()
        logger.log("PROGRAM", "Iceberg has been stopped.")

    def add_to_queue(self, item: Union[Movie, Show, Season, Episode]) -> bool:
        """Add item to the queue for processing."""
        if isinstance(item, Union[Movie, Show, Season, Episode]):
            self.event_queue.put(Event(emitted_by=self.__class__, item=item))
            logger.log("PROGRAM", f"Added {item.log_string} to the queue")
            return True
        else:
            logger.error(f"Failed to add item with type {type(item)} to the queue")
        return False

    def clear_queue(self):
        """Clear the event queue."""
        logger.log("PROGRAM", "Clearing the event queue. Please wait.")
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
                self.event_queue.task_done()
            except Empty:
                break
        logger.log("PROGRAM", "Cleared the event queue")
