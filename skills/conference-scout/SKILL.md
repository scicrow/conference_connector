---
name: conference-scout
description: Turn a conference's programme into a ranked, scored list of people worth talking to, using the conference_connector library for scraping/scoring mechanics and this skill for everything that needs judgement -- finding where a conference's data actually lives, writing an adapter for it, close-reading candidate abstracts, and writing outreach strategy. Use when a user wants to prepare for a conference by identifying relevant talks/posters and the people behind them, or when they name a specific conference and a goal (find a collaborator, find a host lab, scout the competition, map a subfield).
---

# conference-scout

You are driving `conference_connector` (a separate installed library: `recon` / `ingest` /
`prefilter` / `validate` / `rank` / `render`) through a project directory that holds
one user's configs, cached data, and outputs for one conference. Everything
downstream of the item list is arithmetic the library already does correctly -- don't
re-derive it. Everything upstream of that is judgement: this file is about the parts
where you have to look at real pages, real text, and real names and decide something.

## 0. Before anything else: is there a project directory?

Look for `config/config.yaml` in the current directory. If missing, this is a new
project. **Do not hand the user a blank YAML file and ask them to fill it in --
interview them and write it yourself.** That's the whole point of driving this
through a skill rather than a README: the user describes their work and goals in
conversation, you translate that into the structured file the library needs.

1. Interview the user. You need: what conference, what URL, what they're trying to
   get out of it (find a collaborator? a host lab? scout competitors? just triage a
   big programme?), and enough about their own work to write real keyword lists --
   not just a topic name, but the vocabulary someone else might use for the same idea
   with different words. Weak, generic keywords are the single most common way a good
   candidate silently never gets read.
2. Copy `config/config.example.yaml` from the conference_connector install to this
   project's `config/config.yaml`, then rewrite every field for this user from what
   they told you -- don't leave placeholder text in the real config.
3. If the goal has a geography/institution angle (target host, funding-scheme
   eligibility, home turf), fill in the tier lists under `ranking` in `config.yaml`.
   If it doesn't, say so explicitly and leave every tier list empty -- don't invent a
   geographic angle the user didn't ask for.
4. A network contact is optional, not required -- by default the tool identifies
   itself to scraped sites with just this project's name and GitHub URL. Only set
   `contact:` in `config.yaml` (or `export CONFERENCE_CONNECTOR_CONTACT`) if the user
   wants to add their own on top of that.

If a project directory already exists, read its config and treat this as continuing
or re-running an existing scout, not starting over.

## 1. Recon -- the checkpoint, not a formality

**Never write an adapter or run bulk ingest without running `conference_connector recon <url>`
first and showing the user (or at least stating in your own reasoning) what it
found.** This is a hard rule, not a suggestion: recon is a separate, explicit command
precisely so scraping never starts on a guess.

Run it against the conference's main programme/schedule page first. Read the report:

- **Platform fingerprint hit?** Check `references/adapter-authoring.md` for whether
  conference_connector (or your own knowledge) has a known pattern for that platform. A match
  can mean zero new parsing code.
- **Iframes to a different host?** Recon on that URL next. This is what happened with
  ECCB 2026 -- the conference's own site was a shell around a different platform.
- **Embedded data markers present?** The content may already be sitting in the HTML
  as JSON. No browser automation needed; find the blob and parse it directly.
- **`likely_client_rendered: true`?** Don't reach for Selenium/Playwright as step one.
  Check `well_known_probes` and embedded data first -- most of the time the real data
  is one plain HTTP request away.
- **Programme-looking links?** Recon the promising ones too. A conference's data is
  often split across 3-6 pages/endpoints (schedule, posters, keynotes, workshops as
  separate sources), not one.

Budget: a handful of recon calls (one per real lead), not a crawl. If recon comes back
with nothing usable after a few tries, stop and tell the user rather than guessing at
a scraper for a site that may need auth, a PDF export, or a manual list instead.

## 2. Writing the adapter

Read `references/adapter-authoring.md` before writing any parsing code -- it has the
bug catalogue from the one real adapter built so far, and every one of those bugs was
silent (ran fine, returned wrong/incomplete data). The checks that catch them are in
`conference_connector.validate`; use them as you go, not just at the end.

Work fixture-first: save a couple of real pages to `fixtures/<slug>/`, write against
those, run `conference_connector.validate.validate()` on the parsed output, only then point the
adapter at the live site for a full ingest.

Write the adapter as a project-local Python module (not inside the conference_connector install)
implementing `conference_connector.adapters.base.Adapter` (a `SLUG` and `fetch_all(refresh)`).
Register it with `conference_connector.adapters.register(slug, module)`.

## 3. Ingest and validate

```
conference_connector ingest <slug>
conference_connector validate <slug>
```

Read the validate output. An issue about a field present in 50-95% of one kind is the
single highest-signal thing it reports -- that pattern caught a real markup-variant bug
before. Don't dismiss it without actually looking at the flagged items.

Sanity-check the raw kind counts against what the site itself implies (a schedule
grid, a stated poster count, page counts) before moving on.

## 4. Prefilter, then close-read

```
conference_connector prefilter
```

This writes `data/interim/candidates_for_review.md`. Read `references/close-reading.md`
before scoring -- it covers how to read a large candidate file in chunks, what
`item_scores.json` needs, and the "items are evidence, people are the deliverable"
framing that makes the later person-ranking make sense. Do the close read yourself
(you're the "LLM-in-the-loop" this pipeline is designed around) rather than trying to
script it -- that's the point of not calling an API here.

Write `data/processed/item_scores.json` by hand from what you read.

## 5. Rank and render

```
conference_connector rank
conference_connector render
```

Check the output counts against what you expect (tier sizes, total shortlist size)
before treating it as final. If a tier looks empty or absurdly large, the `ranking`
weights in `config.yaml` probably need adjusting -- that's expected iteration, not a
bug.

## 6. Outreach strategy (advice.md + dossiers)

If the user wants strategy written up (not just the ranked list), read
`references/outreach-writing.md` before drafting `advice.md` or per-person dossiers.
The core discipline there: ground every claim in a real scored item and a real quote,
never write anything that could be mistaken for a ready-to-send message unless the
user explicitly wants drafts, and never include email addresses in any output.

## Hard constraints, always

- No outreach performed by you, ever, regardless of what the user's goal is. Draft
  material is fine (if asked for) but must be clearly marked unsent.
- No email addresses in any output file, even when a source exposes them.
- No touching authenticated/attendee-only endpoints.
- Be a polite client: cache everything, throttle requests, identify honestly (the
  default User-Agent already does this; never override it with something generic
  enough to look anonymous).
- Respect `robots.txt` for the sites you scrape -- recon reports it; read it before
  deciding to proceed with an adapter for that host.
