// pull_tab.scad
// Small raised pull tab for a labeled storage-bin lid example (assembly
// part 3 of 3). Hand-authored for the ai-3d-factory examples/ library
// (examples/storage-bin-lid/). Shares the same origin as
// lid_panel.scad/raised_label.scad - do not re-center this part.
// Positioned centered along the front edge, so a hand can grip it to lift
// the lid off the bin. See docs/slicer-review-workflow.md.
//
// This repo does not run OpenSCAD automatically. Geometry sanity check
// passed does not mean print-ready - human slicer review is still
// required. See AGENT.md.

// ---- Shared parameters (all in millimeters) - keep in sync with lid_panel.scad and raised_label.scad ----
lid_width = 160;
lid_depth = 100;
lid_height = 4;

// ---- Pull-tab-only parameters ----
tab_width = 30;
tab_depth = 14;
tab_height = 5;          // how far the tab rises above the lid surface
tab_corner_radius = 4;

module pull_tab() {
    translate([lid_width / 2 - tab_width / 2, 0, lid_height])
        hull() {
            for (x = [tab_corner_radius, tab_width - tab_corner_radius])
                for (y = [tab_corner_radius, tab_depth - tab_corner_radius])
                    translate([x, y, 0])
                        cylinder(r = tab_corner_radius, h = tab_height, $fn = 32);
        }
}

pull_tab();
