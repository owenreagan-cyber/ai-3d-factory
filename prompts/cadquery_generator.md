# Prompt: CadQuery generator

Reference prompt for generating CadQuery source for a single mechanical
part. Not invoked automatically in Phase 0/1 (CAD generation helpers land
in Phase 2 — see `docs/roadmap.md`); this documents the intended prompt
shape for that future tooling and for manual use today.

---

You are generating CadQuery (Python) source for one mechanical part of an
`ai-3d-factory` project. Reach for CadQuery over OpenSCAD when the part
needs fillets, chamfers, or exact engineering fits that are awkward to
express in OpenSCAD's CSG model (see `docs/tool-routing.md`).

Rules:

1. **Parametrize dimensions as named variables/function arguments**, not
   inline literals, so the part can be re-generated at different sizes.
2. **Use the correct tolerance category** from `config/tolerances.json` for
   any mating fit (connector clearance, sliding fit, etc.) — state which
   category you used and why.
3. **Keep units in millimeters.**
4. **If this part must align with other parts in a multi-color assembly**,
   build it at the shared origin those other parts use, and document the
   convention in a comment.
5. **Export to `stl/` under the project** (e.g. via
   `cq.exporters.export(result, "projects/<slug>/stl/<part_name>.stl")`).
   This prompt does not run print/slice commands — export only.
6. After export, run `factory validate` and `factory render` on the
   resulting STL before considering the part done.

Do not generate geometry that reproduces a specific copyrighted character,
logo, or protected symbol (see `docs/licensing-policy.md`).
