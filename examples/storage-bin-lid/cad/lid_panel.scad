// lid_panel.scad
// Main panel for a labeled storage-bin lid example (assembly part 1 of 3:
// lid panel + raised label text + pull tab). Hand-authored for the
// ai-3d-factory examples/ library (examples/storage-bin-lid/) - no
// built-in `factory generate-openscad` template covers a bin-lid shape
// yet (the built-in templates are test-cube/nameplate/sign/
// multipart-nameplate - see factory/openscad/templates.py). Keep
// lid_width/lid_depth/lid_height in sync with raised_label.scad and
// pull_tab.scad - all three parts share the same (0,0,0) origin and must
// be imported into the slicer without re-centering any of them. See
// docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with raised_label.scad and pull_tab.scad ----
lid_width = 160;
lid_depth = 100;
lid_height = 4;

// ---- Lid-only parameters ----
corner_radius = 6;          // set to 0 for square corners
lip_wall_thickness = 2;     // friction-fit lip wall thickness
lip_height = 6;              // how far the lip extends down into the bin opening
lip_inset = 3;               // gap between the lid's outer edge and the lip, for a snug (not tight) friction fit

module rounded_rect(width, depth, radius, height) {
    if (radius > 0) {
        hull() {
            for (x = [radius, width - radius])
                for (y = [radius, depth - radius])
                    translate([x, y, 0])
                        cylinder(r = radius, h = height, $fn = 32);
        }
    } else {
        cube([width, depth, height]);
    }
}

// A downward-facing lip ring, inset from the lid's outer edge, sized to
// friction-fit inside a storage bin's top opening - like a picture
// frame's backing ring, not a solid plug.
module friction_fit_lip() {
    inner_width = lid_width - 2 * lip_inset;
    inner_depth = lid_depth - 2 * lip_inset;
    inner_radius = max(corner_radius - lip_inset, 0);
    translate([lip_inset, lip_inset, -lip_height])
        difference() {
            rounded_rect(inner_width, inner_depth, inner_radius, lip_height);
            translate([lip_wall_thickness, lip_wall_thickness, -1])
                rounded_rect(
                    inner_width - 2 * lip_wall_thickness,
                    inner_depth - 2 * lip_wall_thickness,
                    max(inner_radius - lip_wall_thickness, 0),
                    lip_height + 2
                );
        }
}

union() {
    rounded_rect(lid_width, lid_depth, corner_radius, lid_height);
    friction_fit_lip();
}
