"""Parsers: tolerant M3U reader plus adapters for JSON sources."""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from .models import Entry


class HLSPlaylistError(ValueError):
    """The document is an HLS media/master playlist, not a channel list."""


class NotAPlaylistError(ValueError):
    pass


# Tags that only appear in HLS media/master playlists (RFC 8216), never in channel lists.
HLS_TAGS = ("#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE", "#EXT-X-STREAM-INF",
            "#EXT-X-PLAYLIST-TYPE", "#EXT-X-ENDLIST", "#EXT-X-KEY", "#EXT-X-MAP",
            "#EXT-X-DISCONTINUITY-SEQUENCE", "#EXT-X-I-FRAME-STREAM-INF", "#EXT-X-PART-INF")

_ATTR_RE = re.compile(r'([A-Za-z0-9_:.-]+)\s*=\s*"([^"]*)"')
_ATTR_UNQUOTED_RE = re.compile(r'([A-Za-z0-9_:.-]+)=([^\s",]+)')


def decode_bytes(data: bytes, encoding_hint: Optional[str] = None) -> str:
    """Decode playlist bytes: BOM-aware UTF-8/16, then the hint, then cp1252, then latin-1."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in [e for e in (encoding_hint, "cp1252") if e]:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1")


def parse_extinf(line: str):
    """Return (duration, attrs, title) for an #EXTINF line.

    Robust against commas inside quoted attribute values (user agents) and missing attributes.
    """
    body = line[len("#EXTINF:"):] if line.upper().startswith("#EXTINF:") else line
    attrs: dict = {}
    last_end = 0
    for m in _ATTR_RE.finditer(body):
        attrs[m.group(1).lower()] = m.group(2).strip()
        last_end = m.end()
    if last_end:
        rest = body[last_end:]
        idx = rest.find(",")
        title = rest[idx + 1:] if idx >= 0 else ""
        head = body[:last_end]
    else:
        idx = body.find(",")
        head = body[:idx] if idx >= 0 else body
        title = body[idx + 1:] if idx >= 0 else ""
        for m in _ATTR_UNQUOTED_RE.finditer(head):
            attrs[m.group(1).lower()] = m.group(2).strip()
    dur_m = re.match(r"\s*(-?\d+(?:\.\d+)?)", head)
    duration = dur_m.group(1) if dur_m else "-1"
    return duration, attrs, title.strip()


def _split_pipe_headers(url: str):
    """Kodi style 'url|User-Agent=x&Referer=y' -> (url, ua, referrer)."""
    if "|" not in url:
        return url, None, None
    base, _, hdrs = url.partition("|")
    ua = ref = None
    for part in hdrs.split("&"):
        k, _, v = part.partition("=")
        k = k.strip().lower()
        if k == "user-agent":
            ua = v.strip()
        elif k in ("referer", "referrer"):
            ref = v.strip()
    return base.strip(), ua, ref


def _split_list(value: str) -> list:
    return [x.strip() for x in re.split(r"[;,|]", value or "") if x.strip()]


def parse_m3u(text: str, source_id: str) -> list:
    """Parse a channel-list M3U. Raises HLSPlaylistError for HLS media/master playlists."""
    text = text.lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    upper_head = [ln.strip().upper() for ln in lines[:400]]
    if any(ln.startswith(HLS_TAGS) for ln in upper_head):
        raise HLSPlaylistError(f"{source_id}: document is an HLS playlist, not a channel list")
    if not any(ln.startswith(("#EXTM3U", "#EXTINF")) for ln in upper_head):
        raise NotAPlaylistError(f"{source_id}: no #EXTM3U/#EXTINF header")

    out: list = []
    cur = None
    for raw in lines:
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        up = line.upper()
        if up.startswith("#EXTINF"):
            _, attrs, title = parse_extinf(line)
            cur = {"attrs": attrs, "title": title, "ref": attrs.get("http-referrer") or attrs.get("http-referer"),
                   "ua": attrs.get("http-user-agent") or attrs.get("user-agent"), "grp": attrs.get("group-title", ""),
                   "drm": False}
            continue
        if cur is None:
            continue
        if up.startswith("#EXTVLCOPT:"):
            opt = line.split(":", 1)[1]
            k, _, v = opt.partition("=")
            k = k.strip().lower()
            if k in ("http-referrer", "http-referer"):
                cur["ref"] = v.strip() or cur["ref"]
            elif k == "http-user-agent":
                cur["ua"] = v.strip() or cur["ua"]
            continue
        if up.startswith("#EXTGRP:"):
            if not cur["grp"]:
                cur["grp"] = line.split(":", 1)[1].strip()
            continue
        if up.startswith("#KODIPROP:"):
            if "license_key" in line.lower() or "license_type" in line.lower():
                cur["drm"] = True
            continue
        if line.startswith("#"):
            continue
        # a URI line
        url, ua2, ref2 = _split_pipe_headers(line)
        a = cur["attrs"]
        title = cur["title"] or a.get("tvg-name", "") or "Unnamed channel"
        e = Entry(source_id=source_id, name=title, url=url, attrs=a, group=cur["grp"],
                  referrer=cur["ref"] or ref2, user_agent=cur["ua"] or ua2,
                  tvg_id=a.get("tvg-id", ""), tvg_logo=a.get("tvg-logo", ""),
                  tvg_country=a.get("tvg-country", ""),
                  languages=_split_list(a.get("tvg-language", "")))
        if cur["drm"]:
            e.blocked_reason = "drm"
        if "\u24bc" in title or "[geo-blocked]" in title.lower():   # Free-TV marks geo-blocked with Ⓖ
            e.labels.append("Geo-blocked")
        if "[not 24/7]" in title.lower():
            e.labels.append("Not 24/7")
        out.append(e)
        cur = None
    return out


# ---------------------------------------------------------------- IPTV-org API

class IptvOrgData:
    """Metadata index built from the IPTV-org API."""

    def __init__(self, channels: list, feeds: list, logos: list, blocklist: list,
                 categories: list | None = None, countries: list | None = None):
        self.channels = {c["id"]: c for c in channels}
        self.feeds = {(f["channel"], f["id"]): f for f in feeds}
        self.main_feed = {f["channel"]: f["id"] for f in feeds if f.get("is_main")}
        self.blocked = {}
        for b in blocklist:
            self.blocked.setdefault(b["channel"], b.get("reason", "blocked"))
        self.category_ids = {c["id"] for c in (categories or [])}
        self.countries = {c["code"]: c for c in (countries or [])}
        self.logo = {}
        # prefer in-use, feed-specific, then larger
        for lg in sorted(logos, key=lambda x: (not x.get("in_use", True), -(x.get("width") or 0))):
            self.logo.setdefault((lg["channel"], lg.get("feed")), lg["url"])
        self.nsfw = {cid for cid, c in self.channels.items()
                     if c.get("is_nsfw") or "xxx" in (c.get("categories") or [])}

    def logo_for(self, cid: str, feed: Optional[str]) -> str:
        return self.logo.get((cid, feed)) or self.logo.get((cid, None)) or ""

    def canonical_feed(self, cid: str, feed: Optional[str]) -> Optional[str]:
        """Feed part of the channel key. None = the main programme.

        'XHD' collapses onto 'X' when that feed exists, plain SD/HD variants collapse onto
        the main feed; every other (regional/language) feed stays separate.
        """
        if not feed:
            return None
        f = feed
        if (cid, f) in self.feeds and f.upper().endswith("HD") and len(f) > 2 and (cid, f[:-2]) in self.feeds:
            f = f[:-2]
        if self.main_feed.get(cid) == f or f.upper() in ("SD", "HD", "FHD", "UHD", "4K"):
            return None
        return f

    def key_for(self, tvg_id: str) -> tuple:
        """'Id.cc@Feed' -> (channel_id or '', channel_key or '')."""
        if not tvg_id:
            return "", ""
        cid, _, feed = tvg_id.partition("@")
        if cid not in self.channels:
            # IPTV-org ids are case-sensitive but some sources lowercase them
            low = getattr(self, "_lower", None)
            if low is None:
                low = self._lower = {k.lower(): k for k in self.channels}
            cid = low.get(cid.lower(), "")
            if not cid:
                return "", ""
        cf = self.canonical_feed(cid, feed or None)
        return cid, (f"{cid}@{cf}" if cf else cid)

    def display_name(self, cid: str, feed_key: Optional[str]) -> str:
        name = self.channels[cid]["name"]
        if feed_key:
            f = self.feeds.get((cid, feed_key))
            fname = (f or {}).get("name") or feed_key
            if fname.lower() not in name.lower():
                name = f"{name} {fname}"
        return name


def load_iptvorg(raw: dict) -> IptvOrgData:
    return IptvOrgData(raw["channels"], raw.get("feeds", []), raw.get("logos", []), raw.get("blocklist", []),
                       raw.get("categories", []), raw.get("countries", []))


def parse_iptvorg_streams(streams: list, data: IptvOrgData, source_id: str, include_unlinked: bool) -> tuple:
    """Return (entries, stats). Entries carry authoritative IPTV-org metadata."""
    out = []
    unlinked = 0
    for s in streams:
        url = (s.get("url") or "").strip()
        if not url:
            continue
        cid = s.get("channel")
        if not cid or cid not in data.channels:
            unlinked += 1
            if not include_unlinked:
                continue
            e = Entry(source_id=source_id, name=s.get("title") or "Unnamed channel", url=url,
                      referrer=s.get("referrer"), user_agent=s.get("user_agent"),
                      labels=list(s.get("labels") or []), quality=s.get("quality") or "")
            out.append(e)
            continue
        ch = data.channels[cid]
        feed = s.get("feed")
        cf = data.canonical_feed(cid, feed)
        key = f"{cid}@{cf}" if cf else cid
        fobj = data.feeds.get((cid, feed)) or {}
        e = Entry(source_id=source_id, name=data.display_name(cid, cf), url=url,
                  referrer=s.get("referrer"), user_agent=s.get("user_agent"),
                  tvg_id=f"{cid}@{feed}" if feed else cid,
                  tvg_logo=data.logo_for(cid, feed),
                  tvg_country=ch.get("country") or "",
                  categories=list(ch.get("categories") or []),
                  languages=list(fobj.get("languages") or []),
                  labels=list(s.get("labels") or []), quality=s.get("quality") or "")
        e.channel_key = key
        e.country = ""  # resolved in classify
        e.attrs = {"iptvorg_channel": cid}
        if cid in data.nsfw:
            e.nsfw = True
        if cid in data.blocked:
            e.blocked_reason = f"iptvorg_blocklist:{data.blocked[cid]}"
        if ch.get("closed"):
            e.attrs["closed"] = ch["closed"]
        out.append(e)
    return out, {"unlinked_streams": unlinked}


# ---------------------------------------------------------------- JSON adapters

def parse_famelack(doc, source_id: str) -> list:
    out = []
    items = doc if isinstance(doc, list) else doc.get("channels", [])
    for it in items:
        streams = ((it.get("sources") or {}).get("streams")) or []
        for url in streams:
            if not isinstance(url, str):
                continue
            e = Entry(source_id=source_id, name=it.get("name") or "Unnamed channel", url=url.strip(),
                      tvg_country=(it.get("country") or ""), languages=list(it.get("languages") or []))
            if it.get("isGeoBlocked"):
                e.labels.append("Geo-blocked")
            out.append(e)
    return out


def parse_mjh_channels(doc: dict, source_id: str, url_template: str) -> list:
    """i.mjh.nz '.channels.json' (Samsung TV Plus / Pluto TV)."""
    out = []
    headers = {k.lower(): v for k, v in (doc.get("headers") or {}).items()}
    if any(k not in ("user-agent", "referer", "referrer") for k in headers):
        # e.g. a token header: we cannot express it in M3U safely
        raise ValueError(f"{source_id}: needs headers other than user-agent/referrer")
    slug_t = doc.get("slug")
    regions = doc.get("regions") or {}
    if not regions and doc.get("channels"):
        regions = {"": {"channels": doc["channels"]}}
    for region, rdata in regions.items():
        for cid, ch in (rdata.get("channels") or {}).items():
            slug = slug_t.format(id=cid) if slug_t else cid
            url = url_template.format(id=cid, slug=slug, region=region)
            e = Entry(source_id=source_id, name=ch.get("name") or "Unnamed channel", url=url,
                      user_agent=headers.get("user-agent"), referrer=headers.get("referer") or headers.get("referrer"),
                      tvg_id="", tvg_logo=ch.get("logo") or "", tvg_country=region.upper(),
                      group=ch.get("group") or "")
            e.attrs = {"tvg-chno": str(ch.get("chno", ""))}
            out.append(e)
    return out


def load_json(data: bytes):
    return json.loads(decode_bytes(data))


def iter_nonempty(xs: Iterable) -> Iterable:
    return (x for x in xs if x)
