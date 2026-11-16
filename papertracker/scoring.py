"""Relevance: how close each paper is to a topic paragraph, and to papers you already keep.

Runs locally. The default model (bge-small, about 65 MB) downloads once on the first run.
If fastembed can't be installed, a word-overlap scorer stands in so the job still runs.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .config import Topic
from .models import Paper

LEXICAL_THRESHOLD = 0.12  # word overlap scores live on a much lower scale
_WORD = re.compile(r"[a-z][a-z0-9\-]+")
_STOP = set(
    "a an and are as at be by for from has have in into is it its of on or that the this to was were with we our "
    "their these those which using use used via based new two than can also show shows paper study results".split()
)


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def similarity(a, b) -> float:
    if isinstance(a, dict):  # sparse word vectors
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(k, 0.0) for k, w in a.items())
    return sum(x * y for x, y in zip(a, b))


class EmbeddingModel:
    name = "embedding"

    def __init__(self, model_name: str, cache_dir=None):
        from fastembed import TextEmbedding  # imported here so tests don't need it

        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [_unit([float(x) for x in v]) for v in self._model.embed(list(texts), batch_size=64)]


class WordOverlapModel:
    name = "lexical"

    def embed(self, texts: list[str]) -> list[dict]:
        out = []
        for text in texts:
            counts = Counter(w for w in _WORD.findall(text.lower()) if w not in _STOP)
            norm = math.sqrt(sum(c * c for c in counts.values())) or 1.0
            out.append({w: c / norm for w, c in counts.items()})
        return out


def load_model(model_name: str, cache_dir=None):
    try:
        return EmbeddingModel(model_name, cache_dir), ""
    except Exception as err:  # missing package, no network for the first download, ...
        return WordOverlapModel(), f"embedding model unavailable ({err.__class__.__name__}: {err}); using word overlap"


def paper_text(p: Paper) -> str:
    return f"{p.title}. {p.abstract[:2000]}"


class TopicScorer:
    def __init__(self, topics: list[Topic], model, seeds: dict[str, list[str]] | None = None, seed_weight: float = 0.9):
        self.topics = topics
        self.model = model
        self.seed_weight = seed_weight
        self.lexical = getattr(model, "name", "") == "lexical"
        self.topic_vecs = dict(zip([t.id for t in topics], model.embed([t.statement for t in topics])))
        self.seed_vecs = {tid: model.embed(titles) for tid, titles in (seeds or {}).items() if titles}

    def threshold(self, topic: Topic) -> float:
        return LEXICAL_THRESHOLD if self.lexical else topic.threshold

    def pdf_threshold(self, topic: Topic) -> float:
        return LEXICAL_THRESHOLD * 1.5 if self.lexical else topic.pdf_threshold

    def score(self, papers: list[Paper]) -> None:
        if not papers:
            return
        full = self.model.embed([paper_text(p) for p in papers])
        titles = self.model.embed([p.title for p in papers]) if self.seed_vecs else [None] * len(papers)
        for p, vec, tvec in zip(papers, full, titles):
            scores = {}
            for t in self.topics:
                s = similarity(vec, self.topic_vecs[t.id])
                seeds = self.seed_vecs.get(t.id)
                if seeds and tvec is not None:
                    s = max(s, self.seed_weight * max(similarity(tvec, sv) for sv in seeds))
                scores[t.id] = round(s, 4)
            p.scores = scores
            passing = [(scores[t.id], t.id) for t in self.topics if scores[t.id] >= self.threshold(t)]
            if passing:
                p.score, p.topic = max(passing)
            else:
                p.score, p.topic = max(scores.values()), ""
