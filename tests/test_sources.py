import json
from datetime import date

import pytest

from papertracker.sources import arxiv, openalex


def test_query_joins_categories_terms_and_dates():
    q = arxiv.build_query(["cs.GR", "cs.CV"], ["avatar", "digital human"], date(2025, 1, 1), date(2025, 1, 31))
    assert q == '(cat:cs.GR OR cat:cs.CV) AND (all:avatar OR all:"digital human") AND submittedDate:[202501010000 TO 202501312359]'


def test_query_without_terms():
    q = arxiv.build_query(["cs.GR"], [], date(2026, 11, 14), date(2026, 11, 16))
    assert q == "(cat:cs.GR) AND submittedDate:[202611140000 TO 202611162359]"


def test_parse_arxiv_entries(fixture_bytes):
    papers, total = arxiv.parse(fixture_bytes("arxiv_sample.xml"))
    assert total == 2
    first = papers[0]
    assert first.arxiv_id == "2611.04321"
    assert first.title == "Relightable Gaussian Head Avatars from a Single Phone Video"
    assert first.abstract.startswith("We build relightable head avatars")
    assert first.authors == ["Ana Smith", "Bo Li"]
    assert first.published == "2026-11-14"
    assert first.venue == "arXiv cs.CV"
    assert first.pdf_url == "https://export.arxiv.org/pdf/2611.04321"
    assert first.doi == "10.1145/1234567.7654321"
    assert first.key == "arxiv:2611.04321"
    assert papers[1].categories == ["cs.HC"]


def test_arxiv_error_is_raised(fixture_bytes):
    with pytest.raises(arxiv.ArxivError):
        arxiv.parse(fixture_bytes("arxiv_error.xml"))


def test_arxiv_pages_until_total(monkeypatch):
    monkeypatch.setattr(arxiv, "PAGE_SIZE", 1)
    feed = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:totalResults>
      <entry><id>http://arxiv.org/abs/2611.0000{n}v1</id><title>Paper {n}</title><summary>x</summary>
      <published>2026-11-15T00:00:00Z</published></entry></feed>"""
    calls = []

    def getter(url):
        calls.append(url)
        return feed.format(n=len(calls)).encode()

    papers = arxiv.fetch(["cs.GR"], [], date(2026, 11, 14), date(2026, 11, 16), getter=getter, sleep=lambda s: None)
    assert [p.title for p in papers] == ["Paper 1", "Paper 2"]
    assert "start=1" in calls[1]


def test_openalex_abstract_and_parse():
    data = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "openalex_sample.json").read_text())
    assert openalex.abstract_from_index({"world": [1], "hello": [0]}) == "hello world"
    papers = [openalex.parse_work(w) for w in data["results"]]
    pps, editorial, preprint = papers
    assert editorial is None
    assert pps.abstract == "We measured peripersonal space in VR."
    assert pps.venue == "IEEE Transactions on Visualization and Computer Graphics"
    assert pps.doi == "10.1109/tvcg.2026.1111111"
    assert pps.pdf_url == "https://example.org/pps.pdf"
    assert preprint.arxiv_id == "2611.04321"
    assert preprint.key == "arxiv:2611.04321"


def test_openalex_follows_cursor():
    pages = [
        {"meta": {"next_cursor": "abc"}, "results": [{"display_name": "One", "type": "article"}]},
        {"meta": {"next_cursor": None}, "results": [{"display_name": "Two", "type": "article"}]},
    ]
    urls = []

    def getter(url):
        urls.append(url)
        return pages[len(urls) - 1]

    papers = openalex.fetch(date(2026, 11, 1), date(2026, 11, 16), search='"virtual reality"', fields=[17, 32],
                            getter=getter, sleep=lambda s: None)
    assert [p.title for p in papers] == ["One", "Two"]
    assert "cursor=abc" in urls[1]
    assert "title_and_abstract.search" in urls[0]
    assert "primary_topic.field.id%3A17%7C32" in urls[0]


def test_venue_queries_skip_the_field_filter():
    urls = []
    openalex.fetch(date(2026, 11, 1), date(2026, 11, 16), source_ids=["S1", "S2"], fields=[17],
                   getter=lambda url: urls.append(url) or {"results": [], "meta": {}}, sleep=lambda s: None)
    assert "primary_location.source.id%3AS1%7CS2" in urls[0]
    assert "primary_topic" not in urls[0]


def test_resolve_sources_uses_cache():
    calls = []

    def getter(url):
        calls.append(url)
        return {"results": [{"id": "https://openalex.org/S123", "display_name": "IEEE TVCG"}]}

    cache = {"Known": ["S9", "Known venue"]}
    ids = openalex.resolve_sources(["Known", "IEEE TVCG", "S84775595"], cache, getter=getter, sleep=lambda s: None)
    assert ids == ["S9", "S123", "S84775595"]
    assert len(calls) == 1
    assert cache["IEEE TVCG"] == ["S123", "IEEE TVCG"]


def test_used_up_daily_credits_fail_fast(monkeypatch):
    import email.message
    import urllib.error

    from papertracker.sources import http

    headers = email.message.Message()
    headers["x-ratelimit-remaining"] = "0"
    headers["x-ratelimit-reset"] = "7200"
    calls = []

    def urlopen(req, **kw):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", headers, None)

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    with pytest.raises(http.DailyLimit, match="about 2 h"):
        http.get("https://api.openalex.org/works?x=1", sleep=lambda s: None)
    assert len(calls) == 1
