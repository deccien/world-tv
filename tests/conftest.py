import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config as cfg  # noqa: E402
from src.parse import IptvOrgData  # noqa: E402


@pytest.fixture
def settings():
    return cfg.load_settings()


@pytest.fixture
def countries_cfg():
    return cfg.load_countries()


@pytest.fixture
def iptv():
    channels = [
        {"id": "Kan11.il", "name": "Kan 11", "alt_names": [], "country": "IL", "categories": ["general"],
         "is_nsfw": False, "closed": None},
        {"id": "BBCNews.uk", "name": "BBC News", "alt_names": [], "country": "UK", "categories": ["news"],
         "is_nsfw": False, "closed": None},
        {"id": "AlJazeera.qa", "name": "Al Jazeera", "alt_names": [], "country": "QA", "categories": ["news"],
         "is_nsfw": False, "closed": None},
        {"id": "ChannelsTV.ng", "name": "Channels TV", "alt_names": [], "country": "NG", "categories": ["news"],
         "is_nsfw": False, "closed": None},
        {"id": "Adult1.us", "name": "Adult One", "alt_names": [], "country": "US", "categories": ["xxx"],
         "is_nsfw": True, "closed": None},
        {"id": "Takedown.es", "name": "Takedown TV", "alt_names": [], "country": "ES", "categories": ["sports"],
         "is_nsfw": False, "closed": None},
        {"id": "WABC.us", "name": "WABC", "alt_names": [], "country": "US", "categories": ["general"],
         "is_nsfw": False, "closed": None},
    ]
    feeds = [
        {"channel": "AlJazeera.qa", "id": "Arabic", "name": "Arabic", "is_main": True, "languages": ["ara"]},
        {"channel": "AlJazeera.qa", "id": "English", "name": "English", "is_main": False, "languages": ["eng"]},
        {"channel": "AlJazeera.qa", "id": "EnglishHD", "name": "English HD", "is_main": False, "languages": ["eng"]},
        {"channel": "WABC.us", "id": "East", "name": "East", "is_main": True, "languages": ["eng"]},
        {"channel": "WABC.us", "id": "West", "name": "West", "is_main": False, "languages": ["eng"]},
        {"channel": "Kan11.il", "id": "SD", "name": "SD", "is_main": True, "languages": ["heb"]},
    ]
    blocklist = [{"channel": "Takedown.es", "reason": "dmca"}]
    logos = [{"channel": "Kan11.il", "feed": None, "in_use": True, "width": 100, "url": "https://x/kan.png"}]
    return IptvOrgData(channels, feeds, logos, blocklist)
