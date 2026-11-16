"""papertracker run | catchup | check | sources"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from . import __version__, digest, pdfs
from .config import Config, ConfigError, load
from .library import Library, Owned
from .models import Paper, norm_title
from .scoring import TopicScorer, load_model
from .sources import arxiv, http, openalex

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = os.environ.get("PAPERTRACKER_CONFIG", str(REPO / "topics.toml"))


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- small state files

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def python_paths() -> list[str]:
    """What to add under Full Disk Access so a background job can use the Desktop."""
    real = os.path.realpath(sys.executable)
    paths = [real]
    app = Path(sys.base_prefix) / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    if ".framework" in real and app.exists():
        paths.append(str(app))
    return paths


def ensure_output(cfg: Config) -> bool:
    try:
        for d in (cfg.output_dir, cfg.daily_dir, cfg.state_dir):
            d.mkdir(parents=True, exist_ok=True)
        probe = cfg.state_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except PermissionError:
        log(f"Can't write to {cfg.output_dir}. macOS keeps background jobs out of the Desktop until you allow it:")
        log("System Settings > Privacy & Security > Full Disk Access, click +, press Cmd+Shift+G and add:")
        for p in python_paths():
            log(f"  {p}")
        return False


# ---------------------------------------------------------------- fetching

def dedupe(papers: list[Paper]) -> list[Paper]:
    """One record per paper. Keep the arXiv copy (it has a free PDF) and fill gaps from the others."""
    keep: dict[str, Paper] = {}
    title_to_key: dict[str, str] = {}
    for p in papers:
        title = norm_title(p.title)
        key = p.key if p.key in keep else title_to_key.get(title)
        if key is None:
            keep[p.key] = p
            title_to_key[title] = p.key
            continue
        held = keep[key]
        if held.origin != "arxiv" and p.origin == "arxiv":
            p.merge(held)
            del keep[key]
            keep[p.key] = p
            title_to_key[title] = p.key
        else:
            held.merge(p)
    return list(keep.values())


def collect(cfg: Config, start: date, end: date, oa_start: date, cache: dict):
    found: list[Paper] = []
    notes: list[str] = []
    answered = calls = 0
    down: set[str] = set()
    for t in cfg.topics:
        jobs = []
        if t.arxiv_categories:
            jobs.append(("arXiv", lambda t=t: arxiv.fetch(t.arxiv_categories, t.arxiv_terms, start, end)))
        oa = dict(email=cfg.openalex_email, api_key=cfg.openalex_api_key)
        if t.openalex_search:
            fields = cfg.openalex_fields if t.openalex_fields is None else t.openalex_fields
            jobs.append(("OpenAlex", lambda t=t, fields=fields: openalex.fetch(oa_start, end, search=t.openalex_search, fields=fields, **oa)))
        if t.openalex_venues:
            def by_venue(t=t):
                ids = openalex.resolve_sources(t.openalex_venues, cache, **oa)
                return openalex.fetch(oa_start, end, source_ids=ids, **oa) if ids else []
            jobs.append(("OpenAlex venues", by_venue))
        for label, job in jobs:
            calls += 1
            service = label.split()[0]
            if service in down:
                continue
            try:
                got = job()
            except Exception as err:
                down.add(service)  # don't sit through the same timeouts for every topic
                notes.append(f"{service} didn't answer ({err.__class__.__name__}: {err}), so some topics may be missing papers today.")
                log(f"  {label} / {t.id}: failed ({err}), skipping {service} for the rest of this run")
                continue
            answered += 1
            found.extend(got)
            log(f"  {label} / {t.id}: {len(got)}")
    return dedupe(found), notes, answered, calls


def build_scorer(cfg: Config):
    model, warning = load_model(cfg.embedding_model, cfg.model_cache)
    seeds = {}
    for t in cfg.topics:
        titles = (Owned(t.seed_folders).names if t.seed_folders else []) + list(t.seed_titles)
        if titles:
            seeds[t.id] = titles
    return TopicScorer(cfg.topics, model, seeds, cfg.seed_weight), warning


def owned_papers(cfg: Config) -> Owned:
    return Owned(sorted({f for t in cfg.topics for f in t.seed_folders}))


def explain(papers: list[Paper], cfg: Config, scorer: TopicScorer, top: int = 8) -> None:
    for t in cfg.topics:
        ranked = sorted(papers, key=lambda p: p.scores.get(t.id, 0), reverse=True)[:top]
        log(f"\n{t.name} (threshold {scorer.threshold(t):.2f})")
        for p in ranked:
            s = p.scores.get(t.id, 0)
            log(f"  {s:.3f} {'*' if s >= scorer.threshold(t) else ' '} {p.title[:100]}")


def notify(cfg: Config, message: str) -> None:
    if cfg.notify and sys.platform == "darwin":
        script = f'display notification "{message}" with title "PaperTracker"'
        subprocess.run(["osascript", "-e", script], check=False, timeout=15, capture_output=True)


# ---------------------------------------------------------------- commands

def cmd_run(cfg: Config, args) -> int:
    today = date.today()
    if not args.dry_run and not ensure_output(cfg):
        return 3
    state_path = cfg.state_dir / "state.json"
    state = _load_json(state_path, {})
    if args.days:
        start = today - timedelta(days=args.days)
    elif state.get("last_success"):
        start = date.fromisoformat(state["last_success"]) - timedelta(days=2)
    else:
        start = today
    # arXiv lists a paper a day or more after it's submitted, so always look a week back;
    # library.csv keeps anything already listed from showing up again
    start = max(min(start, today - timedelta(days=7)), today - timedelta(days=30))
    oa_start = min(start, today - timedelta(days=14))  # OpenAlex indexes some papers a week or two late
    log(f"PaperTracker {__version__}: {start} to {today}")

    cache_path = cfg.state_dir / "openalex_sources.json"
    cache = _load_json(cache_path, {})
    papers, notes, answered, calls = collect(cfg, start, today, oa_start, cache)
    if calls and not answered:
        log("No source answered, so nothing was written. The next run covers this window again.")
        return 2

    library = Library(cfg.library_path)
    owned = owned_papers(cfg)
    fresh = [p for p in papers if p not in library and p not in owned]
    log(f"  {len(papers)} found, {len(fresh)} new to you")
    scorer, warning = build_scorer(cfg)
    if warning:
        notes.append(warning)
        log(f"  {warning}")
    scorer.score(fresh)
    matches = [p for p in fresh if p.topic]
    if args.explain:
        explain(fresh, cfg, scorer)
    if args.dry_run:
        for topic, members in digest.group_by_topic(matches, cfg.topics):
            log(f"\n{topic.name}: {len(members)}")
            for p in members:
                log(f"  {p.score:.3f}  {p.title[:100]}")
        log(f"\n{len(matches)} matches. Dry run, nothing saved.")
        return 0

    saved = 0
    if not args.no_pdf:
        chosen = pdfs.pick(matches, cfg.pdfs_per_topic_per_day, lambda tid: scorer.pdf_threshold(cfg.topic(tid)))
        saved = pdfs.save_all(chosen, cfg.pdf_dir, log=log)
    path = digest.write_daily(today, matches, cfg, scorer.threshold, notes, (start, today))
    for p in matches:
        library.add(p, today.isoformat())
    library.save()
    _save_json(cache_path, cache)
    state.update(last_success=today.isoformat(), last_run={"matches": len(matches), "pdfs": saved, "notes": notes})
    _save_json(state_path, state)
    log(f"  {len(matches)} matched, {saved} PDFs saved. {path}")
    notify(cfg, f"{len(matches)} new papers, {saved} PDFs saved")
    return 0


def month_windows(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def cmd_catchup(cfg: Config, args) -> int:
    since = date.fromisoformat(args.since) if args.since else cfg.since
    until = date.fromisoformat(args.until) if args.until else date.today()
    if not args.dry_run and not ensure_output(cfg):
        return 3
    state_path = cfg.state_dir / "state.json"
    found_path = cfg.state_dir / "catchup_found.json"
    state = _load_json(state_path, {})
    progress = state.get("catchup") or {}
    same_run = progress.get("since") == since.isoformat() and progress.get("until") == until.isoformat()
    if same_run and not args.restart and progress.get("done_through"):
        done_through = date.fromisoformat(progress["done_through"])
        found = digest.load_papers(found_path)
        log(f"Picking up after {done_through} with {len(found)} papers kept so far.")
    else:
        done_through, found = None, []

    library = Library(cfg.library_path)
    owned = owned_papers(cfg)
    scorer, warning = build_scorer(cfg)
    notes = [warning] if warning else []
    seen = {p.key for p in found} | {norm_title(p.title) for p in found}
    cache_path = cfg.state_dir / "openalex_sources.json"
    cache = _load_json(cache_path, {})

    for a, b in month_windows(since, until):
        if done_through and b <= done_through:
            continue
        log(f"{a:%B %Y}")
        papers, month_notes, answered, calls = collect(cfg, a, b, a, cache)
        if month_notes:
            # a gap here wouldn't be filled later, so stop and let the next run redo this month
            log("Stopping here so this month isn't left with a gap:")
            for n in month_notes:
                log(f"  {n}")
            log("Run the same command again later and it continues from this month.")
            _save_json(cache_path, cache)
            return 2
        fresh = [p for p in papers if p not in library and p not in owned
                 and p.key not in seen and norm_title(p.title) not in seen]
        scorer.score(fresh)
        hits = [p for p in fresh if p.topic]
        found.extend(hits)
        seen |= {p.key for p in hits} | {norm_title(p.title) for p in hits}
        log(f"  {len(papers)} found, {len(hits)} matched ({len(found)} so far)")
        if not args.dry_run:
            digest.save_papers(found_path, found)
            _save_json(cache_path, cache)
            state["catchup"] = {"since": since.isoformat(), "until": until.isoformat(), "done_through": b.isoformat()}
            _save_json(state_path, state)

    if args.dry_run:
        for topic, members in digest.group_by_topic(found, cfg.topics):
            log(f"{topic.name}: {len(members)}")
        log("Dry run, nothing saved.")
        return 0

    saved = 0
    if not args.no_pdf:
        chosen = pdfs.pick(found, cfg.catchup_pdfs_per_topic, lambda tid: scorer.pdf_threshold(cfg.topic(tid)))
        log(f"Downloading {len(chosen)} PDFs")
        saved = pdfs.save_all(chosen, cfg.pdf_dir, log=log)
    path = digest.write_catchup(since, until, found, cfg, notes)
    for p in found:
        library.add(p, date.today().isoformat())
    library.save()
    state["catchup"] = {**state.get("catchup", {}), "finished": True}
    _save_json(state_path, state)
    log(f"{len(found)} papers, {saved} PDFs. {path}")
    notify(cfg, f"Catch-up done: {len(found)} papers, {saved} PDFs")
    return 0


def cmd_check(cfg: Config, args) -> int:
    ok = True
    log(f"Config: {cfg.path} ({len(cfg.topics)} topics)")
    if ensure_output(cfg):
        log(f"Output folder: {cfg.output_dir} is writable")
    else:
        ok = False
    for folder in sorted({f for t in cfg.topics for f in t.seed_folders}):
        o = Owned([folder])
        log(f"Seed folder: {folder} ({len(o.names) + len(o.arxiv_ids)} PDFs)")
    model, warning = load_model(cfg.embedding_model, cfg.model_cache)
    log(f"Scoring: {warning or 'embedding model ' + cfg.embedding_model + ' loaded'}")
    today = date.today()
    quick = lambda url, **kw: http.get(url, retries=1, timeout=20)
    try:
        got = arxiv.fetch(["cs.GR"], [], today - timedelta(days=4), today, getter=quick)
        log(f"arXiv: answered ({len(got)} cs.GR papers in the last few days)")
    except Exception as err:
        ok = False
        log(f"arXiv: failed ({err})")
    try:
        got = openalex.fetch(today - timedelta(days=7), today, search='"virtual reality"', fields=cfg.openalex_fields,
                             email=cfg.openalex_email, api_key=cfg.openalex_api_key, max_pages=1,
                             getter=lambda url: http.get_json(url, retries=1, timeout=20))
        log(f"OpenAlex: answered ({len(got)} recent VR papers on the first page)")
    except Exception as err:
        ok = False
        log(f"OpenAlex: failed ({err})")
    log("All good." if ok else "Something needs fixing, see above.")
    return 0 if ok else 1


def cmd_sources(cfg: Config, args) -> int:
    cache_path = cfg.state_dir / "openalex_sources.json"
    cache = _load_json(cache_path, {})
    for t in cfg.topics:
        if not t.openalex_venues:
            continue
        openalex.resolve_sources(t.openalex_venues, cache, email=cfg.openalex_email, api_key=cfg.openalex_api_key)
        log(t.name)
        for name in t.openalex_venues:
            hit = cache.get(name)
            log(f"  {name}  ->  {hit[1] + ' (' + hit[0] + ')' if hit else 'not found'}")
    _save_json(cache_path, cache)
    return 0


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=DEFAULT_CONFIG, help="topics file (default: topics.toml next to the code)")
    parser = argparse.ArgumentParser(prog="papertracker", description="A daily list of new papers for your topics.", parents=[common])
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", parents=[common], help="fetch what's new since the last run (the daily job)")
    run.add_argument("--days", type=int, help="look back this many days instead")
    run.add_argument("--dry-run", action="store_true", help="print matches, save nothing")
    run.add_argument("--no-pdf", action="store_true", help="skip PDF downloads")
    run.add_argument("--explain", action="store_true", help="show top scores per topic, even below the threshold")
    catchup = sub.add_parser("catchup", parents=[common], help="one-time sweep since a date (default: `since` in the config)")
    catchup.add_argument("--since")
    catchup.add_argument("--until")
    catchup.add_argument("--no-pdf", action="store_true")
    catchup.add_argument("--dry-run", action="store_true")
    catchup.add_argument("--restart", action="store_true", help="ignore progress from an interrupted run")
    sub.add_parser("check", parents=[common], help="check folders, the model and the network")
    sub.add_parser("sources", parents=[common], help="show which OpenAlex venues your venue names matched")
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["run", *(argv if argv is not None else sys.argv[1:])])
    try:
        cfg = load(args.config)
    except ConfigError as err:
        log(f"Config problem: {err}")
        return 1
    handler = {"run": cmd_run, "catchup": cmd_catchup, "check": cmd_check, "sources": cmd_sources}[args.command]
    return handler(cfg, args)
