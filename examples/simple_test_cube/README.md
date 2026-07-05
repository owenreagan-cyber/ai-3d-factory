# simple_test_cube

A minimal example project: a plain 20mm cube, used to exercise the
`factory` CLI end to end (`init-project` -> `plan` -> `validate` ->
`render` -> `report`) without depending on any real design work.

This example does not ship a pre-generated STL. Generate one locally with
trimesh (no network, no external tools):

```bash
python -c "
import trimesh
trimesh.creation.box(extents=(20, 20, 20)).export('cube.stl')
"
factory validate cube.stl
factory render cube.stl
```
