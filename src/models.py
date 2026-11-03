"""Plain data containers shared by the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Entry:
    """One stream as read from a source, enriched step by step."""

    source_id: str
    name: str
    url: str
    attrs: dict = field(default_factory=dict)
    group: str = ""
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    tvg_id: str = ""            # as given by the source (IPTV-org style "Id.cc@Feed" when known)
    tvg_logo: str = ""
    tvg_country: str = ""       # raw country hint from the source
    categories: list = field(default_factory=list)
    languages: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    quality: str = ""
    # filled by classify / normalize
    norm_url: str = ""
    channel_key: str = ""       # IPTV-org based key ("Id.cc" or "Id.cc@Feed") when known
    country: str = ""           # ISO alpha-2 (or XK) or "" for International
    country_method: str = ""
    nsfw: bool = False
    blocked_reason: str = ""


@dataclass
class Channel:
    key: tuple
    name: str
    country: str
    country_name: str
    tvg_id: str = ""
    logo: str = ""
    categories: list = field(default_factory=list)
    languages: list = field(default_factory=list)
    streams: list = field(default_factory=list)   # list[Entry], best first
    dropped_alternatives: int = 0

    @property
    def sources(self) -> list:
        seen = []
        for s in self.streams:
            if s.source_id not in seen:
                seen.append(s.source_id)
        return seen
