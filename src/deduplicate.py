"""Exact-URL dedup and grouping of alternative streams into channels.

Grouping key:
  * IPTV-org channel key ("Id.cc" or "Id.cc@RegionalFeed") when known -> regional feeds never merge
  * otherwise (country, normalized name)
Name-keyed entries join an IPTV-org channel when the normalized name matches that channel's
display name in the same country.
"""
from __future__ import annotations

from collections import defaultdict

from .models import Channel, Entry
from .normalize import clean_title, normalize_name

BAD_LABELS = ("Not 24/7", "Geo-blocked")


def dedup_urls(entries: list) -> tuple:
    """Keep the first occurrence of each normalized URL (entries are in source-priority order).

    Returns (kept, duplicates_per_source).
    """
    seen: set = set()
    kept = []
    dups: dict = defaultdict(int)
    for e in entries:
        if e.norm_url in seen:
            dups[e.source_id] += 1
            continue
        seen.add(e.norm_url)
        kept.append(e)
    return kept, dict(dups)


def _quality_rank(q: str) -> int:
    q = (q or "").lower().rstrip("pi")
    try:
        return int(q)
    except ValueError:
        return 0


def stream_sort_key(e: Entry, source_rank: dict):
    bad = sum(1 for l in (e.labels or []) if l in BAD_LABELS)
    return (bad, source_rank.get(e.source_id, 999), 0 if e.url.startswith("https") else 1, -_quality_rank(e.quality))


def group_channels(entries: list, source_rank: dict, max_alternatives: int, country_name,
                   international: str = "International") -> list:
    _cn = country_name
    country_name = lambda c: (_cn(c) if c else "") or international  # noqa: E731
    groups: dict = {}
    name_to_key: dict = {}

    # first pass: IPTV-org keyed
    for e in entries:
        if e.channel_key:
            key = ("id", e.channel_key)
            ch = groups.get(key)
            if ch is None:
                ch = groups[key] = Channel(key=key, name=clean_title(e.name), country=e.country,
                                           country_name=country_name(e.country), tvg_id=e.channel_key)
                name_to_key.setdefault((e.country, normalize_name(ch.name)), key)
            ch.streams.append(e)
    # second pass: name keyed
    for e in entries:
        if e.channel_key:
            continue
        nn = normalize_name(e.name) or e.norm_url
        key = name_to_key.get((e.country, nn)) or ("name", e.country, nn)
        ch = groups.get(key)
        if ch is None:
            ch = groups[key] = Channel(key=key, name=clean_title(e.name), country=e.country,
                                       country_name=country_name(e.country), tvg_id=e.tvg_id or "")
        ch.streams.append(e)

    out = []
    for ch in groups.values():
        ch.streams.sort(key=lambda s: stream_sort_key(s, source_rank))
        if max_alternatives and len(ch.streams) > max_alternatives:
            ch.dropped_alternatives = len(ch.streams) - max_alternatives
            ch.streams = ch.streams[:max_alternatives]
        for s in ch.streams:
            if not ch.logo and s.tvg_logo:
                ch.logo = s.tvg_logo
            for c in s.categories or []:
                if c not in ch.categories:
                    ch.categories.append(c)
            for l in s.languages or []:
                if l not in ch.languages:
                    ch.languages.append(l)
        out.append(ch)
    return out
