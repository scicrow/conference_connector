# Writing advice.md and per-person dossiers

Only relevant if the user wants outreach strategy written up, not just the ranked
list. `outputs/people.md` and `outputs/people.csv` already give a scored, tiered list
-- `advice.md` and dossiers are for turning that into something the user can actually
act on: how to approach, what to say, what not to do.

## Ground every claim in something real

Every suggested talking point, joint-project idea, or "hook" should trace back to a
specific scored item and, ideally, the verbatim `evidence` quote captured during the
close read (see `close-reading.md`). Don't invent plausible-sounding collaboration
ideas from a person's general reputation or field -- use what the actual abstract, talk,
or poster says. A dossier that could have been written from a Google search of the
person's name, without ever reading their submitted item, has failed at the one thing
this pipeline is for.

## Calibrate the ask to the tier

`conference_connector.pivot` tiers people by composite score (typically A/B/C, configurable via
`weights.yaml`'s `tiers` section). Tier meaning is whatever the project's weights
encode, but a common pattern:

- **Top tier** (highest composite, usually senior + accessible + on-strategy): worth
  a considered message before the conference even starts.
- **Middle tier**: better approached in person -- at a poster board, right after a
  talk, in a session's Q&A -- than cold-emailed. A real technical question in person is
  a stronger opener than a parallel cold email to the same person.
- **Everyone else**: worth recognising by name/face if encountered, not worth a
  special approach.

**Don't over-index on raw composite score alone.** The scoring formula rewards
accessibility (a presenting student is easy to approach) alongside seniority (a
chairing PI is not), so a highly-accessible junior person can outrank a senior PI
who's harder to reach but strategically more important. If someone matters for a
reason the score doesn't capture (they're explicitly named in the user's own
planning notes, they run the one lab that fits perfectly, etc.), write them a dossier
regardless of their raw tier -- just say why in the dossier.

## The "route via student presenter" pattern

A poster presenter or talk speaker who is a student/postdoc in a target group is often
the cheapest real introduction to that group's PI: they're standing at their poster,
happy to talk about their own work, and a good technical conversation with them is a
natural bridge to "you should talk to my supervisor about this." Don't skip this route
in favour of only targeting the most senior name in a cluster.

## What never belongs in these files

- **No email addresses**, even if a source made them available. Contact details are
  the user's to find themselves when they decide to reach out.
- **No sent-looking drafts.** If the user wants email drafts, put them in a clearly
  separate file, opening with an explicit, unambiguous statement that nothing has
  been sent and these are drafts for the user to send by hand (or not at all).
- **No mass-outreach suggestions.** Advice should push toward a small number of
  considered, specific approaches, not a wide blast. If the pipeline surfaced more
  strong candidates than the user could realistically approach individually, say so
  and help prioritise -- don't paper over it by recommending a form-letter approach.
- **Don't lead with a tangential credential** the user has (an old specialism, an
  unrelated background) unless it's genuinely relevant to a specific person's work --
  use it for a moment of legibility ("I also have a background in X"), not as the
  spine of the pitch.
