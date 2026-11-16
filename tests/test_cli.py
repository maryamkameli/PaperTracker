import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from papertracker import cli, config as config_mod
from papertracker.models import Paper
from papertracker.scoring import TopicScorer

from .conftest import FakeModel


def test_dedupe_keeps_the_arxiv_copy_and_fills_in_the_venue():
    oa = Paper(title="Relightable Gaussian Head Avatars", doi="10.1109/tvcg.2026.1", venue="IEEE TVCG", origin="openalex")
    ax = Paper(title="Relightable Gaussian head avatars.", arxiv_id="2611.04321", venue="arXiv cs.CV",
               pdf_url="https://export.arxiv.org/pdf/2611.04321", origin="arxiv")
    other = Paper(title="Something else", origin="openalex")
    out = cli.dedupe([oa, ax, other])
    assert len(out) == 2
    kept = [p for p in out if p.arxiv_id][0]
    assert kept.venue == "IEEE TVCG" and kept.doi == "10.1109/tvcg.2026.1" and kept.pdf_url


def test_month_windows_clip_to_the_range():
    windows = list(cli.month_windows(date(2025, 11, 20), date(2026, 1, 10)))
    assert windows == [(date(2025, 11, 20), date(2025, 11, 30)), (date(2025, 12, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 10))]


def test_config_loads_and_complains(tmp_path):
    good = tmp_path / "topics.toml"
    good.write_text('''output_dir = "~/papers"
since = 2025-01-01
[[topics]]
id = "vr"
name = "VR"
statement = "virtual reality"
arxiv_categories = ["cs.HC"]
openalex_search = 'a, b'
''')
    cfg = config_mod.load(good)
    assert cfg.since == date(2025, 1, 1)
    assert cfg.output_dir.name == "papers" and "~" not in str(cfg.output_dir)
    assert cfg.topics[0].pdf_threshold == 0.75
    assert cfg.topics[0].openalex_search == "a b"
    bad = tmp_path / "bad.toml"
    bad.write_text('output_dir = "x"\n[[topics]]\nid = "vr"\nname = "VR"\nstatement = "s"\n')
    with pytest.raises(config_mod.ConfigError, match="needs arxiv_categories"):
        config_mod.load(bad)


def _fake_sources(monkeypatch, papers_by_source):
    monkeypatch.setattr(cli.arxiv, "fetch", lambda *a, **k: list(papers_by_source.get("arxiv", [])))
    monkeypatch.setattr(cli.openalex, "fetch", lambda *a, **k: list(papers_by_source.get("openalex", [])))
    monkeypatch.setattr(cli, "load_model", lambda *a, **k: (FakeModel(), ""))
    monkeypatch.setattr(cli, "notify", lambda *a, **k: None)


def _args(**kw):
    base = dict(days=None, dry_run=False, no_pdf=True, explain=False)
    return SimpleNamespace(**{**base, **kw})


def test_daily_run_writes_list_library_and_state(config, monkeypatch):
    _fake_sources(monkeypatch, {
        "arxiv": [Paper(title="Gaussian avatar heads", abstract="avatar avatar gaussian", arxiv_id="2611.1", origin="arxiv"),
                  Paper(title="Protein folding", abstract="nothing relevant", arxiv_id="2611.2", origin="arxiv")],
        "openalex": [Paper(title="Peripersonal space in VR", abstract="peripersonal peripersonal", doi="10.1/x", origin="openalex")],
    })
    assert cli.cmd_run(config, _args()) == 0
    today = date.today().isoformat()
    text = (config.daily_dir / f"{today}.md").read_text()
    assert "Gaussian avatar heads" in text and "Peripersonal space in VR" in text and "Protein folding" not in text
    state = json.loads((config.state_dir / "state.json").read_text())
    assert state["last_success"] == today and state["last_run"]["matches"] == 2
    # the same papers again the next day are not listed twice
    assert cli.cmd_run(config, _args()) == 0
    assert (config.library_path).read_text().count("Gaussian avatar heads") == 1


def test_run_stops_when_every_source_fails(config, monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(cli.arxiv, "fetch", boom)
    monkeypatch.setattr(cli.openalex, "fetch", boom)
    assert cli.cmd_run(config, _args()) == 2
    assert not (config.state_dir / "state.json").exists()


class LaptopSlept(BaseException):
    """Not an Exception, so collect() can't swallow it, like a real interruption."""


def test_catchup_resumes_after_an_interruption(config, monkeypatch):
    interrupt = {"on": True}
    months_fetched = []

    def fetch(categories, terms, start, end, **k):
        if interrupt["on"] and start.month == 2:
            raise LaptopSlept()
        months_fetched.append(start.month)
        return [Paper(title=f"Gaussian avatar {start:%b %Y} {categories[0]}", abstract="avatar gaussian",
                      arxiv_id=f"x{start:%m}{categories[0]}", published=start.isoformat(), origin="arxiv")]

    monkeypatch.setattr(cli.arxiv, "fetch", fetch)
    monkeypatch.setattr(cli.openalex, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(cli, "load_model", lambda *a, **k: (FakeModel(), ""))
    monkeypatch.setattr(cli, "notify", lambda *a, **k: None)
    args = SimpleNamespace(since="2025-01-01", until="2025-03-31", no_pdf=True, dry_run=False, restart=False)
    with pytest.raises(LaptopSlept):
        cli.cmd_catchup(config, args)
    assert json.loads((config.state_dir / "state.json").read_text())["catchup"]["done_through"] == "2025-01-31"
    interrupt["on"] = False
    months_fetched.clear()
    assert cli.cmd_catchup(config, args) == 0
    assert 1 not in months_fetched  # January was not fetched again
    text = (config.catchup_dir / "2025-01-01_to_2025-03-31.md").read_text()
    for month in ("January 2025", "February 2025", "March 2025"):
        assert month in text


def test_daily_window_always_reaches_a_week_back(config, monkeypatch):
    seen = {}

    def fetch(categories, terms, start, end, **k):
        seen["start"], seen["end"] = start, end
        return []

    monkeypatch.setattr(cli.arxiv, "fetch", fetch)
    monkeypatch.setattr(cli.openalex, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(cli, "load_model", lambda *a, **k: (FakeModel(), ""))
    monkeypatch.setattr(cli, "notify", lambda *a, **k: None)
    (config.state_dir).mkdir(parents=True)
    (config.state_dir / "state.json").write_text(json.dumps({"last_success": date.today().isoformat()}))
    assert cli.cmd_run(config, _args()) == 0
    assert seen["start"] == date.today() - timedelta(days=7)


def test_catchup_stops_when_one_source_fails(config, monkeypatch):
    monkeypatch.setattr(cli.arxiv, "fetch", lambda *a, **k: [])
    def openalex_down(*a, **k):
        raise RuntimeError("daily request limit reached")
    monkeypatch.setattr(cli.openalex, "fetch", openalex_down)
    monkeypatch.setattr(cli, "load_model", lambda *a, **k: (FakeModel(), ""))
    args = SimpleNamespace(since="2025-01-01", until="2025-02-28", no_pdf=True, dry_run=False, restart=False)
    assert cli.cmd_catchup(config, args) == 2
    state = json.loads((config.state_dir / "state.json").read_text()) if (config.state_dir / "state.json").exists() else {}
    assert "catchup" not in state  # January isn't marked done, so it gets fetched again next time
