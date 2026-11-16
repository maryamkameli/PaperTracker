"""Markdown output: one list per day, and one long list for the catch-up."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .config import Config, Topic
from .models import Paper


def _long_date(d: date) -> str:
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def _short_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _link_path(target: str, start: Path) -> str:
    rel = os.path.relpath(target, start)
    return f"<{rel}>" if " " in rel else rel


def _others(p: Paper, topics: list[Topic], thresholds) -> str:
    names = [t.name for t in topics if t.id != p.topic and p.scores.get(t.id, 0) >= thresholds(t)]
    return f"Also close to: {', '.join(names)}  \n" if names else ""


def _entry(i: int, p: Paper, topics: list[Topic], thresholds, folder: Path) -> str:
    meta = " · ".join(x for x in (f"{p.score:.2f}", p.author_line(), p.venue, p.published) if x)
    links = [f"[Paper]({p.url})"] if p.url else []
    if p.pdf_path:
        links.append(f"[Saved PDF]({_link_path(p.pdf_path, folder)})")
    elif p.pdf_url:
        links.append(f"[PDF]({p.pdf_url})")
    lines = [f"### {i}. {p.title}", "", f"{meta}  ", " · ".join(links) + "  "]
    other = _others(p, topics, thresholds)
    if other:
        lines.append(other.rstrip())
    if p.abstract:
        lines += ["", "<details><summary>Abstract</summary>", "", p.abstract, "", "</details>"]
    return "\n".join(lines)


def group_by_topic(papers: list[Paper], topics: list[Topic]) -> list[tuple[Topic, list[Paper]]]:
    groups = []
    for t in topics:
        members = sorted((p for p in papers if p.topic == t.id), key=lambda p: p.score, reverse=True)
        if members:
            groups.append((t, members))
    return groups


def render_daily(day: date, papers: list[Paper], cfg: Config, thresholds, notes: list[str], window: tuple[date, date]) -> str:
    groups = group_by_topic(papers, cfg.topics)
    saved = sum(1 for p in papers if p.pdf_path)
    out = [f"# New papers for {_long_date(day)}", ""]
    if papers:
        out.append(f"{len(papers)} new {'paper' if len(papers) == 1 else 'papers'} across {len(groups)} "
                   f"{'topic' if len(groups) == 1 else 'topics'}, {saved} {'PDF' if saved == 1 else 'PDFs'} saved. "
                   f"Looked at submissions from {_short_date(window[0])} to {_short_date(window[1])}.")
    else:
        out.append(f"Nothing new cleared the bar. Looked at {_short_date(window[0])} to {_short_date(window[1])}.")
    for note in notes:
        out += ["", f"> {note}"]
    folder = cfg.daily_dir
    for topic, members in groups:
        out += ["", f"## {topic.name} ({len(members)})", ""]
        out.append("\n\n".join(_entry(i, p, cfg.topics, thresholds, folder) for i, p in enumerate(members, 1)))
    return "\n".join(out) + "\n"


def _to_dict(p: Paper) -> dict:
    return asdict(p)


def _from_dict(d: dict) -> Paper:
    p = Paper(**{k: v for k, v in d.items() if k in Paper.__dataclass_fields__})
    return p


def write_daily(day: date, new: list[Paper], cfg: Config, thresholds, notes: list[str], window: tuple[date, date]) -> Path:
    """Add today's matches to the day's file. Running twice in a day keeps both runs' papers."""
    cfg.daily_dir.mkdir(parents=True, exist_ok=True)
    json_path = cfg.daily_dir / f"{day.isoformat()}.json"
    papers: dict[str, Paper] = {}
    if json_path.exists():
        for d in json.loads(json_path.read_text(encoding="utf-8")):
            p = _from_dict(d)
            papers[p.key] = p
    for p in new:
        papers[p.key] = p
    merged = list(papers.values())
    json_path.write_text(json.dumps([_to_dict(p) for p in merged], indent=1, ensure_ascii=False), encoding="utf-8")
    md_path = cfg.daily_dir / f"{day.isoformat()}.md"
    md_path.write_text(render_daily(day, merged, cfg, thresholds, notes, window), encoding="utf-8")
    return md_path


def render_catchup(start: date, end: date, papers: list[Paper], cfg: Config, notes: list[str]) -> str:
    groups = group_by_topic(papers, cfg.topics)
    saved = sum(1 for p in papers if p.pdf_path)
    out = [f"# Catch-up: {_short_date(start)} to {_short_date(end)}", ""]
    out.append(f"{len(papers)} papers matched across {len(groups)} topics. {saved} PDFs saved, "
               f"the strongest {cfg.catchup_pdfs_per_topic} or so in each topic.")
    for note in notes:
        out += ["", f"> {note}"]
    folder = cfg.catchup_dir
    for topic, members in groups:
        out += ["", f"## {topic.name} ({len(members)})"]
        by_month: dict[str, list[Paper]] = {}
        for p in members:
            by_month.setdefault((p.published or "")[:7] or "undated", []).append(p)
        for month in sorted(by_month, reverse=True):
            label = month
            if len(month) == 7:
                label = f"{date(int(month[:4]), int(month[5:]), 1):%B %Y}"
            out += ["", f"### {label}", ""]
            for p in sorted(by_month[month], key=lambda p: p.score, reverse=True):
                bits = [f"**{p.score:.2f}**", f"[{p.title}]({p.url})" if p.url else p.title, p.author_line(2), p.venue, p.published]
                line = " · ".join(b for b in bits if b)
                if p.pdf_path:
                    line += f" · [saved PDF]({_link_path(p.pdf_path, folder)})"
                out.append(f"- {line}")
    return "\n".join(out) + "\n"


def write_catchup(start: date, end: date, papers: list[Paper], cfg: Config, notes: list[str]) -> Path:
    cfg.catchup_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.catchup_dir / f"{start.isoformat()}_to_{end.isoformat()}.md"
    path.write_text(render_catchup(start, end, papers, cfg, notes), encoding="utf-8")
    return path


def save_papers(path: Path, papers: list[Paper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_to_dict(p) for p in papers], ensure_ascii=False), encoding="utf-8")


def load_papers(path: Path) -> list[Paper]:
    if not path.exists():
        return []
    return [_from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
