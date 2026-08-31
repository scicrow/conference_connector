# Fixtures

Save 2-3 raw pages here while writing a new adapter (`fixtures/<conference-slug>/*.html`
or `.json`) and parse against them instead of the live site. This keeps adapter
iteration fast, offline, and polite -- you should not be re-fetching a conference's
server every time you tweak a regex.

Nothing here is loaded automatically; point your adapter's tests or a throwaway script
at these files directly while developing, per
`conference_connector/skills/conference-scout/references/adapter-authoring.md`.
