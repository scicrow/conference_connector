# The close-reading pass

`conference_connector prefilter` narrows the full item pool down to a candidate set worth
reading, and writes it to `data/interim/candidates_for_review.md`. Nothing scores
those candidates automatically -- reading them and writing
`data/processed/item_scores.json` is the one stage in this pipeline that's explicitly
not scripted. That's a design choice, not a gap: it assumes you're working from a chat
subscription rather than metered API credits, so scoring hundreds of abstracts means
something (a human, or an LLM-in-the-loop session like this one) actually reads them,
not an unattended batch job.

## Why items aren't the final deliverable

Score items first, but don't stop there. Ranking items directly and listing their
presenters surfaces the wrong people for most outreach goals: presenters at a
poster-heavy conference are disproportionately students, and the person worth
contacting -- a PI who could host a visit, a group leader who could collaborate -- is
often a *last author* or *session chair* who may not present anything themselves and
so never appears in an item-ranked list at all. `conference_connector.pivot` exists to fix this:
items are evidence, people are the deliverable. Score the items; the pivot to people
happens automatically from `item_scores.json` in the `rank` step.

## Reading a large file in chunks

`candidates_for_review.md` can be large (500KB+ for a few hundred candidates isn't
unusual). Read it in chunks of roughly 250-300 lines at a time rather than trying to
read it all at once -- large single reads can exceed a tool's per-call output limit,
and you'll waste a call re-reading a truncated chunk. There's no need to hold the
whole file in memory at once; score each item as you reach it rather than reading
everything first and scoring in a second pass.

## What to write for each candidate

`item_scores.json` is a JSON array; each entry needs:

```json
{
  "item_id": "poster:C-G.35",
  "topic_fit": 4,
  "method_overlap": 4,
  "collab_potential": 3,
  "thread_scores": {"thread_id": 4},
  "evidence": "a verbatim quote from the abstract that justifies the score",
  "why": "one or two plain-language sentences a future reader can trust without re-reading the abstract"
}
```

- **topic_fit / method_overlap / collab_potential** (0-5 each): three angles on the
  same question -- does this matter to the user's stated goals? `conference_connector.pivot`
  averages these into the item's contribution to a person's relevance score, so don't
  conflate them into one number yourself; score each independently.
- **evidence**: an actual quote, not a paraphrase. This is what makes `shortlist.md`
  and any dossiers trustworthy later -- a claim with a verbatim quote next to it can
  be checked; a claim without one has to be taken on faith.
- **why**: written for someone who will never read the original abstract. Don't
  reference "this item" or assume context; state the connection plainly.

## Calibration, not just filtering

Don't just decide yes/no -- distinguish *why* something matters. A cluster of several
independently-scored items pointing at the same lab, method, or institution is a
stronger signal than any single high score in isolation (it suggests an active,
identifiable group, not a one-off). Note that pattern in `why` when you see it; it
carries into how confidently the person-level output can be presented later.

Only score what you'd actually stand behind. If the prefilter's keyword hit looks
like a false positive on a close read (vocabulary overlap without real relevance),
leave it out of `item_scores.json` rather than scoring it low -- low-scored items
still show up in `shortlist.md`; simply not scoring them is how you exclude them.

## Watch for the user's own work

If the user is themselves a presenter, author, or organiser at this conference (their
own poster, talk, or session), their own item(s) will appear in the candidate pool.
Exclude their own submissions from any outreach-target list, but flag them separately
if writing `advice.md` -- their own poster or talk abstract is a ready-made pitch they
can reuse when introducing themselves to people on the ranked list.
