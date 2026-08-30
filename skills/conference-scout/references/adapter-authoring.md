# Writing an adapter

An adapter is a Python module with a `SLUG` and `fetch_all(refresh=False) ->
list[Item]` (see `conference_connector.adapters.base.Adapter`). Everything below is what actually
went wrong building the one adapter that exists so far (ECCB 2026, four sources), kept
concrete on purpose -- generic advice like "test your parser" doesn't transfer, a
catalogue of specific failure shapes does.

## Discovery heuristics (what to try before writing any parsing code)

1. **The conference's own domain is often just marketing.** The actual data --
   abstracts, schedules, author lists -- frequently lives with the academic society
   running it, a submission/programme platform, or a publisher, not on
   `theconference2027.org` itself. If the obvious page looks thin or JS-only, ask
   "who actually runs the backend for this?" before reaching for a browser.

2. **Iframes are the tell.** At ECCB 2026, `eccb2026.org/schedule/parallel-sessions`
   rendered no talks at all -- it was an `<iframe>` pointed at
   `transition.iscb.org`, a completely different domain with completely different
   markup. `conference_connector recon` flags iframes to a different host specifically because
   this is exactly the kind of thing that's invisible if you only look at the visible
   page and easy to miss if you're not looking for it.

3. **Last year's site is a Rosetta stone.** If this year's site is unfinished, rushed,
   or JS-hydrated with nothing to grab, the previous year's instance of the same
   conference (or the same organising society's other conferences) often reveals the
   platform and URL grammar while the current site is still in flux.

4. **"Blocked" sometimes means "you tried the fancy endpoint."** ECCB 2026's poster
   browser used FacetWP for filtering; its AJAX pagination endpoint returned 401, and
   the documented facetwp fetch endpoint returned 401 too. The plain underlying
   WordPress REST collection (`/wp-json/wp/v2/poster?per_page=100&page=N`) had no such
   restriction and served every record. Before concluding a site's data is
   inaccessible, try the boring, undecorated endpoint underneath the fancy UI.

5. **ID/code grammars often encode structure for free.** ECCB's poster board IDs
   (`A-G.01`, `C-S.B.12`) decoded to session (hence day/time) and track without a
   second request. Cluster a sample of observed IDs before assuming you know their
   shape -- a naive single-letter-track regex silently dropped ~300 posters because
   some track codes were multi-letter (`S.B`, `G.C`, `ELIXIR`).

## The bug catalogue

Every one of these ran without raising an exception. All returned data. All returned
*wrong or incomplete* data, silently. That's the pattern to defend against -- "it ran"
is not "it worked."

### 1. A filter/regex silently drops a whole category

**What happened:** the board-ID regex `[A-Z]-[A-Z]\.\d+` matched single-letter track
codes only. Multi-letter codes (`S.B` for SysBio, `G.C` for GenCompBio, `ELIXIR`)
never matched, and posters using them were silently excluded wherever the code
gated inclusion. ~300 of ~850 posters vanished with no error.

**How it's caught:** count structural markers in the raw page independently of your
parse logic (e.g. `html.count("<div class='well well-sm'>")`) and compare to how many
items your parser actually returned. A mismatch means your extraction logic, not the
source data, is the problem. This is exactly what `conference_connector.validate`'s
`expected_min_total` check and the field-presence-outlier check are for -- but the
raw marker count is a check you should do by hand too, once, while writing the parser.

### 2. One structural block actually contains N items, not 1

**What happened:** each `<div class='row schedulerow'>` (one one-hour time slot) held
three separate talk blocks back-to-back. The first-pass parser searched each row for
one title and stopped, returning 31 of 91 real talks.

**How it's caught:** when your per-item count looks suspiciously round or suspiciously
low relative to the conference's stated scale (a schedule grid, a stated talk count),
open one raw block in a text editor and count by eye how many logical items are
actually inside it. Don't trust "the loop ran once per div" to mean "one item per div."

### 3. A naive text split breaks on nested structure

**What happened:** organiser strings like "Cristian Iperi (USZ Universitätsspital
Zürich, Switzerland), Jessica Gliozzo (..., Milan, Italy)" were split on every comma,
shredding each parenthetical affiliation into its own bogus "name" fragment.

**How it's caught:** a name-sanity check -- does an extracted "name" contain `(`, `)`,
a URL, or an implausible run of digits? `conference_connector.validate`'s suspicious-name check
does exactly this. The fix was a depth-aware splitter (track paren nesting, only split
at depth 0) -- see `_split_top_level` in `conference_connector/adapters/eccb2026/eccb_workshops.py`
for a working example to copy.

### 4. A markup variant breaks a fixed-order/fixed-label parser

**What happened:** 16 of 18 tutorial/workshop entries used
`Organized by: ... Scientific area: ... Overview: ...` in that order. One entry was
pasted from Word (wrapped every few words in `data-ccp-*` spans, breaking any regex
assuming clean text between labels); another used `Abstract:` instead of `Overview:`.
A parser hard-coded to that field order and those exact labels returned empty fields
for exactly those two entries.

**How it's caught:** field-presence outlier detection -- if `overview` is present in
16/18 items of a kind but missing in the other 2, that's not 2 items lacking an
overview, it's almost certainly 2 items using different markup for the same content.
`conference_connector.validate` flags any field present in 50-95% of one kind for exactly this
reason. The fix was to stop assuming a fixed field order/label set and instead find
every labelled-field marker in the block, sort by position, and take each field's
text as "everything up to the next marker" -- order- and subset-agnostic. See
`_FIELD_MARKER_RE` in the same file.

## General principle

**An outlier in field presence is almost never a real gap in the source data -- it's
almost always your parser hitting a markup variant it doesn't handle.** If 95% of
items in a kind have a field and 5% don't, go read those 5% in the raw HTML before
concluding the source just didn't provide it.

## Mojibake

Run `conference_connector.html_utils.clean_text()` (wraps `ftfy.fix_text`) on every extracted
string, unconditionally, before anything else touches it -- including before using a
name as a dictionary key or dedup criterion. At ECCB 2026, ~75% of the source pages
were double-encoded UTF-8 (`ZoltÃ¡n` for `Zoltán`, `Î²-lactamase` for `β-lactamase`).
Corrupted names silently fracture person-resolution downstream (the same person
becomes two different dict keys) with no error anywhere. `conference_connector.validate` scans
for common mojibake byte signatures, but the real fix is running `clean_text`
unconditionally, not detecting the damage after the fact.

## Author/affiliation strings

`conference_connector.html_utils.parse_author_string` handles one common convention: `"Name,
Affiliation part 1, Affiliation part 2, ..., Country[, Country]"`, including a
trailing duplicated country (a real rendering quirk seen on ISCB pages). This is a
common shape, not a universal one -- if a conference formats author blocks
differently (e.g. structured JSON with separate name/affiliation/country fields, which
is actually easier), write a project-local parser instead of forcing the string
convention to fit.
