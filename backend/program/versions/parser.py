from typing import Dict, List

import PTN
from program.versions.ranks import BaseRankingModel, DefaultRanking, calculate_ranking
from pydantic import BaseModel, Field
from thefuzz import fuzz

from .patterns import (
    COMPLETE_SERIES_COMPILED,
    MULTI_AUDIO_COMPILED,
    MULTI_SUBTITLE_COMPILED,
    UNWANTED_QUALITY_COMPILED,
)


class ParsedMediaItem(BaseModel):
    """ParsedMediaItem class containing parsed data."""
    raw_title: str
    parsed_title: str = None
    fetch: bool = False
    is_4k: bool = False
    is_multi_audio: bool = False
    is_multi_subtitle: bool = False
    is_complete: bool = False
    year: List[int] = []
    resolution: List[str] = []
    quality: List[str] = []
    season: List[int] = []
    episode: List[int] = []
    codec: List[str] = []
    audio: List[str] = []
    subtitles: List[str] = []
    language: List[str] = []
    bitDepth: List[int] = []
    hdr: bool = False
    proper: bool = False
    repack: bool = False
    remux: bool = False
    upscaled: bool = False
    remastered: bool = False
    directorsCut: bool = False
    extended: bool = False

    def __init__(self, raw_title: str, **kwargs):
        super().__init__(raw_title=raw_title, **kwargs)
        parsed = PTN.parse(raw_title, coherent_types=True)
        self.raw_title = raw_title
        self.parsed_title = parsed.get("title")
        self.fetch = check_unwanted_quality(raw_title)
        self.is_multi_audio = check_multi_audio(raw_title)
        self.is_multi_subtitle = check_multi_subtitle(raw_title)
        self.is_complete = check_complete_series(raw_title)
        self.is_4k = any(resolution in ["2160p", "4K", "UHD"] for resolution in parsed.get("resolution", []))
        self.year = parsed.get("year", [])
        self.resolution = parsed.get("resolution", [])
        self.quality = parsed.get("quality", [])
        self.season = parsed.get("season", [])
        self.episode = parsed.get("episode", [])
        self.codec = parsed.get("codec", [])
        self.audio = parsed.get("audio", [])
        self.subtitles = parsed.get("subtitles", [])
        self.language = parsed.get("language", [])
        self.bitDepth = parsed.get("bitDepth", [])
        self.hdr = parsed.get("hdr", False)
        self.proper = parsed.get("proper", False)
        self.repack = parsed.get("repack", False)
        self.remux = parsed.get("remux", False)
        self.upscaled = parsed.get("upscaled", False)
        self.remastered = parsed.get("remastered", False)
        self.directorsCut = parsed.get("directorsCut", False)
        self.extended = parsed.get("extended", False)


class Torrent(BaseModel):
    """Torrent class for storing torrent data."""
    raw_title: str
    infohash: str
    parsed_data: ParsedMediaItem = None
    rank: int = 0

    def __init__(
            self,
            ranking_model: BaseRankingModel,
            raw_title: str,
            infohash: str
    ):
        super().__init__(raw_title=raw_title, infohash=infohash)
        self.parsed_data = ParsedMediaItem(raw_title)
        self.rank = calculate_ranking(self.parsed_data, ranking_model)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Torrent):
            return False
        return self.infohash.lower() == other.infohash.lower()

    def update_rank(self, ranking_model: BaseRankingModel):
        """Update the rank based on the provided ranking model."""
        if self.parsed_data:
            self.rank = calculate_ranking(self.parsed_data, ranking_model)


class ParsedTorrents(BaseModel):
    """ParsedTorrents class for storing scraped torrents."""
    torrents: Dict[str, Torrent] = Field(default_factory=dict)

    def __iter__(self):
        return iter(self.torrents.values())

    def __len__(self):
        return len(self.torrents)

    def add(self, torrent: Torrent):
        """Add a Torrent object."""
        self.torrents[torrent.infohash] = torrent
    
    def sort(self):
        """Sort the torrents by rank and update the dictionary accordingly."""
        sorted_torrents = sorted(self.torrents.values(), key=lambda x: x.rank, reverse=True)
        self.torrents = {torrent.infohash: torrent for torrent in sorted_torrents}


def parser(query: str | None) -> ParsedMediaItem:
    """Parse the given string using the ParsedMediaItem model."""
    return ParsedMediaItem(raw_title=query)

def check_title_match(item, raw_title: str = str, threshold: int = 90) -> bool:
    """Check if the title matches PTN title using levenshtein algorithm."""
    # Lets make this more globally usable by allowing str or MediaItem as input
    if item is None or not raw_title:
        return False
    elif isinstance(item, str):
        return fuzz.ratio(raw_title.lower(), item.lower()) >= threshold
    else:
        target_title = item.title
        if item.type == "season":
            target_title = item.parent.title
        elif item.type == "episode":
            target_title = item.parent.parent.title
        return fuzz.ratio(raw_title.lower(), target_title.lower()) >= threshold

def parse_episodes(string: str, season: int = None) -> List[int]:
    """Get episode numbers from the file name."""
    parsed_data = PTN.parse(string, coherent_types=True)
    parsed_seasons = parsed_data.get("season", [])
    parsed_episodes = parsed_data.get("episode", [])

    if season is not None and (not parsed_seasons or season not in parsed_seasons):
        return []
    
    if isinstance(parsed_episodes, list):
        episodes = parsed_episodes
    elif parsed_episodes is not None:
        episodes = [parsed_episodes]
    else:
        episodes = []
    return episodes

def check_unwanted_quality(string) -> bool:
    """Check if the string contains unwanted quality pattern."""
    return not any(pattern.search(string) for pattern in UNWANTED_QUALITY_COMPILED)

def check_multi_audio(string) -> bool:
    """Check if the string contains multi-audio pattern."""
    return any(pattern.search(string) for pattern in MULTI_AUDIO_COMPILED)

def check_multi_subtitle(string) -> bool:
    """Check if the string contains multi-subtitle pattern."""
    return any(pattern.search(string) for pattern in MULTI_SUBTITLE_COMPILED)

def check_complete_series(string) -> bool:
    """Check if the string contains complete series pattern."""
    return any(pattern.search(string) for pattern in COMPLETE_SERIES_COMPILED)
