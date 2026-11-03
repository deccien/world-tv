import pytest

from src.normalize import clean_title, normalize_name, normalize_url
from src.parse import (HLSPlaylistError, NotAPlaylistError, decode_bytes, parse_extinf, parse_m3u,
                       parse_mjh_channels, parse_famelack)

BASIC = (
    '#EXTM3U x-tvg-url="https://epg.example/guide.xml"\n'
    '#EXTINF:-1 tvg-id="Kan11.il@SD" tvg-logo="https://x/l.png" group-title="Israel",Kan 11 (1080p)\n'
    'https://kan.example/live/index.m3u8\n'
)


def test_basic_parse():
    es = parse_m3u(BASIC, "t")
    assert len(es) == 1
    e = es[0]
    assert e.name == "Kan 11 (1080p)"
    assert e.tvg_id == "Kan11.il@SD"
    assert e.group == "Israel"
    assert e.tvg_logo == "https://x/l.png"
    assert e.url == "https://kan.example/live/index.m3u8"


def test_crlf_and_bom_bytes():
    data = ("\ufeff" + BASIC).replace("\n", "\r\n").encode("utf-8")
    es = parse_m3u(decode_bytes(data), "t")
    assert len(es) == 1 and es[0].url.endswith("index.m3u8") and es[0].group == "Israel"


def test_lone_cr_line_endings():
    es = parse_m3u(BASIC.replace("\n", "\r"), "t")
    assert len(es) == 1


def test_unicode_names_and_legacy_encoding():
    txt = '#EXTM3U\n#EXTINF:-1 group-title="Türkiye",TRT Haber – Ünlü 📺\nhttp://a.example/x.m3u8\n'
    assert parse_m3u(decode_bytes(txt.encode("utf-8")), "t")[0].name == "TRT Haber – Ünlü 📺"
    latin = '#EXTM3U\n#EXTINF:-1 group-title="España",Telemadrid Señal\nhttp://a.example/y.m3u8\n'
    e = parse_m3u(decode_bytes(latin.encode("cp1252")), "t")[0]
    assert e.name == "Telemadrid Señal" and e.group == "España"


def test_utf16_bom():
    data = BASIC.encode("utf-16")
    assert parse_m3u(decode_bytes(data), "t")[0].tvg_id == "Kan11.il@SD"


def test_extvlcopt_preserved_and_comma_in_ua():
    txt = ('#EXTM3U\n'
           '#EXTINF:-1 tvg-id="A.us" http-user-agent="Mozilla/5.0 (X11, Linux) Gecko, like" group-title="News",Name, with comma\n'
           '#EXTVLCOPT:http-referrer=https://ref.example/\n'
           '#EXTVLCOPT:http-user-agent=Custom/1.0 (a, b)\n'
           'https://s.example/a.m3u8\n')
    e = parse_m3u(txt, "t")[0]
    assert e.referrer == "https://ref.example/"
    assert e.user_agent == "Custom/1.0 (a, b)"
    assert e.name == "Name, with comma"
    assert e.group == "News"


def test_missing_attributes_and_extgrp():
    txt = '#EXTM3U\n#EXTINF:-1,Plain\n#EXTGRP:Chile\nhttp://p.example/1\n#EXTINF:0\nhttp://p.example/2\n'
    es = parse_m3u(txt, "t")
    assert es[0].name == "Plain" and es[0].group == "Chile" and es[0].tvg_id == ""
    assert es[1].name == "Unnamed channel"


def test_pipe_headers():
    txt = '#EXTM3U\n#EXTINF:-1,X\nhttps://h.example/a.m3u8|User-Agent=UA1&Referer=https://r/\n'
    e = parse_m3u(txt, "t")[0]
    assert e.url == "https://h.example/a.m3u8" and e.user_agent == "UA1" and e.referrer == "https://r/"


def test_hls_media_playlist_rejected():
    hls = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:6.0,\nseg1.ts\n"
    with pytest.raises(HLSPlaylistError):
        parse_m3u(hls, "t")
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow.m3u8\n"
    with pytest.raises(HLSPlaylistError):
        parse_m3u(master, "t")


def test_not_a_playlist():
    with pytest.raises(NotAPlaylistError):
        parse_m3u("<html>hello</html>", "t")


def test_drm_marked():
    txt = ('#EXTM3U\n#EXTINF:-1,D\n#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha\n'
           'https://d.example/m.mpd\n')
    assert parse_m3u(txt, "t")[0].blocked_reason == "drm"


def test_parse_extinf_duration():
    d, a, t = parse_extinf('#EXTINF:-1 tvg-id="x",Title')
    assert d == "-1" and a["tvg-id"] == "x" and t == "Title"


def test_normalize_url_conservative():
    assert normalize_url("HTTP://Example.COM:80/Path/A.m3u8?Token=AbC#frag") == "http://example.com/Path/A.m3u8?Token=AbC"
    assert normalize_url("https://EX.com:443/x") == "https://ex.com/x"
    assert normalize_url("https://ex.com:8443/x") == "https://ex.com:8443/x"
    assert normalize_url("http://ex.com/x?b=2&a=1") == "http://ex.com/x?b=2&a=1"  # query order kept


def test_titles_and_names():
    assert clean_title("Kan 11 (1080p) [Not 24/7]") == "Kan 11"
    assert clean_title("TVC News Ⓨ") == "TVC News"
    assert normalize_name("BBC News HD") == normalize_name("bbc news")
    assert normalize_name("Télé Liban") == normalize_name("Tele Liban")
    assert normalize_name("WABC East") != normalize_name("WABC West")


def test_mjh_adapter():
    doc = {"slug": "stvp-{id}", "headers": {"user-agent": "okhttp/4"},
           "regions": {"gb": {"channels": {"GB1": {"name": "One", "logo": "https://l", "group": "News"}}}}}
    e = parse_mjh_channels(doc, "s", "https://jmp2.uk/{slug}")[0]
    assert e.url == "https://jmp2.uk/stvp-GB1" and e.tvg_country == "GB" and e.user_agent == "okhttp/4"
    with pytest.raises(ValueError):
        parse_mjh_channels({"headers": {"X-Plex-Token": "t"}, "regions": {}}, "p", "{id}")


def test_famelack_adapter_skips_youtube_only():
    doc = [{"name": "A", "sources": {"streams": ["https://a/x.m3u8"]}, "country": "cl", "isGeoBlocked": True},
           {"name": "Y", "sources": {"youtube": ["abc"]}, "country": "us"}]
    es = parse_famelack(doc, "f")
    assert len(es) == 1 and es[0].tvg_country == "cl" and "Geo-blocked" in es[0].labels
