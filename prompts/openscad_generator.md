# Prompt: OpenSCAD generator

Reference prompt for generating OpenSCAD source for a single part. Not
invoked automatically in Phase 0/1 (CAD generation helpers land in Phase
2 — see `docs/roadmap.md`); this documents the intended prompt shape for
that future tooling and for manual use today.

---

You are generating OpenSCAD source for one part of an `ai-3d-factory`
project. You've been given: the part's name/role, its target measurements,
its material/tolerance requirements (from `config/tolerances.json`), and
the intended printer (`config/printers.json`).

Rules:

1. **Parametrize everything that could plausibly change** — dimensions,
   hole sizes, letter height, wall thickness — as named variables at the
   top of the file, not magic numbers inline.
2. **Use the correct tolerance category** from `config/tolerances.json` for
   any fit between this part and another (seam gap, letter pocket,
   connector, decorative inlay, sliding fit). Don't default to 0.10mm for
   everything.
3. **Keep units in millimeters**, matching this repo's convention (see
   `docs/architecture.md`).
4. **If this part is one of several colors/materials in an assembly**,
   model it at the shared origin the other parts use — don't re-center it
   for convenience. Document the origin convention in a comment at the top
   of the file.
5. **Export to `stl/` under the project**, e.g.
   `openscad -o projects/<slug>/stl/<part_name>.stl projects/<slug>/cad/<part_name>.scad`.
   This prompt does not itself run print/slice commands — export only.
6. After export, the next step is always `factory validate` and
   `factory render` on the resulting STL — don't declare the part done
   before that.

Do not generate geometry that reproduces a specific copyrighted
character, logo, or protected symbol (see `docs/licensing-policy.md`).
