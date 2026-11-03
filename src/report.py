"""report.json / report.md, output validation and the entry-drop safeguard."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pycountry

CRED_RE = re.compile(r"(password|passwd|pass|token|apikey|api_key|secret|jwt|auth)=([^&\s]+)", re.I)


class ValidationError(Exception):
    pass


class SafeguardError(Exception):
    pass


def iso_without(country_codes: set, names) -> list:
    out = []
    for c in pycountry.countries:
        if c.alpha_2 not in country_codes:
            out.append({"code": c.alpha_2, "name": names.name(c.alpha_2)})
    return sorted(out, key=lambda x: x["name"].casefold())


def build_report(*, build_time: str, channels: list, files: dict, source_stats: list, exclusions: dict,
                 names, settings: dict, warnings: list, intl: str) -> dict:
    countries: dict = {}
    for ch in channels:
        key = ch.country or ""
        d = countries.setdefault(key, {"code": ch.country or None, "name": ch.country_name or intl,
                                       "channels": 0, "streams": 0})
        d["channels"] += 1
        d["streams"] += len(ch.streams)
    unique_urls = {s.norm_url for ch in channels for s in ch.streams}
    with_alt = sum(1 for ch in channels if len(ch.streams) > 1)
    alt_streams = sum(len(ch.streams) - 1 for ch in channels)
    real = sorted([v for k, v in countries.items() if k], key=lambda x: x["name"].casefold())
    intl_row = countries.get("")
    world = files.get("world.m3u", {})
    fav_groups = files.pop("_favorite_groups", [])
    return {
        "title": settings.get("title", "World TV"),
        "build_time_utc": build_time,
        "pages_url": settings.get("resolved_pages_url", ""),
        "totals": {
            "world_entries": world.get("entries", 0),
            "world_channel_entries": sum(len(ch.streams) for ch in channels),
            "unique_urls": len(unique_urls),
            "unique_channels": len(channels),
            "channels_with_alternatives": with_alt,
            "alternative_streams": alt_streams,
            "alternatives_dropped_by_cap": sum(ch.dropped_alternatives for ch in channels),
            "countries_with_channels": len(real),
            "iso_countries_without_channels": 0,
            "international_channels": intl_row["channels"] if intl_row else 0,
            "sources_ok": sum(1 for s in source_stats if s["status"] == "fresh"),
            "sources_from_cache": sum(1 for s in source_stats if s["status"] == "cache"),
            "sources_failed": sum(1 for s in source_stats if s["status"] == "failed"),
            "sources_total": len(source_stats),
        },
        "countries": real + ([intl_row] if intl_row else []),
        "iso_countries_without_channels": [],
        "favorites": fav_groups,
        "sources": source_stats,
        "exclusions": exclusions,
        "files": files,
        "settings": {
            "max_alternatives": settings.get("max_alternatives"),
            "lite_per_country": settings.get("lite", {}).get("per_country"),
            "favorites_on_top_of_world": settings.get("favorites_on_top_of_world"),
            "max_entry_drop": settings.get("max_entry_drop"),
        },
        "warnings": warnings,
    }


def finish_report(report: dict, names) -> dict:
    codes = {c["code"] for c in report["countries"] if c.get("code")}
    missing = iso_without(codes, names)
    report["iso_countries_without_channels"] = missing
    report["totals"]["iso_countries_without_channels"] = len(missing)
    return report


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return str(n)


def render_markdown(r: dict) -> str:
    t = r["totals"]
    L = [f"# {r['title']} build report", "", f"Built: **{r['build_time_utc']}** (UTC)", "",
         "## Totals", "",
         "| Metric | Value |", "|---|---|"]
    for k, v in t.items():
        L.append(f"| {k.replace('_', ' ')} | {v:,} |" if isinstance(v, int) else f"| {k} | {v} |")
    L += ["", "## Files", "", "| File | Entries | Channels | Size |", "|---|---:|---:|---:|"]
    for f, d in r["files"].items():
        L.append(f"| {f} | {d['entries']:,} | {d['channels']:,} | {human_size(d['bytes'])} |")
    L += ["", "## Sources", "",
          "| Source | Status | Parsed | Excluded | Duplicates | Unique URLs kept | Countries | Fetched (UTC) | Error |",
          "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for s in r["sources"]:
        L.append(f"| {s['name']} | {s['status']} | {s['parsed']:,} | {sum(s['excluded'].values()):,} | "
                 f"{s['duplicates']:,} | {s['unique_urls']:,} | {s['countries']} | {s.get('fetched_at', '')} | "
                 f"{s.get('error', '')[:120]} |")
    L += ["", "## Exclusions", ""]
    for k, v in sorted(r["exclusions"].items(), key=lambda x: -x[1]):
        L.append(f"- {k}: {v:,}")
    if r.get("favorites"):
        L += ["", "## Favorites", ""] + [f"- {g['group']}: {g['channels']}" for g in r["favorites"]]
    L += ["", f"## Countries with channels ({t['countries_with_channels']})", "",
          "| Country | Code | Channels | Streams |", "|---|---|---:|---:|"]
    for c in r["countries"]:
        L.append(f"| {c['name']} | {c['code'] or '-'} | {c['channels']:,} | {c['streams']:,} |")
    L += ["", f"## ISO countries without channels ({t['iso_countries_without_channels']})", "",
          ", ".join(f"{c['name']} ({c['code']})" for c in r["iso_countries_without_channels"]) or "None"]
    if r.get("warnings"):
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ validation

def validate_playlist(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{path.name}: not UTF-8 ({exc})") from exc
    lines = text.split("\n")
    if not lines or lines[0].strip() != "#EXTM3U":
        raise ValidationError(f"{path.name}: missing #EXTM3U header")
    if "\r" in text:
        raise ValidationError(f"{path.name}: contains CR characters")
    entries = 0
    pending = None
    for i, line in enumerate(lines[1:], 2):
        if not line:
            continue
        if line.startswith("#EXTINF"):
            if pending is not None:
                raise ValidationError(f"{path.name}:{pending}: #EXTINF without URL")
            if 'group-title="' not in line or 'group-title=""' in line:
                raise ValidationError(f"{path.name}:{i}: entry without group-title")
            pending = i
        elif line.startswith("#EXTVLCOPT:"):
            continue
        elif line.startswith("#"):
            continue
        else:
            if pending is None:
                raise ValidationError(f"{path.name}:{i}: URL without #EXTINF")
            if not re.match(r"^https?://\S+$", line):
                raise ValidationError(f"{path.name}:{i}: not an http(s) URL")
            entries += 1
            pending = None
    if pending is not None:
        raise ValidationError(f"{path.name}:{pending}: trailing #EXTINF without URL")
    return {"entries": entries, "bytes": len(raw)}


def validate_outputs(out_dir: Path, files: dict, settings: dict, log_lines: list) -> list:
    """Raises ValidationError on hard failures; returns warnings."""
    warnings = []
    for f, meta in files.items():
        v = validate_playlist(out_dir / f)
        if v["entries"] != meta["entries"]:
            raise ValidationError(f"{f}: entry count mismatch ({v['entries']} vs {meta['entries']})")
    w = files.get("world.m3u", {})
    if w.get("entries", 0) == 0:
        raise ValidationError("world.m3u is empty")
    lim = settings.get("limits", {})
    if w.get("entries", 0) > int(lim.get("max_world_entries", 40000)):
        warnings.append(f"world.m3u has {w['entries']} entries (> {lim.get('max_world_entries')})")
    if w.get("bytes", 0) > float(lim.get("max_world_mb", 15)) * 1024 * 1024:
        warnings.append(f"world.m3u is {human_size(w['bytes'])} (> {lim.get('max_world_mb')} MB)")
    for line in log_lines:
        if CRED_RE.search(line):
            raise ValidationError("build log contains a credential-looking parameter; refusing to publish")
    return warnings


# ------------------------------------------------------------------ safeguard

def check_drop(new_entries: int, previous: dict | None, max_drop: float) -> str:
    """Raise SafeguardError if entries fell by more than max_drop vs the published report."""
    if not previous:
        return "no previous report.json available; safeguard skipped"
    try:
        old = int(previous["totals"]["world_entries"])
    except (KeyError, TypeError, ValueError):
        return "previous report.json has no totals.world_entries; safeguard skipped"
    if old <= 0:
        return "previous report had 0 entries; safeguard skipped"
    drop = (old - new_entries) / old
    if drop > max_drop:
        raise SafeguardError(f"world.m3u entries dropped {drop:.0%} ({old} -> {new_entries}); "
                             f"limit is {max_drop:.0%}. Keeping the previous deployment.")
    return f"entries {old} -> {new_entries} ({-drop:+.1%}); within limit"


def write_json(path: Path, data: dict) -> int:
    b = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    path.write_bytes(b)
    return len(b)
