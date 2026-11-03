"""Playlist writers and selections (world, lite, favorites, categories)."""
from __future__ import annotations

import re
from pathlib import Path

from .models import Channel
from .normalize import sanitize_attr, sanitize_title


def group_sort_key(country_name: str, international: str):
    return (1 if country_name == international else 0, country_name.casefold())


def channel_lines(ch: Channel, group: str, max_streams: int | None, name_fmt: str) -> list:
    streams = ch.streams[:max_streams] if max_streams else ch.streams
    lines = []
    multi = len(streams) > 1
    for i, s in enumerate(streams, 1):
        title = name_fmt.format(name=ch.name, n=i) if multi else ch.name
        attrs = []
        if ch.tvg_id:
            attrs.append(f'tvg-id="{sanitize_attr(ch.tvg_id)}"')
        attrs.append(f'tvg-name="{sanitize_attr(ch.name)}"')
        if ch.logo:
            attrs.append(f'tvg-logo="{sanitize_attr(ch.logo)}"')
        if ch.country:
            attrs.append(f'tvg-country="{ch.country}"')
        attrs.append(f'group-title="{sanitize_attr(group)}"')
        if s.referrer:
            attrs.append(f'http-referrer="{sanitize_attr(s.referrer)}"')
        if s.user_agent:
            attrs.append(f'http-user-agent="{sanitize_attr(s.user_agent)}"')
        lines.append(f"#EXTINF:-1 {' '.join(attrs)},{sanitize_title(title)}")
        if s.referrer:
            lines.append(f"#EXTVLCOPT:http-referrer={sanitize_title(s.referrer)}")
        if s.user_agent:
            lines.append(f"#EXTVLCOPT:http-user-agent={sanitize_title(s.user_agent)}")
        lines.append(s.url.strip())
    return lines


def render(sections: list, name_fmt: str) -> tuple:
    """sections: list of (group, [Channel], max_streams). Returns (text, entry_count)."""
    out = ["#EXTM3U"]
    n = 0
    for group, chans, max_streams in sections:
        for ch in chans:
            lines = channel_lines(ch, group, max_streams, name_fmt)
            n += sum(1 for l in lines if l.startswith("#EXTINF"))
            out.extend(lines)
    return "\n".join(out) + "\n", n


def by_country(channels: list, international: str) -> list:
    groups: dict = {}
    for ch in channels:
        groups.setdefault(ch.country_name or international, []).append(ch)
    order = sorted(groups, key=lambda g: group_sort_key(g, international))
    return [(g, sorted(groups[g], key=lambda c: (c.name.casefold(), c.tvg_id))) for g in order]


def lite_pick(chans: list, n: int, priority: list) -> list:
    pri = set(priority or [])

    def score(c: Channel):
        return (0 if pri & set(c.categories) else 1, 0 if c.logo else 1,
                0 if c.tvg_id else 1, -len(c.streams), c.name.casefold())

    picked = sorted(chans, key=score)[:n]
    return sorted(picked, key=lambda c: c.name.casefold())


def select_favorites(channels: list, fav_cfg: dict) -> list:
    """Return list of (group_name, [Channel]) in rule order."""
    mode = fav_cfg.get("group_mode", "per_rule")
    prefix = fav_cfg.get("group_prefix", "Favorites: ")
    single = fav_cfg.get("single_group_name", "★ Favorites")
    by_key = sorted(channels, key=lambda c: (0 if c.logo else 1, -len(c.streams), c.name.casefold()))
    result = []
    used_single: set = set()
    for rule in fav_cfg.get("rules") or []:
        limit = int(rule.get("limit", 20))
        picked: list = []
        seen: set = set()
        for pat in rule.get("ids") or []:
            rx = re.compile(pat)
            for c in by_key:
                if len(picked) >= limit:
                    break
                if id(c) in seen or not c.tvg_id:
                    continue
                if rx.search(c.tvg_id):
                    picked.append(c)
                    seen.add(id(c))
                    break  # one channel per explicit id pattern, keeps the list ordered
        countries = {x.upper() for x in rule.get("countries") or []}
        cats = set(rule.get("categories") or [])
        langs = set(rule.get("languages") or [])
        name_rx = re.compile(rule["name_regex"], re.I) if rule.get("name_regex") else None
        has_filter = bool(countries or cats or langs or name_rx)
        if has_filter:
            for c in by_key:
                if len(picked) >= limit:
                    break
                if id(c) in seen:
                    continue
                if countries and c.country not in countries:
                    continue
                if cats and not (cats & set(c.categories)):
                    continue
                if langs and not (langs & set(c.languages)):
                    continue
                if name_rx and not name_rx.search(c.name):
                    continue
                picked.append(c)
                seen.add(id(c))
        if mode == "single":
            picked = [c for c in picked if id(c) not in used_single]
            used_single.update(id(c) for c in picked)
            if picked:
                result.append((single, picked))
        elif picked:
            result.append((f"{prefix}{rule['name']}", picked))
    if mode == "single" and result:
        merged = [c for _, cs in result for c in cs]
        result = [(single, merged)]
    return result


def write(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return len(data)


def build_outputs(channels: list, settings: dict, fav_cfg: dict, out_dir: Path) -> dict:
    """Write all playlists. Returns {filename: {"bytes": n, "entries": n, "channels": n}}."""
    intl = settings.get("international_group", "International")
    name_fmt = settings.get("alternative_name_format", "{name} | {n}")
    groups = by_country(channels, intl)
    files = {}

    fav = select_favorites(channels, fav_cfg)
    fav_streams = int(fav_cfg.get("streams_per_channel", 2))
    fav_sections = [(g, cs, fav_streams) for g, cs in fav]

    world_sections = [(g, cs, None) for g, cs in groups]
    if settings.get("favorites_on_top_of_world", True):
        world_sections = fav_sections + world_sections
    text, n = render(world_sections, name_fmt)
    files["world.m3u"] = {"bytes": write(out_dir / "world.m3u", text), "entries": n,
                          "channels": sum(len(cs) for _, cs, _ in world_sections)}

    lite = settings.get("lite", {})
    per = int(lite.get("per_country", 25))
    lite_streams = int(lite.get("streams_per_channel", 2))
    lite_sections = [(g, lite_pick(cs, per, lite.get("priority_categories")), lite_streams) for g, cs in groups]
    text, n = render(lite_sections, name_fmt)
    files["world-lite.m3u"] = {"bytes": write(out_dir / "world-lite.m3u", text), "entries": n,
                               "channels": sum(len(cs) for _, cs, _ in lite_sections)}

    text, n = render(fav_sections, name_fmt)
    files["favorites.m3u"] = {"bytes": write(out_dir / "favorites.m3u", text), "entries": n,
                              "channels": sum(len(cs) for _, cs, _ in fav_sections)}

    for fname, cats in (settings.get("category_files") or {}).items():
        cs = set(cats)
        sections = []
        for g, chans in groups:
            sel = [c for c in chans if cs & set(c.categories)]
            if sel:
                sections.append((g, sel, None))
        text, n = render(sections, name_fmt)
        files[f"{fname}.m3u"] = {"bytes": write(out_dir / f"{fname}.m3u", text), "entries": n,
                                 "channels": sum(len(x) for _, x, _ in sections)}
    files["_favorite_groups"] = [{"group": g, "channels": len(cs)} for g, cs in fav]
    return files
