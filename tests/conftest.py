import math
from pathlib import Path

import pytest

from papertracker.config import Config, Topic

FIXTURES = Path(__file__).parent / "fixtures"
VOCAB = ["avatar", "gaussian", "cybersickness", "teleportation", "peripersonal", "rendering"]


class FakeModel:
    """Counts a few words. Enough to check the plumbing without downloading a model."""

    name = "fake"

    def embed(self, texts):
        out = []
        for text in texts:
            low = text.lower()
            vec = [float(low.count(w)) for w in VOCAB] + [0.05]
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec])
        return out


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()


@pytest.fixture
def topics():
    return [
        Topic(id="avatars", name="Realistic avatars", statement="avatar gaussian avatar", threshold=0.6, arxiv_categories=["cs.CV"]),
        Topic(id="sickness", name="Cybersickness", statement="cybersickness teleportation", threshold=0.6, arxiv_categories=["cs.HC"]),
        Topic(id="neuro", name="VR for neuroscience", statement="peripersonal", threshold=0.6, openalex_search="peripersonal"),
    ]


@pytest.fixture
def config(tmp_path, topics):
    return Config(output_dir=tmp_path / "out", topics=topics)
