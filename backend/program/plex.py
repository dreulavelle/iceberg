"""Plex library module"""
import concurrent.futures
import os
import threading
import time
from datetime import datetime
from plexapi.server import PlexServer
from plexapi.exceptions import BadRequest, Unauthorized
from utils.logger import logger
from program.settings.manager import settings_manager
from program.media.container import MediaItemContainer
from program.media.state import Symlink, Library
from program.media.item import (
    Movie,
    Show,
    Season,
    Episode,
)


class Plex(threading.Thread):
    """Plex library class"""

    def __init__(self, media_items: MediaItemContainer):
        super().__init__(name="Plex")
        self.key = "plex"
        self.initialized = False
        self.library_path = os.path.abspath(
            os.path.dirname(settings_manager.settings.symlink.library_path)
        )
        self.last_fetch_times = {}

        try:
            self.settings = settings_manager.settings.plex
            self.plex = PlexServer(self.settings.url, self.settings.token, timeout=60)
        except Unauthorized:
            logger.error("Plex is not authorized!")
            return
        except BadRequest as e:
            logger.error("Plex is not configured correctly: %s", e)
            return
        except Exception as e:
            logger.error("Plex exception thrown: %s", e)
            return
        self.running = False
        self.log_worker_count = False
        self.media_items = media_items
        self._update_items(init=True)
        self.initialized = True
        logger.info("Plex initialized!")

    def run(self):
        while self.running:
            self._update_items()
            for i in range(10):
                time.sleep(i)

    def start(self):
        self.running = True
        super().start()

    def stop(self):
        self.running = False

    def _get_last_fetch_time(self, section):
        return self.last_fetch_times.get(section.key, datetime(1800, 1, 1))

    def _update_items(self, init=False):
        items = MediaItemContainer()
        sections = self.plex.library.sections()
        processed_sections = set()
        max_workers = os.cpu_count() / 2
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="Plex"
        ) as executor:
            for section in sections:
                if (
                    section.key in processed_sections
                    or not self._is_wanted_section(section)
                ):
                    continue
                if section.refreshing:
                    processed_sections.add(section.key)
                    continue
                # Fetch only items that have been added or updated since the last fetch
                last_fetch_time = self._get_last_fetch_time(section)
                filters = {"addedAt>>": last_fetch_time}
                if init:
                    filters = {}
                future_items = {
                    executor.submit(self._create_and_match_item, item)
                    for item in section.search(
                        libtype=section.type, filters=filters
                    )
                }
                for future in concurrent.futures.as_completed(future_items):
                    media_item = future.result()
                    items.append(media_item)
                self.last_fetch_times[section.key] = datetime.now()
                processed_sections.add(section.key)

        if not processed_sections:
            logger.error(f"Failed to process any sections.  Ensure that your library_path" 
                " of {self.library_path} folders are included in the relevant sections"
                " (found in Plex Web UI Setting > Manage > Libraries > Edit Library)."
            )
            return

        added_count = 0
        for item in items:
            if item is not None and item not in self.media_items:
                self.media_items.append(item)
                added_count += 1

        if added_count > 0:
            if added_count <= 5:
                logger.info("Found %d from Plex", item.log_string)
            else:
                logger.info("Found %d items from Plex", added_count)

    def update_item_section(self, item):
        """Update plex library section for a single item"""
        item_type = item.type
        if item.type == "episode":
            item_type = "show"
        for section in self.plex.library.sections():
            if section.type != item_type:
                continue

            if self._update_section(section, item):
                logger.debug(
                    "Updated section %s for %s", section.title, item.log_string
                )

    def _update_section(self, section, item):
        if item.state == Symlink and item.get("update_folder") != "updated":
            update_folder = item.update_folder
            section.update(update_folder)
            item.set("update_folder", "updated")
            return True
        return False

    def _create_and_match_item(self, item):
        new_item = self._create_item(item)
        if new_item:
            self.match_item(new_item)
        return new_item

    def _create_item(self, item):
        new_item = _map_item_from_data(item)
        if not new_item or item.type != "show":
            return new_item
        for season in item.seasons():
            if season.seasonNumber == 0:
                continue
            if not (new_season := _map_item_from_data(season)):
                continue
            new_season_episodes = []
            for episode in season.episodes():
                new_episode = _map_item_from_data(episode)
                if new_episode:
                    new_season_episodes.append(new_episode)
            new_season.episodes = new_season_episodes
            new_item.seasons.append(new_season)
        return new_item

    def match_item(self, new_item):
        for existing_item in self.media_items:
            if existing_item.imdb_id == new_item.imdb_id:
                self._update_item(existing_item, new_item)
                break
        # Leaving this here as a reminder to not forget about deleting items that are removed from plex, needs to be revisited
        # if item.state is MediaItemState.LIBRARY and item not in found_items:
        #     self.media_items.remove(item)

    def _update_item(self, item, library_item):
        items_updated = 0
        item.set("guid", library_item.guid)
        item.set("key", library_item.key)
        if item.type != "show":
            return items_updated
        def first_matching(items, number): 
            return next(filter(lambda x: x.number == number, items), None)
        flat_episodes = ((s, e) for s in item.seasons for e in season.episodes)
        for season, episode in flat_episodes:
            if episode.state == Library:
                continue
            if not (found_season := first_matching(library_item.seasons, season.number)):
                continue
            if not (found_episode := first_matching(found_season.episodes, episode.number)):
                continue
            episode.set("guid", found_episode.guid)
            episode.set("key", found_episode.key)
            items_updated += 1
        return items_updated

    def _is_wanted_section(self, section):
        section_located = any(
            self.library_path in location 
            for location in section.locations
        )
        return section_located and section.type in ["movie", "show"]


def _map_item_from_data(item):
    """Map Plex API data to MediaItemContainer."""
    file = None
    guid = getattr(item, "guid", None)
    if item.type in ["movie", "episode"]:
        file = getattr(item, "locations", [None])[0].split("/")[-1]
    genres = [genre.tag for genre in getattr(item, "genres", [])]
    is_anime = "anime" in genres
    title = getattr(item, "title", None)
    key = getattr(item, "key", None)
    season_number = getattr(item, "seasonNumber", None)
    episode_number = getattr(item, "episodeNumber", None)
    art_url = getattr(item, "artUrl", None)
    imdb_id = None
    tvdb_id = None
    aired_at = None

    if item.type in ["movie", "show"]:
        guids = getattr(item, "guids", [])
        imdb_id = next(
            (guid.id.split("://")[-1] for guid in guids if "imdb" in guid.id), None
        )
        aired_at = getattr(item, "originallyAvailableAt", None)

    media_item_data = {
        "title": title,
        "imdb_id": imdb_id,
        "tvdb_id": tvdb_id,
        "aired_at": aired_at,
        "genres": genres,
        "key": key,
        "guid": guid,
        "art_url": art_url,
        "file": file,
        "is_anime": is_anime,
    }

    # Instantiate the appropriate subclass based on 'item_type'
    if item.type == "movie":
        return Movie(media_item_data)
    elif item.type == "show":
        return Show(media_item_data)
    elif item.type == "season":
        media_item_data["number"] = season_number
        return Season(media_item_data)
    elif item.type == "episode":
        media_item_data["number"] = episode_number
        media_item_data["season_number"] = season_number
        return Episode(media_item_data)
    else:
        # Specials may end up here..
        logger.error("Unknown Item: %s with type %s", item.title, item.type)
        return None
