"""World TV build: python -m src.main [--offline] [--no-safeguard]"""
from __future__ import annotations

import argparse
import re as _re
import logging
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from .classify import Classifier
from .deduplicate import dedup_urls, group_channels
from .fetch import fetch_all, fetch_json, load_cache, FetchResult
from .generate import build_outputs, build_regional
from .normalize import normalize_url
from .parse import (HLSPlaylistError, decode_bytes, load_iptvorg, load_json, parse_famelack,
                    parse_iptvorg_streams, parse_m3u, parse_mjh_channels)
from .report import (SafeguardError, ValidationError, build_report, check_drop, finish_report,
                     render_markdown, validate_outputs, write_json)

ROOT = cfg.ROOT
log = logging.getLogger("worldtv")


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list = []

    def emit(self, record):
        self.lines.append(self.format(record))


def fetch_jobs(sources: list) -> list:
    jobs = []
    for s in sources:
        if s["type"] == "iptvorg_api":
            for name, url in s["urls"].items():
                jobs.append((f"{s['id']}__{name}", url))
        else:
            jobs.append((s["id"], s["url"]))
    return jobs


def offline_results(jobs: list, cache_dir: Path) -> dict:
    out = {}
    for key, url in jobs:
        content, ts = load_cache(cache_dir, key)
        out[key] = FetchResult(key, url, "cache" if content else "failed", content,
                               "" if content else "offline and no cache", ts)
    return out


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build World TV playlists")
    ap.add_argument("--offline", action="store_true", help="use cache/ only, no network")
    ap.add_argument("--no-safeguard", action="store_true", help="skip the entry-drop safeguard")
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    lh = ListHandler()
    fmt = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    lh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root_log = logging.getLogger("worldtv")
    root_log.handlers[:] = [sh, lh]
    root_log.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    t0 = time.time()
    cdir = Path(args.config_dir) if args.config_dir else None
    settings = cfg.load_settings(cdir)
    sources = cfg.load_sources(cdir)
    countries_cfg = cfg.load_countries(cdir)
    fav_cfg = cfg.load_favorites(cdir)
    out_dir = Path(args.out) if args.out else ROOT / settings.get("output_dir", "site")
    cache_dir = ROOT / settings.get("cache_dir", "cache")
    intl = settings.get("international_group", "International")
    build_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    jobs = fetch_jobs(sources)
    results = offline_results(jobs, cache_dir) if args.offline else fetch_all(jobs, settings, cache_dir)

    # ---- IPTV-org metadata (needed by every other source for classification/exclusion)
    iptv = None
    iptv_src = next((s for s in sources if s["type"] == "iptvorg_api"), None)
    if iptv_src:
        raw = {}
        for name in iptv_src["urls"]:
            r = results[f"{iptv_src['id']}__{name}"]
            if r.content:
                try:
                    raw[name] = load_json(r.content)
                except ValueError as exc:
                    log.error("IPTV-org %s is not valid JSON: %s", name, exc)
        if "channels" in raw:
            iptv = load_iptvorg(raw)
        else:
            log.error("IPTV-org channels.json unavailable: classification falls back to source hints")

    clf = Classifier(settings, countries_cfg, iptv)
    names = clf.names

    # ---- parse every source in priority order
    all_entries = []
    stats = []
    for s in sources:
        st = {"id": s["id"], "name": s["name"], "type": s["type"], "url": s.get("url") or s.get("urls", {}).get("streams"),
              "status": "failed", "error": "", "fetched_at": "", "parsed": 0, "excluded": {}, "duplicates": 0,
              "unique_urls": 0, "countries": 0}
        try:
            if s["type"] == "iptvorg_api":
                keys = [f"{s['id']}__{n}" for n in s["urls"]]
                rs = [results[k] for k in keys]
                crit = [results[f"{s['id']}__streams"], results[f"{s['id']}__channels"]]
                statuses = {r.status for r in crit}
                st["status"] = "failed" if "failed" in statuses else ("cache" if "cache" in statuses else "fresh")
                st["error"] = "; ".join(f"{k.split('__')[1]}: {r.error}" for k, r in zip(keys, rs) if r.error)
                st["fetched_at"] = min((r.fetched_at for r in crit if r.fetched_at), default="")
                sr = crit[0]
                if not (iptv and sr.content):
                    raise RuntimeError("streams.json or channels.json missing")
                entries, extra = parse_iptvorg_streams(load_json(sr.content), iptv, s["id"],
                                                       bool(settings.get("include_unlinked_iptvorg_streams")))
                st.update(extra)
            else:
                r = results[s["id"]]
                st["status"], st["error"], st["fetched_at"] = r.status, r.error, r.fetched_at
                if not r.content:
                    raise RuntimeError(r.error or "no content")
                if s["type"] == "m3u":
                    entries = parse_m3u(decode_bytes(r.content, s.get("encoding")), s["id"])
                elif s["type"] == "json_custom":
                    doc = load_json(r.content)
                    adapter = s.get("adapter")
                    if adapter == "famelack":
                        entries = parse_famelack(doc, s["id"])
                    elif adapter == "mjh_channels":
                        entries = parse_mjh_channels(doc, s["id"], s["options"]["url_template"])
                    else:
                        raise ValueError(f"unknown json adapter {adapter!r}")
                else:
                    raise ValueError(f"unknown source type {s['type']!r}")
        except (HLSPlaylistError, ValueError, RuntimeError, KeyError) as exc:
            st["status"] = "failed"
            st["error"] = (st["error"] + "; " if st["error"] else "") + f"{type(exc).__name__}: {exc}"
            log.error("source %s failed: %s", s["id"], exc)
            stats.append(st)
            continue
        st["parsed"] = len(entries)
        hints = s.get("country_hints") or {}
        ex_rx = hints.get("exclude_groups_regex")
        ex_rx = _re.compile(ex_rx, _re.I) if ex_rx else None
        for e in entries:
            e._src_stats = st  # type: ignore[attr-defined]
            e._hints = hints   # type: ignore[attr-defined]
            if ex_rx and ex_rx.search(e.group or ""):
                e.blocked_reason = "excluded_group"
        all_entries.extend(entries)
        stats.append(st)
        log.info("source %s: %d entries (%s)", s["id"], len(entries), st["status"])

    # ---- normalize, link, classify, exclude
    blocked_urls: set = set()
    if iptv:
        sr = results.get(f"{iptv_src['id']}__streams") if iptv_src else None
        if sr and sr.content:
            for row in load_json(sr.content):
                c = row.get("channel")
                if c and (c in iptv.blocked or c in iptv.nsfw):
                    blocked_urls.add(normalize_url(row.get("url", "")))
    exclusions = Counter()
    kept = []
    for e in all_entries:
        e.url = e.url.strip()
        e.norm_url = normalize_url(e.url)
        clf.link(e)
        clf.hint_categories(e)
        clf.classify_country(e, e._hints)  # type: ignore[attr-defined]
        clf.link_by_name_in_country(e)
        reason = clf.exclusion(e, blocked_urls)
        if reason:
            exclusions[reason] += 1
            e._src_stats["excluded"][reason] = e._src_stats["excluded"].get(reason, 0) + 1  # type: ignore
            continue
        kept.append(e)

    kept, dups = dedup_urls(kept)
    exclusions["duplicate_url"] = sum(dups.values())
    per_src_countries = defaultdict(set)
    per_src_urls = Counter()
    for e in kept:
        per_src_urls[e.source_id] += 1
        per_src_countries[e.source_id].add(e.country or "INT")
    for st in stats:
        st["duplicates"] = dups.get(st["id"], 0)
        st["unique_urls"] = per_src_urls.get(st["id"], 0)
        st["countries"] = len(per_src_countries.get(st["id"], ()))

    source_rank = {s["id"]: i for i, s in enumerate(sources)}
    channels = group_channels(kept, source_rank, int(settings.get("max_alternatives", 8)),
                              names.name, intl)
    log.info("channels: %d from %d unique URLs", len(channels), len(kept))
    if not channels:
        log.error("no channels at all; refusing to publish")
        return 3

    # ---- write outputs
    tmp_out = out_dir.parent / (out_dir.name + ".new")
    if tmp_out.exists():
        shutil.rmtree(tmp_out)
    tmp_out.mkdir(parents=True)
    files = build_outputs(channels, settings, fav_cfg, tmp_out)
    regional = build_regional(channels, settings, cfg.load_regions(cdir), tmp_out)
    files.update(regional)
    for fname, meta in regional.items():
        log.info("  %-28s %6d entries %10d bytes  (%s)", fname, meta["entries"], meta["bytes"], meta["region"])
    fav_groups = files.get("_favorite_groups")
    playlist_files = {k: v for k, v in files.items() if not k.startswith("_")}
    try:
        warnings = validate_outputs(tmp_out, playlist_files, settings, lh.lines)
    except ValidationError as exc:
        log.error("validation failed: %s", exc)
        return 4

    report = build_report(build_time=build_time, channels=channels, files=dict(playlist_files, _favorite_groups=fav_groups),
                          source_stats=stats, exclusions=dict(exclusions), names=names, settings=settings,
                          warnings=warnings, intl=intl)
    report = finish_report(report, names)

    # ---- safeguard vs the live site
    note = "safeguard disabled"
    if not args.no_safeguard:
        prev = None
        url = settings.get("resolved_pages_url")
        if url and not args.offline:
            prev = fetch_json(url + "report.json", settings)
        try:
            note = check_drop(report["totals"]["world_entries"], prev, float(settings.get("max_entry_drop", 0.30)))
        except SafeguardError as exc:
            log.error("SAFEGUARD: %s", exc)
            return 5
    report["safeguard"] = note
    report["build_seconds"] = round(time.time() - t0, 1)
    log.info("safeguard: %s", note)

    # ---- landing page + reports, then swap into place
    tmpl = out_dir / "index.html"          # hand-written landing page lives in site/
    if not tmpl.exists():
        tmpl = ROOT / "templates" / "index.html"
    if tmpl.exists():
        shutil.copyfile(tmpl, tmp_out / "index.html")
    (tmp_out / ".nojekyll").write_text("", encoding="utf-8")
    write_json(tmp_out / "report.json", report)
    (tmp_out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_out.replace(out_dir)

    t = report["totals"]
    log.info("done: %d entries, %d unique URLs, %d channels, %d countries, sources ok %d / cache %d / failed %d",
             t["world_entries"], t["unique_urls"], t["unique_channels"], t["countries_with_channels"],
             t["sources_ok"], t["sources_from_cache"], t["sources_failed"])
    for f, d in playlist_files.items():
        log.info("  %-20s %7d entries %10d bytes", f, d["entries"], d["bytes"])
    for w in warnings:
        log.warning(w)
    if url := settings.get("resolved_pages_url"):
        log.info("master playlist URL: %sworld.m3u", url)
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
