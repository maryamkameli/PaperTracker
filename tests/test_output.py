from datetime import date

import pytest

from papertracker import digest, pdfs
from papertracker.models import Paper


def _paper(title, topic, score, **kw):
    return Paper(title=title, topic=topic, score=score, scores={topic: score}, url=f"https://x.org/{len(title)}", **kw)


def test_daily_file_keeps_earlier_runs(config):
    th = lambda t: t.threshold
    window = (date(2026, 11, 14), date(2026, 11, 16))
    day = date(2026, 11, 16)
    digest.write_daily(day, [_paper("First paper", "avatars", 0.8)], config, th, [], window)
    path = digest.write_daily(day, [_paper("Second paper", "sickness", 0.75)], config, th, ["arXiv was slow"], window)
    text = path.read_text()
    assert "# New papers for Monday, November 16, 2026" in text
    assert "## Realistic avatars (1)" in text and "## Cybersickness (1)" in text
    assert "First paper" in text and "Second paper" in text
    assert "> arXiv was slow" in text
    assert (config.daily_dir / "2026-11-16.json").exists()


def test_daily_file_links_saved_pdf(config):
    pdf = config.pdf_dir / "avatars" / "2026-11" / "2026 Smith - Heads.pdf"
    p = _paper("Heads", "avatars", 0.9, pdf_path=str(pdf), abstract="An abstract.")
    path = digest.write_daily(date(2026, 11, 16), [p], config, lambda t: t.threshold, [], (date(2026, 11, 15), date(2026, 11, 16)))
    text = path.read_text()
    assert "[Saved PDF](<../pdfs/avatars/2026-11/2026 Smith - Heads.pdf>)" in text
    assert "<details><summary>Abstract</summary>" in text


def test_empty_day_says_so(config):
    path = digest.write_daily(date(2026, 11, 16), [], config, lambda t: t.threshold, [], (date(2026, 11, 15), date(2026, 11, 16)))
    assert "Nothing new cleared the bar" in path.read_text()


def test_catchup_groups_by_month(config):
    papers = [_paper("Old one", "avatars", 0.71, published="2025-02-03"), _paper("New one", "avatars", 0.9, published="2026-10-01")]
    text = digest.render_catchup(date(2025, 1, 1), date(2026, 11, 16), papers, config, [])
    assert text.index("### October 2026") < text.index("### February 2025")


def test_pdf_filename_is_safe():
    p = Paper(title='What/Is: "Real"? A Study of Avatars', authors=["Ana María López"], published="2026-11-15")
    assert pdfs.filename(p) == "2026 López - What Is Real A Study of Avatars.pdf"


def test_pick_takes_the_strongest_per_topic():
    papers = [
        _paper("a1", "avatars", 0.95, pdf_url="u"), _paper("a2", "avatars", 0.90, pdf_url="u"),
        _paper("a3", "avatars", 0.85, pdf_url="u"), _paper("a4", "avatars", 0.99),  # no free PDF
        _paper("s1", "sickness", 0.74, pdf_url="u"),  # under the PDF bar
    ]
    chosen = pdfs.pick(papers, 2, lambda tid: 0.8)
    assert [p.title for p in chosen] == ["a1", "a2"]


def test_download_checks_for_a_real_pdf(tmp_path):
    p = Paper(title="Heads", authors=["Ana Smith"], published="2026-11-15", pdf_url="https://example.org/x.pdf")
    path = pdfs.download(p, tmp_path, getter=lambda url, **kw: b"%PDF-1.7 ...", sleep=lambda s: None)
    assert path.name == "2026 Smith - Heads.pdf" and path.read_bytes().startswith(b"%PDF")
    p2 = Paper(title="Paywalled", pdf_url="https://example.org/login")
    with pytest.raises(pdfs.NotAPdf):
        pdfs.download(p2, tmp_path, getter=lambda url, **kw: b"<html>", sleep=lambda s: None)
