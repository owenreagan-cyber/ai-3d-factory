# Licensing policy

## Default: original designs

Every project's geometry should default to an original design, authored
locally (by hand, by parametric CAD script, or — in a future phase, with
explicit approval — by a generative tool). Record this in each part's
`source` and `license` fields in `part_manifest.json`, e.g.
`"source": "original design"`, `"license": "original"`.

## Anime-inspired is okay; anime/franchise reproductions are not

Taking general stylistic inspiration from anime, games, or other media
(proportions, an aesthetic, a color scheme) is fine. What is not okay,
without the user providing a licensed/open asset to work from:

- Direct reproductions of anime/franchise characters, logos, marks, or
  symbols.
- Any other copyrighted or trademarked character, logo, or protected
  design.

If a request would require reproducing a specific franchise character or
logo, stop and ask — don't approximate it as "close enough to be
original."

## If the user provides a licensed or open asset

Record its actual source and license in the relevant part's `source` and
`license` fields (e.g. `"source": "user-provided, https://...", "license":
"CC-BY-4.0"`), instead of `"original design"`. Don't guess at a license —
ask if it's unclear.

## Why this is enforced here, not just in prompts

`config/agent_policy.json` lists `copyrighted_franchise_assets` as a
blocked action alongside the cloud/print safety gates, and
`part_manifest.schema.json` requires a `source`/`license` field per part so
this decision is recorded, not just assumed, for every part that ships
through this pipeline.
