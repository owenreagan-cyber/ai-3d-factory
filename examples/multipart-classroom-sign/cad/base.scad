// base.scad
// Base plate for a multi-part classroom sign example (assembly part 1 of
// 3: base plate + raised text layer + accent badge). Hand-authored for the
// ai-3d-factory examples/ library (examples/multipart-classroom-sign/) -
// no built-in `factory generate-openscad` template covers a 3-part sign
// with an icon/badge accent yet (the built-in `multipart-nameplate`
// template only covers a base + text pair - see
// factory/openscad/templates.py). Keep plate_width/plate_depth/
// plate_height in sync with text_layer.scad and badge.scad - all three
// parts share the same (0,0,0) origin and must be imported into the
// slicer without re-centering any of them. See
// docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with text_layer.scad and badge.scad ----
plate_width = 150;
plate_depth = 50;
plate_height = 5;

// ---- Base-only parameters ----
mounting_hole_diameter = 4;   // set to 0 to omit the 4 corner mounting holes
mounting_hole_margin = 8;     // distance of hole centers from each edge

module mounting_holes() {
    for (x = [mounting_hole_margin, plate_width - mounting_hole_margin])
        for (y = [mounting_hole_margin, plate_depth - mounting_hole_margin])
            translate([x, y, -1])
                cylinder(d = mounting_hole_diameter, h = plate_height + 2, $fn = 32);
}

difference() {
    cube([plate_width, plate_depth, plate_height]);
    if (mounting_hole_diameter > 0) {
        mounting_holes();
    }
}
