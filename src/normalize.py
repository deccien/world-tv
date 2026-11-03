"""Conservative URL and name normalization."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str) -> str:
    """Lowercase scheme and host, drop default port and fragment, keep path and query as-is."""
    url = (url or "").strip()
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    if not scheme or not host:
        return url
    try:
        port = p.port
    except ValueError:
        port = None
    userinfo = ""
    if "@" in p.netloc:
        userinfo = p.netloc.rsplit("@", 1)[0] + "@"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6 literal
    netloc = userinfo + host
    if port is not None and DEFAULT_PORTS.get(scheme) != port:
        netloc += f":{port}"
    path = p.path or ""
    return urlunsplit((scheme, netloc, path, p.query, ""))


_BRACKET_RE = re.compile(r"\s*[\[(][^\])]*[\])]")
_QUALITY_RE = re.compile(r"\b(\d{3,4}[pi]|fhd|uhd|hd|sd|4k|8k|hevc|h\.?265|h\.?264)\b", re.I)
_GEO_MARK_RE = re.compile(r"[\u24b6-\u24e9]")  # circled letters Ⓖ Ⓨ Ⓢ used by Free-TV as flags


def clean_title(name: str) -> str:
    """Display title: drop '(1080p)', '[Not 24/7]', '[Geo-blocked]', Free-TV Ⓖ marks, extra spaces."""
    n = unicodedata.normalize("NFC", name or "")
    n = _GEO_MARK_RE.sub("", n)
    n = re.sub(r"\s*\((\d{3,4}[pi])\)", "", n)
    n = re.sub(r"\s*\[(not 24/7|geo-blocked|geo blocked|offline|vod)\]", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -|")
    return n or (name or "").strip() or "Unnamed channel"


def normalize_name(name: str) -> str:
    """Matching key for a channel name (accents/case/quality tags removed)."""
    n = clean_title(name)
    n = _BRACKET_RE.sub(" ", n)
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.casefold().replace("&", " and ").replace("+", " plus ")
    n = _QUALITY_RE.sub(" ", n)
    n = re.sub(r"[^\w]+", " ", n, flags=re.UNICODE)
    n = re.sub(r"\btv\b", " tv ", n)
    return re.sub(r"\s+", " ", n).strip()


def sanitize_attr(value: str) -> str:
    return (value or "").replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def sanitize_title(value: str) -> str:
    return (value or "").replace("\r", " ").replace("\n", " ").strip()
