import zipfile

import numpy as np
import trimesh

from card3d import slicecheck as SC


def _square(x0, y0, x1, y1, feature):
    """Extrusion moves round a rectangle, as G-code lines under a feature tag."""
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    out = [f"; FEATURE: {feature}", f"G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f}"]
    out += [f"G1 X{x:.3f} Y{y:.3f} E{0.05 * 10:.4f}" for x, y in pts[1:]]
    return out


def _gcode(rect, settings, layers=3):
    """A small sliced card: a settings block, a brim and a wall on layer 1, thinner layers above."""
    x0, y0, x1, y1 = rect
    g = [f"; {k} = {v}" for k, v in settings.items()] + ["M83"]
    for i in range(layers):
        g += ["; CHANGE_LAYER", f"; Z_HEIGHT: {0.2 * (i + 1):.1f}"]
        if i == 0:
            g += _square(x0 - 3, y0 - 3, x1 + 3, y1 + 3, "Brim")
            g += _square(x0 + 0.2, y0 + 0.2, x1 - 0.2, y1 - 0.2, "Outer wall")
            g += _square(x0 + 0.6, y0 + 0.6, x1 - 0.6, y1 - 0.6, "Inner wall")
        else:
            g += _square(x0 + 0.2, y0 + 0.2, x1 - 0.2, y1 - 0.2, "Outer wall")
    return "\n".join(g) + "\n"


def _card():
    return trimesh.creation.box(bounds=[[0.0, 0.0, 0.0], [30.0, 12.0, 2.0]])


SETTINGS = {"brim_width": "5", "enable_support": "0", "curr_bed_type": "Textured PEI Plate"}


def test_toolpath_reads_layers_and_the_first_layer_moves():
    layers, segs = SC.toolpath(_gcode((100, 50, 130, 62), SETTINGS))
    assert len(layers) == 3
    assert layers[0][1] > layers[1][1]                     # the first layer carries the most filament
    assert {f for *_xy, f in segs} == {"Brim", "Outer wall", "Inner wall"}


def test_a_full_circle_arc_has_its_length():
    # one G3 that ends where it starts, centre 5 mm to the right: a full circle of radius 5
    g = "M83\n; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\nG0 X10 Y10\nG3 X10 Y10 I5 J0 E1.0\n"
    _layers, segs = SC.toolpath(g)
    length = sum(np.hypot(c - a, d - b) for a, b, c, d, _f in segs)
    assert abs(length - 2 * np.pi * 5) < 0.2


def test_the_settings_block_is_read():
    s = SC.settings_in(_gcode((0, 0, 30, 12), SETTINGS))
    assert s["brim_width"] == "5" and s["curr_bed_type"] == "Textured PEI Plate"


def test_a_card_the_slicer_moved_passes():
    sliced = {"gcode": _gcode((100, 50, 130, 62), SETTINGS), "slice_info": "", "plate_png": None}
    card, turns = SC.placed_as_sliced(_card(), sliced)
    rep = SC.check(sliced, card, overrides={"brim_width": "5", "enable_support": "0"},
                   bed_type="Textured PEI Plate")
    assert turns == 0 and rep["lined_up"] and rep["ok"], rep
    assert rep["islands"][0]["brim"] and rep["islands"][0]["first_layer_moves"] > 0


def test_a_setting_the_slicer_dropped_fails_the_check():
    sliced = {"gcode": _gcode((100, 50, 130, 62), SETTINGS), "slice_info": "", "plate_png": None}
    card, _turns = SC.placed_as_sliced(_card(), sliced)
    rep = SC.check(sliced, card, overrides={"brim_width": "8"})
    assert not rep["ok"] and not rep["settings"]["brim_width"]["ok"]


def test_a_card_the_slicer_turned_a_quarter_is_found():
    # the 30 x 12 card printed as 12 x 30: a move alone cannot line it up
    sliced = {"gcode": _gcode((100, 50, 112, 80), SETTINGS), "slice_info": "", "plate_png": None}
    moved_only = SC.check(sliced, _card())
    assert not moved_only["lined_up"]
    card, turns = SC.placed_as_sliced(_card(), sliced)
    rep = SC.check(sliced, card, overrides={"brim_width": "5"})
    assert turns in (1, 3) and rep["lined_up"] and rep["ok"], rep


def test_read_3mf_reads_the_plate_gcode(tmp_path):
    f = tmp_path / "card.gcode.3mf"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("Metadata/plate_1.gcode", _gcode((0, 0, 30, 12), SETTINGS))
        z.writestr("Metadata/slice_info.config", '<plate><metadata key="prediction" value="600"/></plate>')
    sliced = SC.read_3mf(f)
    assert "CHANGE_LAYER" in sliced["gcode"] and "prediction" in sliced["slice_info"]
    assert sliced["plate_png"] is None


def test_parts_are_placed_where_the_slicer_put_the_card_and_named_by_a_spot():
    # a card of two pads, 30 x 12 in its own frame, printed turned a quarter as 12 x 30
    left = trimesh.creation.box(bounds=[[0.0, 0.0, 0.0], [10.0, 12.0, 2.0]])
    right = trimesh.creation.box(bounds=[[20.0, 0.0, 0.0], [30.0, 12.0, 2.0]])
    card = trimesh.util.concatenate([left, right])
    sliced = {"gcode": _gcode((100, 50, 112, 80), SETTINGS), "slice_info": "", "plate_png": None}
    matrix, turns = SC.plate_transform(card, sliced)
    assert turns in (1, 3) and matrix.shape == (4, 4)
    placed = SC.parts_as_sliced({"left": left, "right": right}, card, sliced)
    (x0, y0, _), (x1, y1, _) = np.vstack([m.bounds for m in placed.values()]).min(0), \
        np.vstack([m.bounds for m in placed.values()]).max(0)
    assert abs(x0 - 100) < 0.5 and abs(x1 - 112) < 0.5 and abs(y0 - 50) < 0.5 and abs(y1 - 80) < 0.5
    for name, m in placed.items():
        cx, cy = m.bounds.mean(axis=0)[:2]
        assert SC.part_at(placed, cx, cy) == (name, 0.0)
    # the gap between the pads is 10 mm wide, so its middle is 5 mm from either pad
    gap_x, gap_y = 106.0, 65.0
    name, far = SC.part_at(placed, gap_x, gap_y)
    assert abs(far - 5.0) < 0.01, (name, far)


def test_a_card_that_cannot_be_lined_up_places_no_parts():
    sliced = {"gcode": _gcode((100, 50, 160, 90), SETTINGS), "slice_info": "", "plate_png": None}
    assert SC.plate_transform(_card(), sliced) == (None, 0)
    assert SC.parts_as_sliced({"card": _card()}, _card(), sliced) == {}
    assert SC.part_at({}, 0.0, 0.0) == (None, float("inf"))


def test_a_setting_per_extruder_is_compared_as_a_list():
    # a dual-nozzle printer writes one value per extruder, joined by commas
    assert SC._same(["Standard", "Standard"], "Standard,Standard")
    assert not SC._same(["Standard", "Standard"], "Standard")
    assert not SC._same(["Standard", "Standard"], "Standard,High Flow")
    assert SC._same([0.4, 0.4], "0.4,0.4")


def _outline(x0, y0, side=10.0, e=0.5):
    """G-code for one square outline at (x0, y0), started from a travel to its corner."""
    pts = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side), (x0, y0)]
    out = [f"G1 X{pts[0][0]} Y{pts[0][1]} F12000", "G1 E.8"]
    out += [f"G1 X{x} Y{y} E{e}" for x, y in pts[1:]]
    out.append("G1 E-.8")
    return out


def _two_layers(*squares):
    g = ["M83"]
    for z in (0.2, 0.4):
        g += ["; CHANGE_LAYER", f"; Z_HEIGHT: {z}"]
        for x0, y0 in squares:
            g += _outline(x0, y0)
    return "\n".join(g) + "\n"


def test_a_jump_between_two_parts_is_a_crossing_and_a_move_over_one_part_is_not():
    apart = SC.travels(_two_layers((0, 0), (40, 0)))
    # the jump from one square to the other runs 30 mm over nothing: once on the first layer, and on
    # the second also the jump back from where the first layer ended
    assert [p["crossings"] for p in apart["layers"]] == [1, 2]
    assert 28 < apart["layers"][0]["air_mm"] < 31 and 56 < apart["layers"][1]["air_mm"] < 61
    assert apart["retracts"] == 4 and apart["crossings"] == 3
    # one square: the only travel is onto its own corner, which its lines cover
    alone = SC.travels(_two_layers((0, 0)))
    assert alone["crossings"] == 0 and alone["air_mm"] < 0.5


def test_more_parts_means_more_crossings():
    few = SC.travels(_two_layers((0, 0), (40, 0)))
    many = SC.travels(_two_layers((0, 0), (40, 0), (80, 0), (0, 40)))
    assert many["crossings"] > few["crossings"] and many["air_mm"] > few["air_mm"]
