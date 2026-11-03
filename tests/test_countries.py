from src.classify import Classifier, CountryNames
from src.models import Entry
from src.normalize import normalize_url


def mk(**kw):
    e = Entry(source_id=kw.pop("source_id", "s"), name=kw.pop("name", "X"), url=kw.pop("url", "https://x/1.m3u8"), **kw)
    e.norm_url = normalize_url(e.url)
    return e


def test_names(countries_cfg):
    n = CountryNames(countries_cfg)
    assert n.name("CI") == "Côte d’Ivoire"
    assert n.name("TR") == "Türkiye"
    assert n.name("PS") == "Palestine"
    assert n.name("GB") == "United Kingdom"
    assert n.name("NG") == "Nigeria"


def test_codes(countries_cfg):
    n = CountryNames(countries_cfg)
    assert n.code("us-ca") == "US"          # subdivision -> country
    assert n.code("UK") == "GB"
    assert n.code("US;CA") == "US"
    assert n.code("INT") == ""
    assert n.code("zz") == ""
    assert n.code("XK") == "XK"
    assert n.from_label("USA") == "US"
    assert n.from_label("Israel") == "IL"
    assert n.from_label("Côte d’Ivoire") == "CI"
    assert n.from_label("日本 / Japan") == "JP"
    assert n.from_label("Business") == ""


def run(clf, e, hints=None):
    clf.link(e)
    clf.hint_categories(e)
    clf.classify_country(e, hints or {})
    clf.link_by_name_in_country(e)
    return e


def test_precedence_iptvorg_over_tvg_country(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    e = run(clf, mk(name="Kan 11", tvg_id="Kan11.il@SD", tvg_country="US", group="USA"),
            {"groups_are_countries": True})
    assert e.country == "IL" and e.country_method == "iptvorg_channel"
    assert e.channel_key == "Kan11.il"


def test_precedence_tvg_country_over_group(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    e = run(clf, mk(name="Random", tvg_country="cl", group="Argentina"), {"groups_are_countries": True})
    assert e.country == "CL" and e.country_method == "tvg-country"


def test_group_mapping_then_manual_then_international(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    assert run(clf, mk(name="Foo", group="Lebanon"), {"groups_are_countries": True}).country == "LB"
    assert run(clf, mk(name="Foo", group="Nz"), {"group_map": {"Nz": "NZ"}}).country == "NZ"
    e = run(clf, mk(name="TVNZ 1", group="News"), {"group_map": {"News": None}})
    assert e.country == "NZ" and e.country_method == "manual_map"
    e = run(clf, mk(name="Unknown Channel", group="Music"), {})
    assert e.country == "" and e.country_method == "international"


def test_never_by_language(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    e = run(clf, mk(name="Some Arabic Channel", languages=["ara"]), {})
    assert e.country == ""


def test_name_match_feed(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    e = run(clf, mk(name="Al Jazeera English", group="News"), {})
    assert e.country == "QA" and e.channel_key == "AlJazeera.qa@English"


def test_exclusions(settings, countries_cfg, iptv):
    clf = Classifier(settings, countries_cfg, iptv)
    assert clf.exclusion(run(clf, mk(tvg_id="Adult1.us")), set()) == "nsfw"
    assert clf.exclusion(run(clf, mk(tvg_id="Takedown.es")), set()) == "iptvorg_blocklist"
    assert clf.exclusion(run(clf, mk(name="Hot XXX channel")), set()) == "denylist"
    assert clf.exclusion(run(clf, mk(url="rtmp://a/b")), set()) == "non_http_url"
    assert clf.exclusion(run(clf, mk(url="http://p.example/live?username=a&password=b")), set()) == "credential_url"
    assert clf.exclusion(run(clf, mk(url="https://www.youtube.com/watch?v=x")), set()) == "web_page_not_stream"
    blocked = {normalize_url("https://bad.example/x.m3u8")}
    assert clf.exclusion(run(clf, mk(url="https://BAD.example/x.m3u8")), blocked) == "iptvorg_blocked_url"
    assert clf.exclusion(run(clf, mk(name="BBC News", tvg_id="BBCNews.uk")), set()) == ""
