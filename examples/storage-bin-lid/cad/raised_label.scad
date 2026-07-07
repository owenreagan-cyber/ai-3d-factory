// raised_label.scad
// Raised label text for a labeled storage-bin lid example (assembly part
// 2 of 3). Hand-authored for the ai-3d-factory examples/ library
// (examples/storage-bin-lid/). Shares the same origin as
// lid_panel.scad/pull_tab.scad - do not re-center this part. Intended as
// its own separately-colored part (e.g. contrasting label color), not
// fused with the lid panel. See docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with lid_panel.scad and pull_tab.scad ----
lid_width = 160;
lid_depth = 100;
lid_height = 4;

// ---- Label-only parameters ----
label_text = "CRAYONS";
label_size = 14;
label_height = 1.6;   // how far the raised text rises above the lid surface
label_font = "Liberation Sans:style=Bold";  // change if this font isn't installed locally

module raised_label() {
    translate([lid_width / 2, lid_depth / 2, lid_height])
        linear_extrude(height = label_height)
            text(label_text, size = label_size, halign = "center", valign = "center", font = label_font);
}

raised_label();
