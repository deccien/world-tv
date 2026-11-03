"""Download sources with timeouts, bounded retries, limited concurrency and a last-good cache."""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("worldtv.fetch")


@dataclass
class FetchResult:
    key: str
    url: str
    status: str                 # "fresh" | "cache" | "failed"
    content: Optional[bytes] = None
    error: str = ""
    fetched_at: str = ""        # when the content was downloaded (UTC ISO)


def safe_url(url: str) -> str:
    """URL for logs: no query string, no userinfo."""
    url = re.sub(r"//[^/@]*@", "//", url)
    return url.split("?", 1)[0]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cache_paths(cache_dir: Path, key: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return cache_dir / f"{safe}.bin.gz", cache_dir / f"{safe}.json"


def save_cache(cache_dir: Path, key: str, url: str, content: bytes, fetched_at: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_p, meta_p = _cache_paths(cache_dir, key)
    tmp = data_p.with_suffix(".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(content)
    tmp.replace(data_p)
    meta_p.write_text(json.dumps({
        "url": safe_url(url), "fetched_at": fetched_at, "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }, indent=1), encoding="utf-8")


def load_cache(cache_dir: Path, key: str):
    data_p, meta_p = _cache_paths(cache_dir, key)
    if not data_p.exists():
        return None, ""
    try:
        with gzip.open(data_p, "rb") as fh:
            content = fh.read()
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        return content, meta.get("fetched_at", "")
    except (OSError, ValueError) as exc:
        log.warning("cache for %s unreadable: %s", key, exc)
        return None, ""


def download(client: httpx.Client, url: str, retries: int, backoff: float, max_bytes: int) -> bytes:
    last: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code in (429,) or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                if resp.status_code >= 400:
                    # 4xx (except 429) will not fix itself on retry
                    raise PermanentError(f"HTTP {resp.status_code}")
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise PermanentError(f"response exceeds {max_bytes} bytes")
                if not buf:
                    raise httpx.HTTPError("empty response")
                return bytes(buf)
        except PermanentError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(backoff * (2 ** (attempt - 1)))
    raise last or RuntimeError("download failed")


class PermanentError(Exception):
    pass


def fetch_all(jobs: list, settings: dict, cache_dir: Path) -> dict:
    """jobs: list of (key, url). Returns {key: FetchResult}."""
    f = settings.get("fetch", {})
    timeout = float(f.get("timeout_seconds", 60))
    retries = int(f.get("retries", 3))
    backoff = float(f.get("backoff_seconds", 2))
    conc = max(1, int(f.get("concurrency", 4)))
    max_bytes = int(f.get("max_bytes", 80_000_000))
    headers = {"User-Agent": settings.get("user_agent", "WorldTV-Builder/1.0"), "Accept-Encoding": "gzip, deflate"}

    def one(job):
        key, url = job
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 20)), headers=headers,
                              follow_redirects=True, http2=False) as client:
                content = download(client, url, retries, backoff, max_bytes)
            ts = _now()
            save_cache(cache_dir, key, url, content, ts)
            log.info("fetched %s (%d bytes)", safe_url(url), len(content))
            return FetchResult(key, url, "fresh", content, "", ts)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to cache
            err = f"{type(exc).__name__}: {exc}"
            content, ts = load_cache(cache_dir, key)
            if content is not None:
                log.warning("fetch failed for %s (%s); using cached copy from %s", safe_url(url), err, ts)
                return FetchResult(key, url, "cache", content, err, ts)
            log.error("fetch failed for %s (%s); no cache", safe_url(url), err)
            return FetchResult(key, url, "failed", None, err, "")

    with ThreadPoolExecutor(max_workers=conc) as pool:
        results = list(pool.map(one, jobs))
    return {r.key: r for r in results}


def fetch_json(url: str, settings: dict, timeout: float = 30):
    """Small helper for the previously published report.json. Returns None on any failure."""
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": settings.get("user_agent", "WorldTV-Builder/1.0")},
                          follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            return r.json()
    except (httpx.HTTPError, ValueError):
        return None
