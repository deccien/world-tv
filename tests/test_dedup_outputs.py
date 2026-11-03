import pytest

from src.classify import Classifier
from src.deduplicate import dedup_urls, group_channels
from src.generate import build_outputs, select_favorites
from src.models import Entry
from src.normalize import normalize_url
from src.parse import parse_iptvorg_streams
from src.report import (SafeguardError, ValidationError, check_drop, validate_outputs, validate_playlist)


def mk(src, name, url, **kw):
    e = Entry(source_id=src, name=name, url=url, **kw)
    e.norm_url = normalize_url(url)
    return e


def classify_all(clf, es):
    for e in es:
        clf.link(e)
        clf.hint_categories(e)
        clf.classify_country(e, {"groups_are_countries": True})
        clf.link_by_name_in_country(e)
    return es


def test_exact_url_dedup_keeps_first():
    es = [mk("a", "X", "HTTP://Host.com:80/a.m3u8#f"), mk("b", "X", "http://host.com/a.m3u8"),
          mk("b", "X", "http://host.com/a.m3u8?q=1")]
    kept, dups = dedup_urls(es)
    assert [e.source_id for e in kept] == ["a", "b"] and dups == {"b": 1}


def test_feed_keys_never_merge_regional(iptv):
    streams = [
        {"channel": "WABC.us", "feed": "East", "url": "https://w/e1"},
        {"channel": "WABC.us", "feed": "West", "url": "https://w/w1"},
        {"channel": "AlJazeera.qa", "feed": "EnglishHD", "url": "https://aj/ehd"},
        {"channel": "AlJazeera.qa", "feed": "English", "url": "https://aj/e"},
        {"channel": "AlJazeera.qa", "feed": "Arabic", "url": "https://aj/a"},
        {"channel": None, "feed": None, "url": "https://nochannel/x", "title": "Orphan"},
    ]
    es, st = parse_iptvorg_streams(streams, iptv, "iptvorg", include_unlinked=False)
    assert st["unlinked_streams"] == 1
    keys = sorted({e.channel_key for e in es})
    assert keys == ["AlJazeera.qa", "AlJazeera.qa@English", "WABC.us", "WABC.us@West"]
    names = {e.channel_key: e.name for e in es}
    assert names["AlJazeera.qa@English"] == "Al Jazeera English"
    assert names["WABC.us@West"] == "WABC West"


def _channels(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    es = [
        mk("iptvorg", "Kan 11", "https://kan/1.m3u8", tvg_id="Kan11.il@SD"),
        mk("other", "Kan 11 HD", "https://kan/2.m3u8", group="Israel"),          # joins by name in IL
        mk("other", "Channels TV", "https://ng/1.m3u8", group="Nigeria"),
        mk("other", "BBC News", "https://bbc/1.m3u8", tvg_id="BBCNews.uk", referrer="https://bbc.co.uk/",
           user_agent="UA (x, y)"),
        mk("other", "Mystery", "https://m/1.m3u8", group="Music"),
    ]
    es += [mk("other", "Channels TV", f"https://ng/alt{i}.m3u8", group="Nigeria") for i in range(12)]
    classify_all(clf, es)
    kept, _ = dedup_urls(es)
    return group_channels(kept, {"iptvorg": 0, "other": 1}, settings["max_alternatives"], clf.names.name)


def test_grouping_naming_and_cap(settings, countries_cfg, iptv):
    chans = _channels(settings, countries_cfg, iptv)
    kan = [c for c in chans if c.tvg_id == "Kan11.il"][0]
    assert len(kan.streams) == 2 and kan.streams[0].source_id == "iptvorg" and kan.logo == "https://x/kan.png"
    ng = [c for c in chans if c.country == "NG"][0]
    assert len(ng.streams) == settings["max_alternatives"] == 8 and ng.dropped_alternatives == 5
    intl = [c for c in chans if c.country == ""]
    assert intl and intl[0].country_name == "International"


def test_outputs_valid(tmp_path, settings, countries_cfg, iptv):
    chans = _channels(settings, countries_cfg, iptv)
    fav = {"group_mode": "per_rule", "group_prefix": "Favorites: ", "streams_per_channel": 2,
           "rules": [{"name": "Israel", "ids": ["^Kan11\\.il$"], "countries": ["IL"], "limit": 5},
                     {"name": "World News", "ids": ["^BBCNews\\.uk$"], "limit": 5}]}
    files = build_outputs(chans, settings, fav, tmp_path)
    files.pop("_favorite_groups")
    validate_outputs(tmp_path, files, settings, [])
    world = (tmp_path / "world.m3u").read_text(encoding="utf-8")
    lines = world.split("\n")
    assert lines[0] == "#EXTM3U"
    groups = [l.split('group-title="')[1].split('"')[0] for l in lines if l.startswith("#EXTINF")]
    assert groups[0].startswith("Favorites: ")            # favorites on top
    country_groups = [g for g in groups if not g.startswith("Favorites")]
    assert country_groups[-1] == "International"           # International last
    assert country_groups == sorted(country_groups, key=lambda g: (g == "International", g.casefold()))
    assert "Kan 11 | 1" in world and "Kan 11 | 2" in world
    assert "#EXTVLCOPT:http-referrer=https://bbc.co.uk/" in world
    assert "#EXTVLCOPT:http-user-agent=UA (x, y)" in world
    assert ",BBC News\n" in world                          # single stream keeps plain name
    lite = (tmp_path / "world-lite.m3u").read_text(encoding="utf-8")
    assert lite.count("Channels TV |") == 2                 # lite: max 2 streams per channel
    for f in files:
        assert validate_playlist(tmp_path / f)["entries"] == files[f]["entries"]


def test_favorites_single_mode(settings, countries_cfg, iptv):
    chans = _channels(settings, countries_cfg, iptv)
    fav = {"group_mode": "single", "single_group_name": "★ Favorites",
           "rules": [{"name": "A", "countries": ["IL"], "limit": 3}, {"name": "B", "countries": ["IL", "NG"], "limit": 3}]}
    res = select_favorites(chans, fav)
    assert len(res) == 1 and res[0][0] == "★ Favorites"
    assert len(res[0][1]) == len({id(c) for c in res[0][1]})  # no duplicates


def test_validation_rejects_bad(tmp_path):
    p = tmp_path / "bad.m3u"
    p.write_text("#EXTM3U\n#EXTINF:-1,No group\nhttp://x/1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_playlist(p)
    p.write_text('#EXTM3U\n#EXTINF:-1 group-title="A",X\nrtmp://x/1\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_playlist(p)
    p.write_text('EXTM3U\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_playlist(p)


def test_log_credential_check(tmp_path, settings):
    p = tmp_path / "world.m3u"
    p.write_text('#EXTM3U\n#EXTINF:-1 group-title="A",X\nhttp://x/1\n', encoding="utf-8")
    files = {"world.m3u": {"entries": 1, "bytes": p.stat().st_size}}
    validate_outputs(tmp_path, files, settings, ["INFO fetched https://x/a.m3u8"])
    with pytest.raises(ValidationError):
        validate_outputs(tmp_path, files, settings, ["ERROR http://x/?password=hunter2"])


def test_safeguard():
    assert "skipped" in check_drop(100, None, 0.3)
    assert "within" in check_drop(75, {"totals": {"world_entries": 100}}, 0.3)
    with pytest.raises(SafeguardError):
        check_drop(69, {"totals": {"world_entries": 100}}, 0.3)
