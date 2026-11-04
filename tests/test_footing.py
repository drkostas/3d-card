import numpy as np
import trimesh

from card3d import footing as F


def _rod_on_its_flat(r=2.55, length=17.0, cut=0.222):
    """A round rod lying along x with its underside cut flat, as a snap axle prints."""
    rod = trimesh.creation.cylinder(radius=r, height=length, sections=96)
    rod.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    rod.apply_translation([0, 0, r])
    floor = trimesh.creation.box(extents=[length + 10, 20, 10])
    floor.apply_translation([0, 0, cut - 5.0])
    rod = rod.difference(floor)
    rod.apply_translation([0, 0, -rod.bounds[0][2]])
    return rod


def test_a_rod_on_a_thin_flat_is_a_narrow_strip_even_with_a_fair_area():
    f = F.footing(_rod_on_its_flat())
    # read half a layer up, where the round rod is already a little wider than its flat
    assert f["width_mm"] < F.FOOT_MIN_W and f["length_mm"] > 16
    assert f["area_mm2"] > 14            # what bed_area alone would have passed
    assert f["narrow"] and "strip" in f["why"]


def test_a_block_stands():
    f = F.footing(trimesh.creation.box(extents=(10, 10, 5)))
    assert not f["narrow"] and abs(f["width_mm"] - 10) < 0.2


def test_a_keel_three_lines_wide_is_not_flagged_for_being_long():
    keel = trimesh.creation.box(extents=(14, 3.2, 2))
    assert not F.footing(keel)["narrow"]


def test_ears_are_one_layer_and_mostly_beyond_the_part():
    rod = _rod_on_its_flat()
    eared = F.ears(rod)
    assert abs(F.EAR_H - 0.2) < 1e-9
    # the eared first layer reaches past both tips by most of an ear
    reach = (eared.extents[0] - rod.extents[0]) / 2.0
    assert abs(reach - (F.EAR_D - F.EAR_OVERLAP)) < 0.2


def test_ears_hold_the_rod_and_leave_its_shape():
    rod = _rod_on_its_flat()
    eared = F.ears(rod)
    f = F.footing(eared)
    assert not f["narrow"] and f["area_mm2"] > 2 * F.footing(rod)["area_mm2"]
    assert eared.is_watertight and len(eared.split(only_watertight=False)) == 1
    # above the ears the rod is untouched
    assert abs(eared.bounds[1][2] - rod.bounds[1][2]) < 1e-6
    # the ears add at most two discs (less where they overlap the rod's own bottom), and above them
    # the rod's cross-section is the same
    discs = 2 * np.pi * (F.EAR_D / 2) ** 2 * F.EAR_H
    assert 0 < eared.volume - rod.volume <= discs + 1e-6
    for z in (1.0, 2.5):
        assert abs(F._section(eared, z).area - F._section(rod, z).area) < 0.05


def test_ears_sit_on_the_ends_of_a_curved_first_layer():
    import numpy as np
    import trimesh
    from shapely.geometry import LineString
    from card3d import footing
    # a thin arc lying on the plate, like an arm on its side: its ends are far off the middle line
    a = np.linspace(-1.0, 1.0, 40)
    arc = LineString(np.c_[20 * np.sin(a), 20 * (1 - np.cos(a))]).buffer(0.7)
    m = trimesh.creation.extrude_polygon(arc, 1.5)
    eared = footing.ears(m)
    disc_area = np.pi * (footing.EAR_D / 2.0) ** 2
    first = footing._section(eared, 0.1).area
    # both discs touch the part, so the first layer gained close to two whole discs, not one
    assert first > footing._section(m, 0.1).area + 1.6 * disc_area
    assert len(eared.split(only_watertight=False)) == 1


def _round_rod(r=2.0, length=30.0):
    """A plain round rod lying along x on the plate, the shape of a limb on a card."""
    rod = trimesh.creation.cylinder(radius=r, height=length, sections=96)
    rod.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    rod.apply_translation([0, 0, r - 0.15])          # a slight flat, as a part seated on a card has
    floor = trimesh.creation.box(extents=[length + 10, 20, 10])
    floor.apply_translation([0, 0, -5.0])
    return rod.difference(floor)


def _ring(at=(25.0, 0.0), r_out=4.0, r_in=2.0, h=3.0):
    ring = trimesh.creation.annulus(r_min=r_in, r_max=r_out, height=h, sections=96)
    ring.apply_translation([at[0], at[1], h / 2.0])
    return ring


def _ball(at=(-25.0, 0.0), r=2.5):
    ball = trimesh.creation.icosphere(subdivisions=4, radius=r)
    ball.apply_translation([at[0], at[1], r - 0.2])
    floor = trimesh.creation.box(extents=[20, 20, 10])
    floor.apply_translation([at[0], at[1], -5.0])
    return ball.difference(floor)


def _parts():
    return {"rod": _round_rod(), "ring": _ring(), "ball": _ball()}


def _frame():
    """A frame round the parts, lying on the plate, with a gate to each part at mid height."""
    outer = trimesh.creation.box(extents=(70, 20, 2))
    inner = trimesh.creation.box(extents=(66, 16, 4))
    frame = outer.difference(inner)
    frame.apply_translation([0, 0, 1.0])
    gates = []
    for x, reach in ((0.0, 6.5), (25.0, 4.5), (-25.0, 6.0)):     # each runs 0.5 mm into its part
        g = trimesh.creation.box(extents=(1.2, reach, 1.0))
        g.apply_translation([x, -8.0 + reach / 2.0, 1.4])
        gates.append(g)
    return trimesh.boolean.union([frame] + gates)


def _card():
    return trimesh.boolean.union([_frame()] + list(_parts().values()))


def test_the_sheet_is_one_layer_and_one_piece_with_the_frame():
    c = _card()
    s, (t,), info = F.sheet([c], parts=list(_parts().values()))
    assert abs(s.extents[2] - F.SHEET_H) < 1e-6 and abs(s.bounds[0][2]) < 1e-6
    assert len(trimesh.boolean.union([s, t]).split(only_watertight=False)) == 1
    assert info["area_mm2"] > 100


def test_the_sheet_keeps_clear_of_every_part_and_joins_the_frame():
    c, parts = _card(), list(_parts().values())
    s, _t, _i = F.sheet([c], parts=parts)
    under = F._cut(s, 0.1)
    for p in parts:
        assert under.distance(F._cut(p, 0.1)) > 0.25          # 0.3 mm drawn, so nothing welds it to a part
    assert under.intersection(F._cut(_frame(), 0.1)).area > 1.0


def test_the_round_sides_stand_over_the_sheet():
    c, parts = _card(), list(_parts().values())
    s, _t, _i = F.sheet([c], parts=parts)
    for p in parts:
        sides = F._cut(p, 0.6).difference(F._cut(p, 0.1).buffer(F.SHEET_GAP_XY))
        if sides.area > 0.5:
            assert sides.intersection(F._cut(s, 0.1)).area > 0.95 * sides.area


def test_the_card_is_empty_for_one_layer_over_the_sheet_and_untouched_above():
    c, parts = _card(), list(_parts().values())
    s, (t,), info = F.sheet([c], parts=parts)
    gap_mid = F.SHEET_H + F.SHEET_GAP_Z / 2.0
    over = F._cut(s, 0.1).difference(F._cut(_frame(), 0.1).buffer(0.05))
    assert F._cut(t, gap_mid).intersection(over).area < 0.05
    # the frame keeps its second layer, the first layer is the card's own, above nothing changed
    assert abs(F._cut(t, gap_mid).intersection(F._cut(_frame(), gap_mid)).area -
               F._cut(_frame(), gap_mid).area) < 0.05
    assert abs(F._cut(t, 0.1).area - F._cut(c, 0.1).area) < 0.05
    for z in (0.6, 1.5, 2.5):
        assert abs(F._cut(t, z).area - F._cut(c, z).area) < 0.05
    assert info["taken_mm3"][0] > 0


def test_a_scrap_inside_a_ring_is_left_out_and_reported():
    c, parts = _card(), list(_parts().values())
    s, _t, info = F.sheet([c], parts=parts)
    hole = trimesh.creation.cylinder(radius=1.5, height=1)
    hole.apply_translation([25, 0, 0.5])
    assert info["left_out_mm2"] > 0
    assert not F._cut(s, 0.1).intersects(F._cut(hole, 0.1))


def test_a_body_in_a_second_colour_is_kept_clear_of_too():
    c, parts = _card(), list(_parts().values())
    inlay = trimesh.creation.box(extents=(4, 4, 0.6))
    inlay.apply_translation([12.0, 0, 0.3])
    s, (t, b), _i = F.sheet([c, inlay], parts=parts + [inlay])
    assert F._cut(s, 0.1).distance(F._cut(inlay, 0.1)) > 0.25          # 0.3 mm drawn, so nothing welds it to a part
    assert abs(b.bounds[1][2] - inlay.bounds[1][2]) < 1e-6


def test_without_parts_everything_is_kept_clear_of_and_the_largest_piece_kept():
    rod = _round_rod()
    s, (t,), info = F.sheet([rod])
    assert len(s.split(only_watertight=False)) == 1
    assert F._cut(s, 0.1).distance(F._cut(rod, 0.1)) > 0.25          # 0.3 mm drawn, so nothing welds it to a part


def test_the_sheet_stays_inside_the_frame():
    c, parts = _card(), list(_parts().values())
    s, _t, _i = F.sheet([c], parts=parts)
    assert s.bounds[0][0] >= c.bounds[0][0] - 1e-6 and s.bounds[1][0] <= c.bounds[1][0] + 1e-6
    assert s.bounds[0][1] >= c.bounds[0][1] - 1e-6 and s.bounds[1][1] <= c.bounds[1][1] + 1e-6
