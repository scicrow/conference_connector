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

- [ ] **Set a contact string** -- required before any network request
  ```
  export CONFERENCE_CONNECTOR_CONTACT="you@example.com"
  ```
  This goes *only* into the `User-Agent` header of requests to the conference sites
  you scrape (never anywhere else, never to this project) -- standard scraping
  etiquette, so a site admin who notices unusual traffic has someone to contact
  instead of an anonymous bot. It doesn't need to be a personal email; a project
  alias or a lab website URL works just as well.

- [ ] **Make a project directory** for this conference -- separate from this repo, one
  per conference/profile you scout
  ```
  mkdir my-conference-scout && cd my-conference-scout
  mkdir -p config data outputs
  ```

- [ ] **Copy the example configs in and rewrite them for yourself** -- this is the step
  that actually shapes your results, don't skip rewriting the placeholder text
  ```
  curl -o config/profile.yaml  https://raw.githubusercontent.com/scicrow/conference_connector/main/config/profile.example.yaml
  curl -o config/weights.yaml  https://raw.githubusercontent.com/scicrow/conference_connector/main/config/weights.example.yaml
  ```
  Edit `profile.yaml`: who you are, what research threads you care about, and real
  keyword lists for each (see the comments in the file). Edit `weights.yaml` only if
  your goal has a geography/institution angle (a target host, a funding scheme's
  eligible countries) or you want to change how roles map to "how easy is this person
  to approach."

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
```

`conference_connector` resolves `config/`, `data/`, and `outputs/` relative to your
current directory (override with `CONFERENCE_CONNECTOR_CONFIG_DIR` /
`CONFERENCE_CONNECTOR_DATA_DIR` / `CONFERENCE_CONNECTOR_OUTPUT_DIR`), so each
conference/profile combination is just a project directory with its own configs -- the
one you made in the Quickstart above.

There is no automated LLM-scoring step. Scoring hundreds of abstracts against a chat
subscription (not API credits) means a human or an LLM-in-the-loop session actually
reads them -- see `skills/conference-scout/references/close-reading.md`.

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

## What this doesn't do

- No outreach. Nothing here sends email, DMs, or anything else on your behalf.
- No email-address harvesting. Adapters should not extract contact details even when a
  source exposes them; keep people's addresses out of every output.
- No auth-gated or attendee-only data. Public programme pages only.
- No headless browser by default. Most "JS-rendered" conference sites ship their data
  as embedded JSON or behind a plain REST endpoint once you look (that's what `recon`
  is for) -- Selenium/Playwright is a last resort, not a starting assumption.
