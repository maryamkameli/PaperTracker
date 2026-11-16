"""OpenAlex: journals and proceedings that don't go through arXiv (TVCG, TOG, CHI, neuroscience journals)."""
from __future__ import annotations

import re
import time
import urllib.parse
from datetime import date

from ..models import Paper
from . import http

API = "https://api.openalex.org"
SELECT = "id,doi,display_name,publication_date,authorships,primary_location,best_oa_location,abstract_inverted_index,type"
SKIP_TYPES = {"editorial", "erratum", "paratext", "letter", "retraction", "dataset", "peer-review", "supplementary-materials"}
PER_PAGE = 200
MAX_PAGES = 40
PAUSE = 1.2  # a short gap between calls keeps OpenAlex from answering 429

_last_call = 0.0


def _wait_turn(sleep=time.sleep) -> None:
    global _last_call
    gap = PAUSE - (time.monotonic() - _last_call)
    if gap > 0:
        sleep(gap)
    _last_call = time.monotonic()


def abstract_from_index(index: dict | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    if not index:
        return ""
    words = {}
    for word, positions in index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))


def parse_work(work: dict) -> Paper | None:
    if work.get("type") in SKIP_TYPES:
        return None
    title = work.get("display_name") or ""
    if not title:
        return None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    best = work.get("best_oa_location") or {}
    authors = [(a.get("author") or {}).get("display_name", "") for a in work.get("authorships") or []]
    doi = work.get("doi") or ""
    return Paper(
        title=title,
        abstract=abstract_from_index(work.get("abstract_inverted_index")),
        authors=[a for a in authors if a],
        published=work.get("publication_date") or "",
        venue=source.get("display_name") or "",
        url=doi or location.get("landing_page_url") or work.get("id", ""),
        pdf_url=best.get("pdf_url") or "",
        doi=doi,
        origin="openalex",
    )


def _params(extra: dict, email: str, api_key: str = "") -> str:
    if email:
        extra = {**extra, "mailto": email}
    if api_key:
        extra = {**extra, "api_key": api_key}
    return urllib.parse.urlencode(extra)


def fetch(start: date, end: date, *, search: str = "", source_ids: list[str] | tuple = (), fields: list[int] | tuple = (),
          email: str = "", api_key: str = "", max_pages: int = MAX_PAGES, getter=http.get_json, sleep=time.sleep) -> list[Paper]:
    """Works published between start and end. `fields` (OpenAlex field ids, e.g. 17 = Computer Science)
    narrows a keyword search so VR papers from, say, nursing education stay out."""
    filters = [f"from_publication_date:{start.isoformat()}", f"to_publication_date:{end.isoformat()}"]
    if search and fields:
        filters.append("primary_topic.field.id:" + "|".join(str(f) for f in fields))
    if search:
        filters.append(f"title_and_abstract.search:{search}")
    if source_ids:
        filters.append("primary_location.source.id:" + "|".join(source_ids))
    papers: list[Paper] = []
    cursor = "*"
    for _ in range(max_pages):
        _wait_turn(sleep)
        data = getter(f"{API}/works?" + _params({"filter": ",".join(filters), "per_page": PER_PAGE, "cursor": cursor, "select": SELECT}, email, api_key))
        results = data.get("results") or []
        for work in results:
            paper = parse_work(work)
            if paper:
                papers.append(paper)
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor or not results:
            break
    return papers


def resolve_sources(names: list[str], cache: dict, *, email: str = "", api_key: str = "", getter=http.get_json, sleep=time.sleep) -> list[str]:
    """Turn venue names into OpenAlex source ids, remembering answers in `cache`.
    A name that already looks like an id (S84775595) is used as is."""
    ids = []
    for name in names:
        if re.fullmatch(r"S\d+", name.strip()):
            ids.append(name.strip())
            continue
        if name not in cache:
            _wait_turn(sleep)
            data = getter(f"{API}/sources?" + _params({"search": name, "per_page": 1, "select": "id,display_name"}, email, api_key))
            hits = data.get("results") or []
            cache[name] = [hits[0]["id"].rsplit("/", 1)[-1], hits[0].get("display_name", "")] if hits else None
        if cache[name]:
            ids.append(cache[name][0])
    return ids
