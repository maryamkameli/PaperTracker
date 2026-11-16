from papertracker.models import Paper
from papertracker.scoring import TopicScorer, WordOverlapModel, similarity

from .conftest import FakeModel


def test_papers_land_in_the_closest_topic(topics):
    scorer = TopicScorer(topics, FakeModel())
    a = Paper(title="Gaussian avatar heads", abstract="An avatar built from gaussian splats.")
    b = Paper(title="Teleportation study", abstract="Cybersickness was lower with teleportation.")
    c = Paper(title="Protein folding", abstract="Nothing to do with any topic.")
    scorer.score([a, b, c])
    assert a.topic == "avatars"
    assert b.topic == "sickness"
    assert c.topic == ""
    assert set(a.scores) == {"avatars", "sickness", "neuro"}


def test_seed_titles_pull_papers_in(topics):
    topics[0].threshold = 0.95
    plain = TopicScorer(topics, FakeModel())
    seeded = TopicScorer(topics, FakeModel(), seeds={"avatars": ["Gaussian avatar"]}, seed_weight=1.0)
    p1 = Paper(title="Gaussian avatar", abstract="rendering rendering rendering")
    p2 = Paper(title="Gaussian avatar", abstract="rendering rendering rendering")
    plain.score([p1])
    seeded.score([p2])
    assert p1.topic != "avatars"
    assert p2.topic == "avatars"


def test_word_overlap_fallback_scores_related_text_higher():
    model = WordOverlapModel()
    a, b, c = model.embed(["cybersickness during teleportation", "teleportation reduces cybersickness", "protein folding"])
    assert similarity(a, b) > similarity(a, c)
