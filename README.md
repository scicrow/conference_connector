# conference_connector

Turn a conference's programme into a ranked list of people worth talking to, scored
against your own research or outreach goals.

Built out of a real run against ECCB 2026 (see `conference_connector/adapters/eccb2026/`, kept in
as a worked example). It is not a general "scrape any conference automatically" tool --
every conference site is different, and the part that varies (finding where the data
actually lives, and parsing its particular markup) is deliberately left to an
adapter, written with the help of the `conference-scout` skill and a recon pass, not
inferred by magic.

## Why a library *and* a skill

Everything downstream of "here is the item list" -- scoring mechanics, the person
pivot, geography weighting, rendering -- is arithmetic on structured data. That belongs
in code: reproducible, auditable, and the same every time you re-run it.

Everything upstream of that -- figuring out where a given conference's data lives,
writing the adapter, close-reading the shortlisted abstracts, writing outreach
strategy -- is judgement. That belongs to an agent working through the
`conference-scout` skill (see `skills/conference-scout/SKILL.md`), not to a script.

## The pipeline

```
conference_connector recon <url>        # look before you scrape -- explicit, separate, run first
conference_connector ingest <adapter>   # adapter -> data/interim/items.jsonl
conference_connector prefilter          # keyword filter -> data/interim/candidates_for_review.md
# --- read candidates_for_review.md, hand-write data/processed/item_scores.json ---
conference_connector validate <adapter> # sanity-check adapter output (coverage, mojibake, outliers)
conference_connector rank                # item_scores.json -> data/processed/people.json
conference_connector render              # -> outputs/{shortlist,people}.md, {items,people}.csv
```

`recon` is a deliberate checkpoint: it makes a handful of requests to one URL, reports
what it finds (platform fingerprints, embedded JSON, iframes to other hosts,
well-known-path probes, programme-looking links), and does nothing else. Nothing in
this tool loops over a site or writes an adapter without a person reading that report
first and deciding how to proceed.

There is no automated LLM-scoring step. Scoring hundreds of abstracts against a
subscription (not API credits) means a human or an LLM-in-the-loop session actually
reads them -- see `skills/conference-scout/references/close-reading.md`.

## Setup

```
pip install -e /path/to/conference_connector
export CONFERENCE_CONNECTOR_CONTACT="you@example.com"   # required before any network request
```

Then, from your *project* directory (not this repo):

```
mkdir -p config data outputs
cp /path/to/conference_connector/config/profile.example.yaml config/profile.yaml
cp /path/to/conference_connector/config/weights.example.yaml config/weights.yaml
# edit both for your own research profile and outreach goals
```

conference_connector resolves `config/`, `data/`, and `outputs/` relative to your current
directory (override with `CONFERENCE_CONNECTOR_CONFIG_DIR` / `CONFERENCE_CONNECTOR_DATA_DIR` /
`CONFERENCE_CONNECTOR_OUTPUT_DIR`), so each conference/profile combination is just a project
directory with its own configs.

## Using an existing adapter vs. writing a new one

If your conference runs on a platform conference_connector already has an adapter for, `conference_connector
ingest <slug>` is the whole ingest step. Right now that's just `eccb2026` (ECCB 2026
specifically -- not a generic ISCB-platform adapter; see the module docstring for why).

For anything else: run `conference_connector recon`, read `skills/conference-scout/references/
adapter-authoring.md`, and write a project-local adapter against
`conference_connector.adapters.base.Adapter`. Register it with
`conference_connector.adapters.register("your-slug", your_module)` before calling the CLI (a
one-line bootstrap script in your project works fine), or point the CLI at it directly.

## What this doesn't do

- No outreach. Nothing here sends email, DMs, or anything else on your behalf.
- No email-address harvesting. Adapters should not extract contact details even when a
  source exposes them; keep people's addresses out of every output.
- No auth-gated or attendee-only data. Public programme pages only.
- No headless browser by default. Most "JS-rendered" conference sites ship their data
  as embedded JSON or behind a plain REST endpoint once you look (that's what `recon`
  is for) -- Selenium/Playwright is a last resort, not a starting assumption.
