// badge.scad
// Small raised accent badge/icon for a multi-part classroom sign example
// (assembly part 3 of 3). Hand-authored for the ai-3d-factory examples/
// library (examples/multipart-classroom-sign/). Shares the same origin as
// base.scad/text_layer.scad - do not re-center this part. Intended as its
// own separately-colored accent (e.g. a school-color badge), distinct
// from the base plate and text layer - a simple stand-in for the kind of
// icon/badge part a richer classroom or manufacturing demo might need.
// See docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with base.scad and text_layer.scad ----
plate_width = 150;
plate_depth = 50;
plate_height = 5;

// ---- Badge-only parameters ----
badge_margin = 10;        // distance from the left edge, centered vertically
badge_diameter = 16;
badge_height = 2;         // how far the raised badge rises above the plate surface

module accent_badge() {
    translate([badge_margin + badge_diameter / 2, plate_depth / 2, plate_height])
        cylinder(d = badge_diameter, h = badge_height, $fn = 64);
}

accent_badge();
