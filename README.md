# conference_connector

Turn a conference's programme into a ranked list of people worth talking to, scored
against your own research or outreach goals.

Built out of a real run against ECCB 2026 (see `conference_connector/adapters/eccb2026/`,
kept in as a worked example). It is **not** a general "scrape any conference
automatically" tool -- every conference site is different, and the part that varies
(finding where the data actually lives, and parsing its particular markup) is
deliberately left to an adapter, written with the help of the `conference-scout` skill
and a recon pass, not inferred by magic.

## Quickstart checklist

Requirements: Python 3.11+, and an AI coding agent that supports skills (this was
built for/with Claude Code) if you want the `conference-scout` skill to drive adapter
writing and scoring for you. You can also run every command below by hand without an
agent.

- [ ] **Install the library**
  ```
  pip install git+https://github.com/scicrow/conference_connector.git
  ```
  (or `pip install -e /path/to/conference_connector` if you've cloned it locally and
  want to edit it)

- [ ] **Make a project directory** for this conference -- separate from this repo, one
  per conference/profile you scout
  ```
  mkdir my-conference-scout && cd my-conference-scout
  mkdir -p config data outputs
  ```

- [ ] **Get a config.yaml.** Preferred: open this project directory with an agent
  that has the `conference-scout` skill and tell it about the conference and what
  you're trying to get out of it -- it interviews you and writes `config/config.yaml`
  for you, including real keyword lists (not just topic names -- the vocabulary
  someone else might use for the same idea). Manual fallback:
  ```
  curl -o config/config.yaml https://raw.githubusercontent.com/scicrow/conference_connector/main/config/config.example.yaml
  ```
  and rewrite every field yourself -- who you are, your research threads and their
  keywords, and (only if your goal has a geography/institution angle) the `ranking`
  tier lists. This file is the one step that actually shapes your results; don't
  leave the placeholder text in.

- [ ] *(Optional)* **Add your own contact.** By default the tool identifies itself to
  scraped sites with just its own name and GitHub URL -- nothing personal required.
  If you'd rather a site admin be able to reach you directly, add `contact:
  "you@example.com"` (or any contact string) to `config.yaml`, or set
  `CONFERENCE_CONNECTOR_CONTACT` in your shell.

- [ ] **Recon the conference site before scraping anything**
  ```
  conference_connector recon https://your-conference.org/programme
  ```
  Read the output. Follow any iframe or programme-looking link it surfaces with
  another `recon` call. This is a deliberate, explicit checkpoint -- see
  [Recon: the checkpoint](#recon-the-checkpoint) below.

- [ ] **Get an adapter** -- either reuse `eccb2026` (if you're literally attending ECCB
  2026) or write a new one for your conference. Writing one is the part most worth
  doing with an agent driving the `conference-scout` skill; see
  `skills/conference-scout/references/adapter-authoring.md` either way.

- [ ] **Run the pipeline**
  ```
  conference_connector ingest <adapter-slug>
  conference_connector validate <adapter-slug>
  conference_connector prefilter
  # --- read data/interim/candidates_for_review.md, hand-write data/processed/item_scores.json ---
  conference_connector rank
  conference_connector render
  ```

- [ ] **Check `outputs/`** -- `shortlist.md` and `people.md` are the main deliverables;
  `items.csv` / `people.csv` are the same data for a spreadsheet.

- [ ] *(Optional)* **Generate a phone-friendly reference card** for the actual event:
  ```
  conference_connector card --pdf
  ```
  Produces `outputs/reference_card.html` (and `.pdf`, if a local Chrome/Chromium is
  found) -- a day-by-day schedule plus one card per Tier A/B person with their
  posters/talks (board/room/time) and, if `outputs/dossiers/*.md` exist, their
  hand-written hook/opener/ask. Designed to survive being AirDropped to a phone and
  read while walking around a poster hall.

The rest of this README explains *why* each piece works the way it does. If something
above didn't make sense, the answer is probably in one of the sections below.

## The pipeline, in full

```
conference_connector recon <url>        # look before you scrape -- explicit, separate, run first
conference_connector ingest <adapter>   # adapter -> data/interim/items.jsonl
conference_connector prefilter          # keyword filter -> data/interim/candidates_for_review.md
# --- read candidates_for_review.md, hand-write data/processed/item_scores.json ---
conference_connector validate <adapter> # sanity-check adapter output (coverage, mojibake, outliers)
conference_connector rank               # item_scores.json -> data/processed/people.json
conference_connector render             # -> outputs/{shortlist,people}.md, {items,people}.csv
conference_connector card [--tiers A,B] [--pdf]  # -> outputs/reference_card.{html,pdf}
```

`conference_connector` resolves `config/`, `data/`, and `outputs/` relative to your
current directory (override with `CONFERENCE_CONNECTOR_CONFIG_DIR` /
`CONFERENCE_CONNECTOR_DATA_DIR` / `CONFERENCE_CONNECTOR_OUTPUT_DIR`), so each
conference/profile combination is just a project directory with its own configs -- the
one you made in the Quickstart above.

There is no automated LLM-scoring step. Scoring hundreds of abstracts against a chat
subscription (not API credits) means a human or an LLM-in-the-loop session actually
reads them -- see `skills/conference-scout/references/close-reading.md`.

### The reference card

`card` is the last, optional stage -- it doesn't compute anything new, just assembles
what `rank` and (optionally) the outreach-writing step already produced into something
readable on a phone during the event itself: a day-by-day schedule across everyone
included, plus one card per person with their items' day/time/room/board.

It reads `outputs/dossiers/*.md` opportunistically -- if a project has hand-written
dossiers (see `skills/conference-scout/references/outreach-writing.md`), their hook/
opening-line/ask sections get pulled in verbatim (matched by loose keyword, not an
exact header, so different dossier-writing styles still work); anyone without one
still gets a card, using `item_scores.json`'s `why` for their best-scoring item as the
one-line summary instead. `config.yaml`'s `card.exclude_people` list is there for data
artifacts that resolve as a "person" but aren't one (a corporate author string like
"The Foo Consortium" showing up as a last author, for instance) -- there's no way to
detect that automatically, so check `outputs/people.md` for anything like it first.

PDF export shells out to a local Chrome/Chromium if it can find one (checked in the
usual install locations on macOS/Linux/Windows); without one, `card` still writes a
complete, usable HTML file and tells you to use your browser's Print > Save as PDF
instead of failing.

### Recon: the checkpoint

`recon` makes a handful of requests to one URL and reports what it finds (platform
fingerprints, embedded JSON, iframes to other hosts, well-known-path probes,
programme-looking links) -- then does nothing else. Nothing in this tool loops over a
site or writes an adapter without a person reading that report first and deciding how
to proceed. Real example, from building the ECCB 2026 adapter: the conference's own
schedule page turned out to be an empty shell around an `<iframe>` pointing at a
completely different domain -- `recon` catches exactly this, flagged as `<-- DIFFERENT
HOST`, in one call.

## Using an existing adapter vs. writing a new one

If your conference runs on a platform `conference_connector` already has an adapter
for, `conference_connector ingest <slug>` is the whole ingest step. Right now that's
just `eccb2026` (ECCB 2026 specifically -- not a generic ISCB-platform adapter; see the
module docstring for why).

For anything else: run `recon`, read
`skills/conference-scout/references/adapter-authoring.md`, and write a project-local
adapter against `conference_connector.adapters.base.Adapter`. Register it with
`conference_connector.adapters.register("your-slug", your_module)` before calling the
CLI (a one-line bootstrap script in your project works fine), or point the CLI at it
directly.

## Why a library *and* a skill

Everything downstream of "here is the item list" -- scoring mechanics, the person
pivot, geography weighting, rendering -- is arithmetic on structured data. That belongs
in code: reproducible, auditable, and the same every time you re-run it.

Everything upstream of that -- figuring out where a given conference's data lives,
writing the adapter, close-reading the shortlisted abstracts, writing outreach
strategy -- is judgement. That belongs to an agent working through the
`conference-scout` skill (see `skills/conference-scout/SKILL.md`), not to a script.

That includes `config.yaml` itself: you shouldn't have to hand-write YAML to describe
your own research interests, so the intended way to get one is to just tell an agent
about yourself and let the skill interview you and write the file. It's still a file
rather than a fresh prompt on every run, though -- `ingest`, `prefilter`, and `rank`
are separate commands, often run hours or days apart while you tune a weight, and
something has to hold the answer in between. A file also means you can inspect and
edit it directly to nudge the ranking, without a full re-interview each time.

## What this doesn't do

- No outreach. Nothing here sends email, DMs, or anything else on your behalf.
- No email-address harvesting. Adapters should not extract contact details even when a
  source exposes them; keep people's addresses out of every output.
- No auth-gated or attendee-only data. Public programme pages only.
- No headless browser by default. Most "JS-rendered" conference sites ship their data
  as embedded JSON or behind a plain REST endpoint once you look (that's what `recon`
  is for) -- Selenium/Playwright is a last resort, not a starting assumption.
