"""library.csv: every paper the tracker has kept, so nothing shows up twice."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from .models import Paper, looks_like_arxiv_id, norm_title, strip_version

FIELDS = ["key", "title", "authors", "published", "venue", "topic", "score", "url", "pdf_url", "pdf_path", "found_on", "arxiv_id", "doi"]


class Library:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: dict[str, dict] = {}
        self._titles: set[str] = set()
        if self.path.exists():
            with open(self.path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self.rows[row["key"]] = row
                    self._titles.add(norm_title(row.get("title", "")))

    def __len__(self) -> int:
        return len(self.rows)

    def __contains__(self, paper: Paper) -> bool:
        return paper.key in self.rows or norm_title(paper.title) in self._titles

    def add(self, paper: Paper, found_on: str) -> None:
        self.rows[paper.key] = {
            "key": paper.key,
            "title": paper.title,
            "authors": "; ".join(paper.authors),
            "published": paper.published,
            "venue": paper.venue,
            "topic": paper.topic,
            "score": f"{paper.score:.3f}",
            "url": paper.url,
            "pdf_url": paper.pdf_url,
            "pdf_path": paper.pdf_path,
            "found_on": found_on,
            "arxiv_id": paper.arxiv_id,
            "doi": paper.doi,
        }
        self._titles.add(norm_title(paper.title))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for row in sorted(self.rows.values(), key=lambda r: (r["found_on"], r["topic"], r["title"])):
                writer.writerow({k: row.get(k, "") for k in FIELDS})
        os.replace(tmp, self.path)


class Owned:
    """Papers already sitting in your own folders, judged by their PDF file names."""

    def __init__(self, folders: list[str]):
        self.titles: set[str] = set()
        self.arxiv_ids: set[str] = set()
        self.names: list[str] = []
        for folder in folders:
            root = Path(os.path.expanduser(folder))
            if not root.is_dir():
                continue
            for pdf in root.rglob("*.pdf"):
                stem = pdf.stem.strip()
                if looks_like_arxiv_id(stem):
                    self.arxiv_ids.add(strip_version(stem))
                else:
                    self.titles.add(norm_title(stem))
                    self.names.append(stem)

    def __contains__(self, paper: Paper) -> bool:
        return (paper.arxiv_id and paper.arxiv_id in self.arxiv_ids) or norm_title(paper.title) in self.titles
