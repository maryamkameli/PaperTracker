"""arXiv API: new submissions in some categories, optionally narrowed by keywords."""
from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

from ..models import Paper, strip_version
from . import http

API = "https://export.arxiv.org/api/query"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}
PAGE_SIZE = 400
MAX_RESULTS = 6000  # per query; a month of cs.CV keywords stays well under this
PAUSE = 3.1  # arXiv asks for at most one request every three seconds

_last_call = 0.0


class ArxivError(RuntimeError):
    pass


def _wait_turn(sleep=time.sleep) -> None:
    global _last_call
    gap = PAUSE - (time.monotonic() - _last_call)
    if gap > 0:
        sleep(gap)
    _last_call = time.monotonic()


def _term(term: str) -> str:
    term = term.replace('"', "").strip()
    return f'all:"{term}"' if " " in term else f"all:{term}"


def build_query(categories: list[str], terms: list[str], start: date, end: date) -> str:
    parts = []
    if categories:
        parts.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
    if terms:
        parts.append("(" + " OR ".join(_term(t) for t in terms) + ")")
    parts.append(f"submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]")
    return " AND ".join(parts)


def _text(entry, path: str) -> str:
    return " ".join((entry.findtext(path, default="", namespaces=NS) or "").split())


def parse(xml_bytes: bytes) -> tuple[list[Paper], int]:
    root = ET.fromstring(xml_bytes)
    total = int(root.findtext("os:totalResults", default="0", namespaces=NS) or 0)
    papers = []
    for entry in root.findall("a:entry", NS):
        raw_id = _text(entry, "a:id")
        if "/api/errors" in raw_id:
            raise ArxivError(_text(entry, "a:summary") or "arXiv rejected the query")
        arxiv_id = strip_version(raw_id.rsplit("/abs/", 1)[-1])
        primary = entry.find("arxiv:primary_category", NS)
        primary = primary.get("term", "") if primary is not None else ""
        papers.append(
            Paper(
                title=_text(entry, "a:title"),
                abstract=_text(entry, "a:summary"),
                authors=[_text(a, "a:name") for a in entry.findall("a:author", NS)],
                published=_text(entry, "a:published")[:10],
                venue=f"arXiv {primary}".strip(),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=f"https://export.arxiv.org/pdf/{arxiv_id}",
                arxiv_id=arxiv_id,
                doi=_text(entry, "arxiv:doi"),
                categories=[c.get("term", "") for c in entry.findall("a:category", NS)],
                origin="arxiv",
            )
        )
    return papers, total


def fetch(categories: list[str], terms: list[str], start: date, end: date, *, getter=http.get, sleep=time.sleep) -> list[Paper]:
    query = build_query(categories, terms, start, end)
    papers: list[Paper] = []
    offset = 0
    empty_retries = 1
    while offset < MAX_RESULTS:
        params = {
            "search_query": query,
            "start": offset,
            "max_results": PAGE_SIZE,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        _wait_turn(sleep)
        batch, total = parse(getter(API + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)))
        if not batch and offset < total and empty_retries:
            empty_retries -= 1  # arXiv sometimes hands back an empty page mid-way
            continue
        papers.extend(batch)
        offset += PAGE_SIZE
        if not batch or offset >= total:
            break
    return papers
