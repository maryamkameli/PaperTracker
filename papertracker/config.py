from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib


class ConfigError(ValueError):
    pass


@dataclass
class Topic:
    id: str
    name: str
    statement: str
    threshold: float = 0.70
    pdf_threshold: float | None = None
    arxiv_categories: list[str] = field(default_factory=list)
    arxiv_terms: list[str] = field(default_factory=list)
    openalex_search: str = ""
    openalex_venues: list[str] = field(default_factory=list)
    seed_folders: list[str] = field(default_factory=list)
    seed_titles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.pdf_threshold is None:
            self.pdf_threshold = round(self.threshold + 0.05, 3)
        self.statement = " ".join(self.statement.split())
        # commas split OpenAlex filters, so they can't appear inside a search
        self.openalex_search = " ".join(self.openalex_search.replace(",", " ").split())


@dataclass
class Config:
    output_dir: Path
    topics: list[Topic]
    since: date = date(2025, 1, 1)
    pdfs_per_topic_per_day: int = 2
    catchup_pdfs_per_topic: int = 20
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    seed_weight: float = 0.9
    openalex_email: str = ""
    openalex_api_key: str = ""
    # OpenAlex field ids a keyword search must fall in: 17 Computer Science, 32 Psychology, 28 Neuroscience
    openalex_fields: list[int] = field(default_factory=lambda: [17, 32, 28])
    notify: bool = True
    path: Path | None = None

    @property
    def daily_dir(self) -> Path:
        return self.output_dir / "daily"

    @property
    def pdf_dir(self) -> Path:
        return self.output_dir / "pdfs"

    @property
    def catchup_dir(self) -> Path:
        return self.output_dir / "catch-up"

    @property
    def state_dir(self) -> Path:
        return self.output_dir / "state"

    @property
    def library_path(self) -> Path:
        return self.output_dir / "library.csv"

    @property
    def model_cache(self) -> Path:
        return Path.home() / ".cache" / "papertracker" / "models"

    def topic(self, topic_id: str) -> Topic:
        for t in self.topics:
            if t.id == topic_id:
                return t
        raise KeyError(topic_id)


_TOPIC_KEYS = {f.name for f in fields(Topic)}
_CONFIG_KEYS = {f.name for f in fields(Config)} - {"topics", "output_dir", "path"}


def _as_date(value, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ConfigError(f"{name} should look like 2025-01-01, got {value!r}") from None


def load(path: str | os.PathLike) -> Config:
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"no config at {path}. Copy topics.example.toml to topics.toml and edit it.")
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    topics = []
    seen = set()
    for t in raw.pop("topics", []):
        tid = t.get("id", "?")
        missing = [k for k in ("id", "name", "statement") if not t.get(k)]
        if missing:
            raise ConfigError(f"topic {tid} is missing {', '.join(missing)}")
        unknown = set(t) - _TOPIC_KEYS
        if unknown:
            raise ConfigError(f"topic {tid} has unknown keys: {', '.join(sorted(unknown))}")
        if tid in seen:
            raise ConfigError(f"two topics share the id {tid}")
        if not (t.get("arxiv_categories") or t.get("openalex_search") or t.get("openalex_venues")):
            raise ConfigError(f"topic {tid} needs arxiv_categories, openalex_search or openalex_venues")
        seen.add(tid)
        topics.append(Topic(**t))
    if not topics:
        raise ConfigError("add at least one [[topics]] block")

    out = raw.pop("output_dir", "")
    if not out:
        raise ConfigError("set output_dir, the folder where lists and PDFs go")
    unknown = set(raw) - _CONFIG_KEYS
    if unknown:
        raise ConfigError(f"unknown settings: {', '.join(sorted(unknown))}")
    if "since" in raw:
        raw["since"] = _as_date(raw["since"], "since")

    return Config(output_dir=Path(os.path.expanduser(str(out))), topics=topics, path=path, **raw)
