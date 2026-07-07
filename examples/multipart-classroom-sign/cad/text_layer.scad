// text_layer.scad
// Raised text for a multi-part classroom sign example (assembly part 2 of
// 3). Hand-authored for the ai-3d-factory examples/ library
// (examples/multipart-classroom-sign/). Shares the same origin as
// base.scad/badge.scad - do not re-center this part. Intended as its own
// separately-colored part (e.g. contrasting text color), not fused with
// the base plate. See docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with base.scad and badge.scad ----
plate_width = 150;
plate_depth = 50;
plate_height = 5;

// ---- Text-only parameters ----
text_string = "Room 214";
text_size = 14;
text_height = 2;      // how far the raised text rises above the plate surface
text_font = "Liberation Sans:style=Bold";  // change if this font isn't installed locally

module sign_text() {
    translate([plate_width / 2, plate_depth / 2, plate_height])
        linear_extrude(height = text_height)
            text(text_string, size = text_size, halign = "center", valign = "center", font = text_font);
}

sign_text();
