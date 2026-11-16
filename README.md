# PaperTracker

Every morning PaperTracker checks arXiv and OpenAlex for new papers on your topics, keeps the ones that are close to your research, and writes them to a dated markdown list. The strongest match or two in each topic also gets its PDF saved. A one-time catch-up sweep goes back as far as you like (mine starts at January 2025).

Relevance is decided on your machine. Each title and abstract is embedded with a small model (bge-small through fastembed, about 65 MB) and compared with a paragraph you write for each topic, and with the titles of papers you already keep. No API key or language model is needed to run it.

## What it writes

```
~/Desktop/papertracker/
  daily/2026-11-17.md      that day's matches, grouped by topic, with abstracts and links
  daily/2026-11-17.json    the same list, for scripts
  pdfs/<topic>/2026-11/    PDFs of the strongest matches, named "2026 Smith - Title.pdf"
  catch-up/                the long list from the catch-up sweep
  library.csv              everything kept so far, so nothing shows up twice
  state/                   bookkeeping
```

## Setup (macOS)

```bash
git clone https://github.com/maryamkameli/PaperTracker.git
cd PaperTracker
scripts/setup.sh              # makes .venv, installs fastembed, copies topics.example.toml to topics.toml
```

Edit `topics.toml` (see below), then try it without saving anything:

```bash
.venv/bin/python -m papertracker check
.venv/bin/python -m papertracker run --dry-run --explain --days 7
```

`--explain` prints the top scores for every topic, including papers just under the threshold, which is the easiest way to tune thresholds. When the lists look right, schedule it:

```bash
scripts/install_schedule.sh          # every day at 6:15; pass "7 5" for 7:05
```

The script uses launchd. If the Mac is asleep at that time, the job runs as soon as it wakes. If your output folder is on the Desktop or in Documents, macOS keeps background jobs out of it until you add Python to **System Settings > Privacy & Security > Full Disk Access**. The script prints the exact path to add. `scripts/uninstall_schedule.sh` removes the schedule.

Python 3.9 or newer works. If you have [uv](https://docs.astral.sh/uv/), setup uses it.

## Topics

`topics.toml` is gitignored, so your topics stay on your machine. Each topic needs:

- `statement`: a paragraph about the work you want to follow. Every abstract is compared with it, so write it the way you'd describe the area to a colleague.
- a source: `arxiv_categories` (optionally narrowed with `arxiv_terms`), an `openalex_search` (boolean search over titles and abstracts), or `openalex_venues` (whole journals or proceedings, by name or OpenAlex id).
- `threshold`: how close a paper has to be. Around 0.70 is a reasonable start for bge-small.

Optional: `seed_folders` (folders of PDFs you already keep; their file names act as examples, and those papers are never fetched again), `seed_titles`, and `openalex_fields` when a topic's keyword search should look outside the global fields (a medical digital-twin topic wants Engineering and Medicine, for example).

Every paper that's fetched is scored against every topic, so a venue only needs to be listed under one of them.

## The catch-up

```bash
.venv/bin/python -m papertracker catchup                 # from `since` in topics.toml to today
.venv/bin/python -m papertracker catchup --since 2025-06-01 --no-pdf
```

It goes month by month and saves progress after each one. If it stops (the laptop sleeps, a source is down, OpenAlex's daily credits run out), run the same command again and it picks up where it left off. It downloads PDFs only for the strongest `catchup_pdfs_per_topic` papers in each topic.

## Being polite to the sources

- arXiv: one request every three seconds, as their API guide asks. Papers appear on arXiv a day or two after submission, so each daily run looks a week back and `library.csv` filters out what you've already seen.
- OpenAlex: a short pause between calls. Anonymous use gets 1000 credits a day and a keyword search page costs 10, so a daily run uses about 50. A free key from openalex.org (`openalex_api_key`) helps if you run long catch-ups.
- PDFs come only from open-access links: arXiv, or OpenAlex's best open-access location.

## Tests

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest
```

The tests use saved responses and a fake embedding model, so they run offline in under a second.

## Credit

The idea of comparing abstracts with a paragraph per topic comes from [DanhuaZhang/PaperTracker](https://github.com/DanhuaZhang/PaperTracker), which also writes summaries and works with Zotero. This is a separate, smaller implementation built around a local folder of daily lists and PDFs, plus the catch-up sweep.

MIT license.
