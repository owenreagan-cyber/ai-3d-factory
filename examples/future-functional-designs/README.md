# future-functional-designs/

Roadmap / spec examples only, mirroring `../future-organic-models/`'s
concept-only pattern for the **functional / mechanical custom design
track** described in `../../docs/design-quality-standard.md`. **Nothing
under this directory is a working project, a generated model, or a
printable part.**

## Why these are concept-only today

`ai-3d-factory` can already generate parametric CAD source for simple
functional shapes (`docs/cad-backends.md`: OpenSCAD, optionally
CadQuery), but the *design* considerations `docs/design-quality-standard.md`
requires for a real functional/mechanical object - flex/tension planning,
material tradeoffs, layer orientation, fatigue risk, prototype test
strips, grip-force tuning, an iteration loop - aren't a scoped, working
part of this repo yet. These placeholders exist so the shape of that
future work is on record.

## Why `concept_brief.json`, not `brief.json`

Same reasoning as `../future-organic-models/README.md`: every command
that treats a directory as a real project looks for `brief.json`. These
concept-only subdirectories intentionally do **not** have one, so those
commands correctly report `brief_missing` / `needs_brief` instead of
implying there's a real, progressable project here.

## What's here

- `chip-bag-clip-study/` - the canonical worked example from
  `../../docs/design-quality-standard.md`'s functional/mechanical track:
  a chip bag clip, planned (not built) with flex/tension, material, and
  iteration considerations from the start.

None of these contain STL files, renders, or any generated mesh asset.
None of these are `human_approved` or `print_ready`, and none of them are
expected to pass `factory review-gate`. Functional objects under tension
or repeated stress must be treated as prototypes until physically tested
by a human - see `../../docs/design-quality-standard.md`.
