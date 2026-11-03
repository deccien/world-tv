# Sources

Research and first local build: **2026-11-03** (UTC). Every row below was verified with a real
fetch that day. Live per-build numbers are in `report.json` / `report.md` on the site; the
registry the build reads is `config/sources.yaml`.

“Parsed” = entries read from the source. “Unique URLs kept” = URLs this source contributed that
no higher-priority source already had, after exclusions (sources are processed in priority order).

## Enabled

| # | Source | Feed URL | Type | Streams | Countries (kept) | Parsed | Unique URLs kept | Licence | Restrictions / notes |
|---|---|---|---|---|---|---:|---:|---|---|
| 10 | IPTV-org (API) | `https://iptv-org.github.io/api/streams.json` + `channels.json`, `feeds.json`, `logos.json`, `blocklist.json`, `categories.json`, `countries.json` | iptvorg_api | redistributed index of public streams | 180 | 16,357 | 16,234 | Unlicense | Authoritative country/category/NSFW metadata + blocklist (836 entries: NSFW + legal takedowns). 2,100 stream rows have no known channel (1,944 `channel: null` + 156 unknown ids) and are skipped by default (no country/NSFW data). |
| 20 | Doubo Public Channel Directory | `https://cdn.jsdelivr.net/gh/streamline-iptv/iptv-playlists@dist/index.m3u` (mirror: `raw.githubusercontent.com/streamline-iptv/iptv-playlists/dist/index.m3u`) | m3u | redistributed (iptv-org + Free-TV + own discovery; daily playback check; host allowlist) | 44 | 4,933 | 1,814 | CC BY 4.0 (playlists), MIT (code) | Doubo itself is a player app; its machine-readable feeds are this GitHub repo (also per-country/category/language M3U and `index.json`). Geo-blocked streams kept. |
| 30 | Free-TV/IPTV | `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8` | m3u | redistributed links to FTA / free-internet channels | 71 | 2,065 | 798 | none declared | Last updated 2026-11-02 (GitHub Actions). `VOD …` groups excluded (181); 134 YouTube page links dropped (not playable streams). Ⓖ = geo-blocked. |
| 40 | Famelack data (TV Garden successor) | `https://raw.githubusercontent.com/famelack/famelack-data/main/tv/raw/categories/all.json` | json_custom (famelack) | redistributed (mostly iptv-org derived) | 58 | 7,445 | 888 | MIT | YouTube-only entries skipped. No NSFW flag → IPTV-org blocked/NSFW URL set + denylist applied. |
| 50 | Samsung TV Plus via i.mjh.nz | `https://i.mjh.nz/SamsungTVPlus/.channels.json` → `https://jmp2.uk/stvp-{id}` | json_custom (mjh_channels) | original FAST streams (redirect to samsungtv.plus) | 11 (AT CA CH DE ES FR GB IN IT KR US) | 2,656 | 2,646 | none declared (free, ad-supported) | Region-locked. Sent with `okhttp` user agent (EXTVLCOPT) as the JSON specifies. |
| 60 | Pluto TV via i.mjh.nz | `https://i.mjh.nz/PlutoTV/.channels.json` → `https://jmp2.uk/plu-{id}.m3u8` | json_custom (mjh_channels) | original FAST streams (redirect to pluto.tv; same scheme IPTV-org uses) | 13 | 3,039 | 1,124 | none declared (free, ad-supported) | Region-locked. Same channel id in several regions = same URL → kept once (first region). |
| 70 | i.mjh.nz New Zealand | `https://i.mjh.nz/nz/raw-tv.m3u8` | m3u | original NZ free-to-air via i.mjh.nz redirects | 3 | 38 | 36 | none declared | Mostly NZ-only. |
| 80 | freecasthub/public-iptv | `https://raw.githubusercontent.com/freecasthub/public-iptv/main/playlist.m3u` | m3u | redistributed official public broadcasters | 13 | 108 | 19 | none declared | Low activity (last push 2026-01-12). No country tags → IPTV-org name match or International. |

## Evaluated, not enabled

| Source | Finding | Why not |
|---|---|---|
| IPTV-org `index.country.m3u` / `countries/{cc}.m3u` | Active (12,961 entries; e.g. `countries/il.m3u` 34) | Same data as the API path; channels repeat per broadcast country. One IPTV-org path only. |
| IPTV-org `index.m3u` | Active (11,389 URLs) | Subset of `streams.json` (about one stream per feed), so it loses alternatives. |
| TVGarden/tv-garden-channel-list | Archived, read-only since 2026-01; now just LICENSE + README | Moved to famelack/famelack-data (enabled). |
| i.mjh.nz `SamsungTVPlus/all.m3u8`, `PlutoTV/all.m3u8`, `Plex/all.m3u8`, `Roku/all.m3u8` | All return **404**; directories now only list EPG XML (plus hidden `.channels.json`) | Replaced by the `.channels.json` adapters above. |
| Plex (i.mjh.nz `.channels.json`) | Regions list 0 channels; headers include an `X-Plex-Token` | Token-authenticated; nothing usable. |
| Roku (i.mjh.nz `.channels.json`) | 258 channels, no stream URL scheme in the JSON | No machine-usable stream URL. |
| iptv-restream/iptv-channels | GitHub API: 403 “Repository access blocked”; last update 2023-02 | Inaccessible/inactive. |
| dearbulut/iptv (“IPTV Nexus”) | Active; self-described as built on iptv-org plus “your sources”; vendor of IPTV reseller panels | Derivative, mixed provenance, no original streams. |
| Göktürk IPTV (gokturkiptv.com) | A player app; its channel directory links the iptv-org playlists | No own feed. |
| apsattv.com FAST lists | Some reachable (e.g. `ssungusa.m3u`), others 404 | Not evaluated further; overlaps Samsung/Roku data above. Can be added as `type: m3u`. |

## Adding a source

Append an entry to `config/sources.yaml` (on github.com: open the file → pencil icon → edit → *Commit changes*):

```yaml
  - id: mysource            # unique, letters/digits/underscore
    name: My public list
    type: m3u               # m3u | json_custom | iptvorg_api
    enabled: true
    priority: 90            # lower runs first and wins duplicate URLs
    url: https://example.org/playlist.m3u
    country_hints:
      groups_are_countries: true        # if group-title holds country names
      group_map: {"Weather": null}      # explicit group -> ISO code (null = International)
      default_country: null             # or e.g. FJ for a single-country list
      exclude_groups_regex: '^VOD'
```

Only add lists of streams that are free and public (FTA, FAST, broadcaster-provided). Never add
personal subscription/Xtream links: URLs with `username=`/`password=` are dropped by the build anyway.
