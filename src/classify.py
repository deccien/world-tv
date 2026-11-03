"""Country classification, category hints and exclusions.

Country precedence (never by language or server location):
  1. IPTV-org channel country (entry linked to an IPTV-org channel id)
  2. source tvg-country
  3. source country playlist / group-title mapping
  4. countries.yaml manual_map (name regex)
  5. (optional) unique IPTV-org name match within the source's hints -> treated as 1
  6. "International"
"""
from __future__ import annotations

import re
from typing import Optional

import pycountry

from .models import Entry
from .normalize import normalize_name

ISO_CODES = {c.alpha_2 for c in pycountry.countries}


class CountryNames:
    def __init__(self, countries_cfg: dict, iptvorg_countries: Optional[dict] = None):
        self.cfg = countries_cfg or {}
        self.overrides = {k.upper(): v for k, v in (self.cfg.get("names") or {}).items()}
        self.aliases = {k.upper(): v.upper() for k, v in (self.cfg.get("code_aliases") or {}).items()}
        self.non_country = {c.upper() for c in (self.cfg.get("non_country_codes") or [])}
        self.valid = set(ISO_CODES) | {"XK"}
        # group label -> code
        self.by_label: dict = {}
        for c in pycountry.countries:
            for nm in (c.name, getattr(c, "common_name", None), getattr(c, "official_name", None)):
                if nm:
                    self.by_label[nm.casefold()] = c.alpha_2
        for code, c in (iptvorg_countries or {}).items():
            cc = self.aliases.get(code.upper(), code.upper())
            if c.get("name"):
                self.by_label[c["name"].casefold()] = cc
        for code, nm in self.overrides.items():
            self.by_label[nm.casefold()] = code
        for label, code in (self.cfg.get("group_aliases") or {}).items():
            self.by_label[str(label).casefold()] = str(code).upper()

    def code(self, raw: str) -> str:
        """Normalize a code like 'us', 'UK', 'us-ca', 'US;CA' -> 'US' / 'GB' ('' if not a country)."""
        if not raw:
            return ""
        first = re.split(r"[;,|\s]+", raw.strip())[0].upper()
        if not first:
            return ""
        if first.startswith("C/"):          # IPTV-org broadcast_area style
            first = first[2:]
        if "-" in first:                       # ISO 3166-2 subdivision -> its country
            first = first.split("-", 1)[0]
        first = self.aliases.get(first, first)
        if first in self.non_country:
            return ""
        return first if first in self.valid else ""

    def from_label(self, label: str) -> str:
        if not label:
            return ""
        lab = label.strip().casefold()
        if lab in self.by_label:
            return self.by_label[lab]
        # labels like "🇮🇱 Israel" or "Israel (IL)"
        lab2 = re.sub(r"[^\w\s'’.-]", "", lab, flags=re.UNICODE).strip()
        lab2 = re.sub(r"\s*\(.*\)$", "", lab2).strip()
        return self.by_label.get(lab2, "")

    def name(self, code: str) -> str:
        if not code:
            return ""
        if code in self.overrides:
            return self.overrides[code]
        c = pycountry.countries.get(alpha_2=code)
        if not c:
            return code
        return getattr(c, "common_name", None) or c.name


class Classifier:
    def __init__(self, settings: dict, countries_cfg: dict, iptv=None):
        self.settings = settings
        self.iptv = iptv
        self.names = CountryNames(countries_cfg, iptv.countries if iptv else None)
        self.manual = [(re.compile(r["pattern"], re.I), r["country"].upper())
                       for r in (countries_cfg.get("manual_map") or [])]
        self.deny = [re.compile(p, re.I) for p in settings.get("denylist_regex") or []]
        self.url_deny = [re.compile(p, re.I) for p in settings.get("url_denylist_regex") or []]
        self.page_urls = [re.compile(p, re.I) for p in settings.get("page_url_regex") or []]
        self.schemes = set(settings.get("allowed_schemes") or ["http", "https"])
        self.group_hints = [(k.casefold(), v) for k, v in (settings.get("group_category_hints") or {}).items()]
        self.name_match = bool(settings.get("name_match_iptvorg", True))
        self._name_index = None

    # ---- IPTV-org name index: (country, normname) -> channel id, only unique names
    def _build_name_index(self):
        """(country, normalized name) -> (channel id, channel key); unique names only.

        Includes regional/language feed names ("Al Jazeera English" -> AlJazeera.qa@English).
        """
        idx: dict = {}
        if not self.iptv:
            self._name_index = {}
            return

        def add(cc, nm, val):
            k = normalize_name(nm)
            if k:
                idx.setdefault((cc, k), set()).add(val)
                idx.setdefault(("*", k), set()).add(val)

        usable = {}
        for cid, c in self.iptv.channels.items():
            if c.get("closed") or cid in self.iptv.nsfw or cid in self.iptv.blocked:
                continue
            cc = self.names.code(c.get("country", ""))
            usable[cid] = cc
            for nm in [c.get("name", "")] + list(c.get("alt_names") or []):
                add(cc, nm, (cid, cid))
        for (cid, fid), f in self.iptv.feeds.items():
            if cid not in usable:
                continue
            cf = self.iptv.canonical_feed(cid, fid)
            if cf:
                add(usable[cid], self.iptv.display_name(cid, cf), (cid, f"{cid}@{cf}"))
        self._name_index = {k: next(iter(v)) for k, v in idx.items() if len(v) == 1}

    def match_name(self, name: str, country: str = "") -> tuple:
        if self._name_index is None:
            self._build_name_index()
        k = normalize_name(name)
        return self._name_index.get((country or "*", k), ("", ""))

    # ---- link non-IPTV-org entries to IPTV-org channels
    def link(self, e: Entry) -> None:
        if not self.iptv or e.channel_key:
            return
        if e.tvg_id:
            cid, key = self.iptv.key_for(e.tvg_id)
            if cid:
                self._apply_iptv(e, cid, key)

    def _apply_iptv(self, e: Entry, cid: str, key: str) -> None:
        ch = self.iptv.channels[cid]
        e.channel_key = key
        e.attrs = dict(e.attrs)
        e.attrs["iptvorg_channel"] = cid
        if not e.categories:
            e.categories = list(ch.get("categories") or [])
        if cid in self.iptv.nsfw:
            e.nsfw = True
        if cid in self.iptv.blocked:
            e.blocked_reason = e.blocked_reason or f"iptvorg_blocklist:{self.iptv.blocked[cid]}"
        if ch.get("closed"):
            e.attrs["closed"] = ch["closed"]
        if not e.tvg_logo:
            feed = key.partition("@")[2] or None
            e.tvg_logo = self.iptv.logo_for(cid, feed)

    # ---- country
    def classify_country(self, e: Entry, hints: dict | None = None) -> None:
        hints = hints or {}
        cid = (e.attrs or {}).get("iptvorg_channel")
        if cid and self.iptv:
            cc = self.names.code(self.iptv.channels[cid].get("country", ""))
            if cc:
                e.country, e.country_method = cc, "iptvorg_channel"
                return
        cc = self.names.code(e.tvg_country)
        if cc:
            e.country, e.country_method = cc, "tvg-country"
            return
        gmap = hints.get("group_map") or {}
        if e.group in gmap:
            v = gmap[e.group]
            if v:
                cc = self.names.code(str(v))
                if cc:
                    e.country, e.country_method = cc, "group_map"
                    return
        elif hints.get("groups_are_countries") and e.group:
            cc = self.names.from_label(e.group)
            if cc:
                e.country, e.country_method = cc, "group_label"
                return
        if hints.get("default_country"):
            cc = self.names.code(hints["default_country"])
            if cc:
                e.country, e.country_method = cc, "source_default"
                return
        for rx, code in self.manual:
            if rx.search(e.name or ""):
                e.country, e.country_method = self.names.code(code), "manual_map"
                return
        if self.name_match and self.iptv:
            mcid, mkey = self.match_name(e.name)
            if mcid:
                self._apply_iptv(e, mcid, mkey)
                cc = self.names.code(self.iptv.channels[mcid].get("country", ""))
                if cc:
                    e.country, e.country_method = cc, "iptvorg_name_match"
                    return
        e.country, e.country_method = "", "international"

    def link_by_name_in_country(self, e: Entry) -> None:
        """After country is known, attach an IPTV-org id when the name is unique in that country."""
        if not self.iptv or e.channel_key or not e.country or not self.name_match:
            return
        mcid, mkey = self.match_name(e.name, e.country)
        if mcid:
            self._apply_iptv(e, mcid, mkey)

    # ---- categories
    def hint_categories(self, e: Entry) -> None:
        if e.categories:
            return
        g = (e.group or "").casefold()
        cats = []
        for kw, cat in self.group_hints:
            if kw in g and cat not in cats:
                cats.append(cat)
        e.categories = cats

    # ---- exclusions; returns reason or ""
    def exclusion(self, e: Entry, blocked_urls: set) -> str:
        if e.blocked_reason:
            return e.blocked_reason.split(":")[0]
        if e.nsfw:
            return "nsfw"
        if "xxx" in (e.categories or []):
            return "nsfw"
        scheme = e.url.split(":", 1)[0].lower() if ":" in e.url else ""
        if scheme not in self.schemes:
            return "non_http_url"
        if (e.attrs or {}).get("closed") and self.settings.get("exclude_closed_channels", True):
            return "closed_channel"
        if e.norm_url in blocked_urls:
            return "iptvorg_blocked_url"
        text = f"{e.name} \u241f {e.group}"
        if any(rx.search(text) for rx in self.deny):
            return "denylist"
        if any(rx.search(e.url) for rx in self.url_deny):
            return "credential_url"
        if any(rx.search(e.url) for rx in self.page_urls):
            return "web_page_not_stream"
        return ""
