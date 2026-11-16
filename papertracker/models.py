from __future__ import annotations

import re
from dataclasses import dataclass, field

_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_ARXIV_ID = re.compile(r"^(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$", re.IGNORECASE)


def norm_title(title: str) -> str:
    """Lowercase, letters and digits only. Used to spot the same paper from two sources."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def looks_like_arxiv_id(text: str) -> bool:
    return bool(_ARXIV_ID.match(text.strip()))


@dataclass
class Paper:
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""  # YYYY-MM-DD
    venue: str = ""
    url: str = ""
    pdf_url: str = ""
    arxiv_id: str = ""
    doi: str = ""
    categories: list[str] = field(default_factory=list)
    origin: str = ""  # "arxiv" or "openalex"

    # set while scoring and saving
    topic: str = ""
    score: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    pdf_path: str = ""

    def __post_init__(self) -> None:
        self.title = " ".join(self.title.split())
        self.abstract = " ".join(self.abstract.split())
        if self.doi:
            doi = self.doi.strip().lower()
            for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                if doi.startswith(prefix):
                    doi = doi[len(prefix):]
            self.doi = doi
            m = _ARXIV_DOI.match(doi)
            if m and not self.arxiv_id:
                self.arxiv_id = strip_version(m.group(1))
        if self.arxiv_id:
            self.arxiv_id = strip_version(self.arxiv_id)

    @property
    def key(self) -> str:
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.doi:
            return f"doi:{self.doi}"
        return f"title:{norm_title(self.title)}"

    @property
    def year(self) -> str:
        return self.published[:4]

    @property
    def first_author_last(self) -> str:
        if not self.authors:
            return ""
        name = self.authors[0].strip()
        if "," in name:  # "Smith, Ana"
            return name.split(",")[0].strip()
        return name.split()[-1] if name.split() else ""

    def author_line(self, limit: int = 3) -> str:
        if len(self.authors) <= limit:
            return ", ".join(self.authors)
        return ", ".join(self.authors[:limit]) + ", et al."

    def merge(self, other: "Paper") -> None:
        """Fill gaps from another record of the same paper."""
        for name in ("abstract", "venue", "url", "pdf_url", "arxiv_id", "doi", "published"):
            if not getattr(self, name) and getattr(other, name):
                setattr(self, name, getattr(other, name))
        if not self.authors and other.authors:
            self.authors = list(other.authors)
        if other.venue and other.origin == "openalex" and self.venue.startswith("arXiv"):
            # a journal or proceedings name says more than the arXiv category
            self.venue = other.venue
