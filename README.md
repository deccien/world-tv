# World TV

Daily-built worldwide M3U playlists of **free, public** TV streams (free-to-air, broadcaster
streams, FAST services), grouped by country, published on GitHub Pages. Nothing is hosted or
proxied: the playlists only contain links.

**Site:** https://deccien.github.io/world-tv/

| Playlist | URL | What |
|---|---|---|
| Master | https://deccien.github.io/world-tv/world.m3u | every country, every alternative stream (max 8 per channel), Favorites groups on top |
| Lite | https://deccien.github.io/world-tv/world-lite.m3u | every country, up to 25 channels each (news/general and channels with logos first), 1–2 streams each |
| Favorites | https://deccien.github.io/world-tv/favorites.m3u | Israel, world news, US, UK, Arabic, Latin America, Africa, Pacific islands, documentary, music |
| News / Entertainment / Music / Documentary / Sports | `…/news.m3u`, `…/entertainment.m3u`, `…/music.m3u`, `…/documentary.m3u`, `…/sports.m3u` | by category, grouped by country |
| Report | https://deccien.github.io/world-tv/report.md (`report.json`) | totals, countries, per-source stats, exclusions |

The landing page builds its copy buttons from its own address, so it works on any fork. The
username lives in exactly one place: `github_user` in `config/settings.yaml` (used for the
User-Agent and the safeguard's Pages URL fallback; in Actions the URL comes from
`actions/configure-pages`).

Channels with several working links appear as `Name | 1`, `Name | 2`, …; if one fails, try the next.

---

## One-time setup (works from an iPhone browser)

1. On github.com open **deccien/world-tv** → **Settings** → **Pages** → *Build and deployment* →
   **Source: GitHub Actions**.
2. **Actions** tab → if asked, tap **I understand my workflows, go ahead and enable them**.
3. **Actions** → **Update World TV** → **Run workflow** → **Run workflow**. Wait ~2–4 minutes for
   *build* and *deploy* to go green.
4. Open https://deccien.github.io/world-tv/ and copy a playlist URL.

### OTTplayer on iPhone

1. Install **OttPlayertv** from the App Store, sign in (create the account at ottplayer.tv), and add the
   iPhone as a device when the app asks.
2. In Safari: **ottplayer.tv** → profile menu → **Playlists** → **Add playlist** → name it, choose
   the **link/URL** source, paste e.g. the Lite URL.
3. Under **Devices** select your iPhone and save (later: gear icon next to the playlist → Devices).
4. In the app, refresh the playlist list and open it. Keep auto-update on so the daily rebuild arrives.

On a phone, start with **Lite** or **Favorites**; the master list is large (~23k entries, ~9–10 MB).

---

## Maintenance from github.com (iPhone friendly)

- **Rebuild now:** Actions → *Update World TV* → Run workflow.
- **Add a source:** open `config/sources.yaml` → pencil (Edit) → copy an existing block, change
  `id`, `name`, `url`, `priority`, `type` (`m3u` for playlists) → **Commit changes**. Then run the
  workflow. See `docs/SOURCES.md` for the fields. Only free/public lists; personal subscription
  links (`username=`/`password=`) are dropped automatically and must never be committed.
- **Disable a source:** set `enabled: false` in its block.
- **Edit favorites:** `config/favorites.yaml`. Each rule has a `name` (becomes the group
  `Favorites: <name>`), optional `ids` (regexes on IPTV-org ids such as `^Kan11\.il$`, look them up at
  https://iptv-org.github.io/), and/or filters `countries`, `categories`, `languages`, plus `limit`.
  Switch `group_mode: single` for one flat `★ Favorites` group.
- **Tune size:** `config/settings.yaml` → `max_alternatives` (default 8), `lite.per_country` (25),
  `favorites_on_top_of_world` (true).
- **Country names / mappings:** `config/countries.yaml` (`names`, `group_aliases`, `manual_map`).

### How a build works

1. **Fetch** every enabled source (timeouts, 3 bounded retries, 4 parallel downloads, clear
   User-Agent). Each success is cached in `cache/`; on failure the last good copy is used
   (`actions/cache` carries `cache/` between runs).
2. **Parse** M3U (BOM, CRLF, legacy encodings, missing attributes, commas in user agents,
   `#EXTVLCOPT` referrer/user-agent, `#EXTGRP`, Kodi `|User-Agent=`; HLS media/master playlists are
   rejected) and the JSON adapters.
3. **IPTV-org** is ingested once, via `streams.json` + `channels.json` (+ feeds, logos, blocklist).
4. **Country** precedence: IPTV-org channel country → source `tvg-country` → source group/playlist
   mapping → `countries.yaml` manual map → unique IPTV-org name match → `International`. Never by
   language or server location. `us-ca` → United States, `UK` → United Kingdom.
5. **Exclusions:** IPTV-org blocklist (NSFW + legal takedowns) by id and by URL, `is_nsfw`/`xxx`,
   closed channels, regex denylist, non-http(s), credential-looking URLs, YouTube/web pages, DRM.
6. **Dedup:** URLs normalized conservatively (lowercase scheme/host, drop default port and fragment,
   keep query) and deduplicated exactly; alternatives grouped by IPTV-org id/feed or by
   country + normalized name. Regional feeds (East/West, language feeds) are never merged.
7. **Write** the playlists, validate them (header, http(s) URL + group-title on every entry, UTF-8,
   no credentials in the log, size warnings), write `report.json`/`report.md`.
8. **Safeguard:** if `world.m3u` has >30% fewer entries than the live `report.json`, the build
   fails and the previous deployment stays online. (Skipped on the very first deploy.)

Local run: `pip install -r requirements.txt && pytest -q && python -m src.main`
(`--offline` uses only `cache/`, `--no-safeguard` skips the drop check).

### Schedule caveats

- Runs daily at **03:23 UTC** (`23 3 * * *`). GitHub starts scheduled runs late under load (minutes,
  sometimes longer) and may drop a run during heavy load; the next day's run catches up.
- In public repos GitHub **disables scheduled workflows after 60 days without repository activity**.
  The workflow's `keepalive` job re-enables itself through the API on each scheduled run. If it is
  ever disabled anyway, GitHub emails you; fix it at Actions → *Update World TV* → **Enable workflow**,
  then *Run workflow* (or make any commit).
- OTTplayer refreshes on its own timing; the URL never changes.

## Sources & licences

See [`docs/SOURCES.md`](docs/SOURCES.md). Main data: IPTV-org (Unlicense), Doubo Public Channel
Directory (CC BY 4.0 — “Channel list: Doubo Public Channel Directory,
https://github.com/streamline-iptv/iptv-playlists, CC BY 4.0”), Free-TV/IPTV, Famelack (MIT),
Samsung TV Plus and Pluto TV channel data via i.mjh.nz. Availability, geo-blocking and rights vary
by country; streams belong to their broadcasters.
