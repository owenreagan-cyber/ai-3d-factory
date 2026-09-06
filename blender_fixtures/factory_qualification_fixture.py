"""Factory-owned Blender qualification fixture script (Phase 45).

**This is the only Blender Python this repo ever executes, and it is not
arbitrary Python - it is a fixed, hand-written, repository-reviewed
script with no user- or project-supplied input.** It is invoked exactly
once per qualification run, exclusively by `factory.blender_adapter`, as:

    blender --background --factory-startup -Y --offline-mode \
        --python-exit-code 1 \
        --python blender_fixtures/factory_qualification_fixture.py \
        -- <absolute_output_stl_path>

Its only job: build one fixed, deterministic organic-shaped placeholder
object (a UV sphere - never any actual project's design, never a
downloaded or generated asset) and export it to the single path given as
the sole positional argument after `--`. Nothing else.

Safety contract (statically verified by
`tests/test_blender_adapter_safety.py`, which parses this file's own
source/AST - not just this docstring):

- Imports only `bpy` and `sys` - both part of Blender's own embedded
  Python. No `subprocess`, `socket`, `urllib`, `requests`, `os.system`,
  or any other process/network-capable import.
- Reads no file of its own choosing and no environment variable; its only
  input is the single output path `factory.blender_adapter` passes after
  `--` on the command line.
- Writes to exactly one path: the output path it was given. It never
  constructs any other path, never writes a second file, never deletes
  anything.
- Installs no add-on, loads no external `.blend` file, contacts no
  network, imports no add-on module.

See `docs/blender-adapter.md` for the full Phase 45 safety policy this
script exists to satisfy the "Python execution policy" section of.
"""

import sys

import bpy


def _output_path() -> str:
    if "--" not in sys.argv:
        raise SystemExit("factory_qualification_fixture: missing '--' separator before output path")
    after = sys.argv[sys.argv.index("--") + 1 :]
    if not after:
        raise SystemExit("factory_qualification_fixture: no output path given after '--'")
    return after[0]


def main() -> None:
    output_path = _output_path()

    # Start from a bare in-memory scene - never the user's actual startup
    # file/scene state (also true regardless, since --factory-startup is
    # always passed by factory.blender_adapter; this is defense in depth).
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # A fixed, deterministic placeholder shape. Not a product, not a user
    # design, not a copyrighted character - it exists only to prove the
    # adapter's fixture -> Blender -> STL -> Factory validation pipeline.
    bpy.ops.mesh.primitive_uv_sphere_add(radius=5.0, segments=16, ring_count=8, location=(0.0, 0.0, 0.0))
    fixture_object = bpy.context.active_object
    fixture_object.name = "factory_qualification_fixture"

    bpy.ops.object.select_all(action="DESELECT")
    fixture_object.select_set(True)
    bpy.context.view_layer.objects.active = fixture_object

    bpy.ops.wm.stl_export(filepath=output_path, export_selected_objects=True, global_scale=1.0)
    print(f"FACTORY_FIXTURE_EXPORT_OK {output_path}")


main()
