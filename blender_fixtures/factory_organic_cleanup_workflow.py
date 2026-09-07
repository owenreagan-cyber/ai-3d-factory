"""Factory-owned Blender script for `organic_cleanup_workflow` (Phase 49).

**This is the second (and, as of this phase, last) Blender Python script
this repo ever executes, and it is not arbitrary Python either - it is a
fixed, hand-written, repository-reviewed script with no user- or
project-supplied *code*, only two data arguments.** It is invoked
exclusively by `factory.blender_adapter.run_organic_cleanup_workflow()`,
as:

    blender --background --factory-startup -Y --offline-mode \
        --python-exit-code 1 \
        --python blender_fixtures/factory_organic_cleanup_workflow.py \
        -- <input_stl_path> <output_stl_path> <scale_factor>

Its only job, in this exact order:

    1. Import the given input STL (read-only against that file).
    2. Apply one explicit, uniform scale factor - never any other
       transform.
    3. Bake the scale into the mesh data (`transform_apply`) so the
       exported STL's own vertex coordinates reflect the real scaled
       geometry, never a transform an STL exporter would silently drop.
    4. Export the result to the given output path.

Nothing else. In particular, this script never repairs, remeshes,
decimates, smooths, retopologizes, or otherwise touches topology -
`factory.blender_gate`'s `organic_cleanup_workflow` scope is scale/
orientation adaptation only, per `docs/blender-adaptation.md`.

Safety contract (statically verified by
`tests/test_blender_adaptation_safety.py`, which parses this file's own
source/AST - not just this docstring), mirroring
`blender_fixtures/factory_qualification_fixture.py`'s Phase 45 contract
exactly:

- Imports only `bpy` and `sys` - both part of Blender's own embedded
  Python. No `subprocess`, `socket`, `urllib`, `requests`, `os.system`,
  or any other process/network-capable import.
- Reads no file of its own choosing and no environment variable; its only
  inputs are the two paths and the scale factor given after `--` on the
  command line.
- Writes to exactly one path: the output path it was given. Never a
  second file, never a delete, never a write to the input path.
- Installs no add-on, loads no external `.blend` file, contacts no
  network, imports no add-on module.

It deliberately lives **outside** `src/`, in the same
`blender_fixtures/` directory as the Phase 45 fixture script, for the
identical reason that script does: its `import bpy` line must never
collide with the repo-wide safety scan
(`tests/test_blender_gate.py::test_no_blender_execution_code_anywhere_in_src`)
that scans every `.py` file under `src/` for `import bpy`/`from bpy` and
expects to find none. See `docs/blender-adaptation.md`.
"""

import sys

import bpy


def _args() -> tuple[str, str, float]:
    if "--" not in sys.argv:
        raise SystemExit("factory_organic_cleanup_workflow: missing '--' separator before its arguments")
    after = sys.argv[sys.argv.index("--") + 1 :]
    if len(after) != 3:
        raise SystemExit(
            "factory_organic_cleanup_workflow: expected exactly 3 arguments after '--' "
            "(input_stl_path, output_stl_path, scale_factor), got "
            f"{len(after)}"
        )
    input_path, output_path, scale_factor_text = after
    try:
        scale_factor = float(scale_factor_text)
    except ValueError:
        raise SystemExit(f"factory_organic_cleanup_workflow: scale_factor is not a number: {scale_factor_text!r}")
    if scale_factor <= 0:
        raise SystemExit(f"factory_organic_cleanup_workflow: scale_factor must be positive, got {scale_factor}")
    return input_path, output_path, scale_factor


def main() -> None:
    input_path, output_path, scale_factor = _args()

    # Start from a bare in-memory scene - never the user's actual startup
    # file/scene state (also true regardless, since --factory-startup is
    # always passed by factory.blender_adapter; this is defense in depth).
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Step 1: import the given input STL - read-only against that file.
    bpy.ops.wm.stl_import(filepath=input_path)

    imported_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not imported_objects:
        raise SystemExit(f"factory_organic_cleanup_workflow: no mesh object was imported from {input_path!r}")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in imported_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = imported_objects[0]

    # Step 2: apply one explicit, uniform scale factor - never anisotropic
    # (no separate x/y/z factors), never any other transform (no rotation,
    # no translation beyond whatever the import itself produced).
    for obj in imported_objects:
        obj.scale = (scale_factor, scale_factor, scale_factor)

    # Step 3: bake the scale into the mesh data - never left as a
    # transform an STL exporter would silently drop (STL has no transform
    # concept of its own; only raw triangle vertex coordinates).
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Step 4: export the result to the given output path - the only write
    # this script ever performs.
    bpy.ops.wm.stl_export(filepath=output_path, export_selected_objects=True, global_scale=1.0)
    print(f"FACTORY_ORGANIC_CLEANUP_EXPORT_OK {output_path} scale_factor={scale_factor}")


main()
