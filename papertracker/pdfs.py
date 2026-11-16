"""Download open-access PDFs, but only for the strongest match or two per topic."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .models import Paper
from .sources import arxiv, http

MAX_BYTES = 80 * 1024 * 1024


class NotAPdf(RuntimeError):
    pass


def filename(paper: Paper) -> str:
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", paper.title)
    title = " ".join(title.split()).rstrip(".")
    if len(title) > 90:
        title = title[:90].rsplit(" ", 1)[0]
    last = re.sub(r'[\\/:*?"<>|]+', "", paper.first_author_last) or "Unknown"
    return f"{paper.year or 'n.d.'} {last} - {title}.pdf"


def pick(papers: list[Paper], per_topic: int, min_score_for) -> list[Paper]:
    """The top `per_topic` papers in each topic that clear that topic's PDF bar and have a free PDF."""
    chosen = []
    by_topic: dict[str, list[Paper]] = {}
    for p in papers:
        if p.topic and p.pdf_url and p.score >= min_score_for(p.topic):
            by_topic.setdefault(p.topic, []).append(p)
    for group in by_topic.values():
        group.sort(key=lambda p: p.score, reverse=True)
        chosen.extend(group[:per_topic])
    return chosen


def download(paper: Paper, folder: Path, *, getter=http.get, sleep=time.sleep) -> Path:
    path = Path(folder) / filename(paper)
    if path.exists():
        return path
    if "arxiv.org" in paper.pdf_url:
        arxiv._wait_turn(sleep)  # same three-second courtesy as the API
    data = getter(paper.pdf_url, timeout=120, retries=2)
    if not data.startswith(b"%PDF"):
        raise NotAPdf(paper.pdf_url)
    if len(data) > MAX_BYTES:
        raise NotAPdf(f"{paper.pdf_url} is larger than {MAX_BYTES // 1_000_000} MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def save_all(papers: list[Paper], pdf_root: Path, log=print, **kwargs) -> int:
    saved = 0
    for p in papers:
        month = (p.published or "")[:7] or "undated"
        try:
            path = download(p, Path(pdf_root) / p.topic / month, **kwargs)
        except Exception as err:  # one bad link shouldn't stop the rest
            log(f"  no PDF for '{p.title[:60]}': {err}")
            continue
        p.pdf_path = str(path)
        saved += 1
    return saved
