import numpy as np
import trimesh

from card3d import tosprue as T


def test_a_small_kit_becomes_one_card_and_comes_back(kit):
    got, rep = T.best_card(verbose=False, source=kit)
    assert got["bodies"] == 1                      # one solid card
    assert rep["ok"] and rep["matched"] == len(got["parts"]) == 3
    assert got["fits_bed"] and len(got["gates"]) >= 3
    W, H, Z = got["size"]
    assert W > 20 and H > 14 and Z >= 10


def test_rows_decide_the_reading_order(kit):
    a = T.build(verbose=False, source=kit, rows=[["wheel"], ["block"], ["rod"]])
    b = T.build(verbose=False, source=kit, rows=[["rod"], ["block"], ["wheel"]])

    def y(got, n):
        return float(got["parts"][n].bounds.mean(axis=0)[1])
    # the first row is the top of the card
    assert y(a, "wheel") > y(a, "block") > y(a, "rod")
    assert y(b, "rod") > y(b, "block") > y(b, "wheel")


def test_the_bed_is_a_setting(kit):
    assert T.build(verbose=False, source=kit)["fits_bed"]
    assert not T.build(verbose=False, source=kit, bed=(30.0, 30.0))["fits_bed"]


def test_export_writes_the_card(kit, tmp_path):
    got, f = T.export(out=tmp_path / "out", name="kit.stl", verbose=False, source=kit)
    assert f == tmp_path / "out" / "kit.stl"
    back = trimesh.load(f)
    assert abs(back.volume - got["card"].volume) < 1e-3 * got["card"].volume


def test_build_needs_a_source():
    try:
        T.build(verbose=False)
    except ValueError as e:
        assert "source" in str(e)
    else:
        raise AssertionError("build() without source= must refuse")


def test_a_world_point_maps_onto_its_part_on_the_card(kit):
    # the socket's centre is a world point inside the block's material (its wall), and mapped
    # through to_card it must land inside the block as placed, seated and moved
    got, _rep = T.best_card(verbose=False, source=kit)
    j = got["joints"][0]
    at = np.asarray(j["at"], float)
    block = got["parts"]["block"]
    on_card = trimesh.transform_points([at], np.asarray(got["to_card"]["block"], float))[0]
    lo, hi = block.bounds
    assert np.all(on_card >= lo - 1e-6) and np.all(on_card <= hi + 1e-6)
    off = trimesh.transform_points([at], np.asarray(got["moved"]["block"], float))[0]
    assert not (np.all(off >= lo - 1e-6) and np.all(off <= hi + 1e-6)) or np.allclose(off, on_card)


def test_the_card_reads_back_from_its_file_as_one_piece(kit):
    got, _rep = T.best_card(verbose=False, source=kit)
    w = got["as_written"]
    assert w["ok"] and w["bodies"] == 1 and w["holes"] == 0


def test_up_mode_turns_the_models_up_to_the_top_of_the_card():
    # a part whose model-up currently points up and to the right on the card
    m = trimesh.creation.box(extents=(6, 6, 6))
    ref = np.array([1.0, 1.0, 0.0])
    _p, turn = T._spin_flat(m, ("up", ref))
    rot = trimesh.transformations.rotation_matrix(turn, [0, 0, 1])[:3, :3]
    got = rot @ ref
    assert got[1] > 0 and abs(got[0]) < 1e-6         # now points straight up the card (+Y)


def test_up_mode_leaves_a_part_whose_up_points_at_the_viewer():
    m = trimesh.creation.box(extents=(6, 6, 6))
    _p, turn = T._spin_flat(m, ("up", np.array([0.0, 0.0, 1.0])))
    assert turn == 0.0                               # nothing to turn about Z


def test_long_mode_hangs_the_limb_with_its_ref_end_at_the_top():
    m = trimesh.creation.box(extents=(20, 3, 3))     # long axis along X
    p, turn = T._spin_flat(m, ("long", np.array([1.0, 0.2, 0.0])))  # +X end is the joint end
    b = p.bounds
    assert (b[1][1] - b[0][1]) > (b[1][0] - b[0][0])  # long axis now runs down the card
    rot = trimesh.transformations.rotation_matrix(turn, [0, 0, 1], m.bounds.mean(axis=0))
    tip = trimesh.transform_points(np.array([[10.0, 0.0, 0.0]]), rot)[0]
    assert tip[1] > float(m.bounds.mean(axis=0)[1])   # the +X end ended up at the top


def test_upright_wins_over_down_and_across(kit):
    # a part named in both upright and across takes the upright turn (build resolves the mode string
    # against the seating turn). "long" stands the rod's long axis down the card, across lays it flat.
    a = T.build(verbose=False, source=kit, rows=[["wheel"], ["block"], ["rod"]],
                across={"rod"}, upright={"rod": "long"})
    rod = a["parts"]["rod"]
    b = rod.bounds
    assert (b[1][1] - b[0][1]) > (b[1][0] - b[0][0])  # the rod hangs down, not across


def test_cross_bars_never_cross_a_part():
    a = trimesh.creation.box(extents=(10, 10, 2)); a.apply_translation((20, 30, 1))
    b = trimesh.creation.box(extents=(10, 10, 2)); b.apply_translation((60, 30, 1))
    placed = {"a": a, "b": b}
    segs = T.cross_bars(placed, [15.0, 45.0], 80.0, 60.0, pitch=12.0)
    assert segs                                       # verticals fit the clear lane between the parts
    for (x, y0, y1) in segs:
        for p in placed.values():
            lo, hi = p.bounds
            overlap_x = (x + T.BAR_W / 2 > lo[0]) and (x - T.BAR_W / 2 < hi[0])
            overlap_y = (y1 > lo[1]) and (y0 < hi[1])
            assert not (overlap_x and overlap_y)


def _ring_with_a_stub(R):
    # a ring cut from a 2 mm plate with a round stub on its rim, turned by R
    ring = trimesh.creation.annulus(r_min=4.0, r_max=6.0, height=2.0, sections=96)
    stub = trimesh.creation.cylinder(radius=1.4, height=8.0, sections=48)
    stub.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    stub.apply_translation([9.0, 0.0, 0.0])
    m = trimesh.util.concatenate([ring, stub])
    m.apply_transform(R)
    return m


def test_flat_sides_finds_the_plate_a_ring_was_cut_from():
    R = trimesh.transformations.rotation_matrix(0.9, [0.3, 0.8, 0.5])
    up = R[:3, :3] @ np.array([0.0, 0.0, 1.0])
    a, b = T.flat_sides(_ring_with_a_stub(R))
    assert abs(abs(float(a @ up)) - 1.0) < 1e-6 and np.allclose(a, -b)


def test_flat_sides_lays_both_of_a_mirrored_pair_flat(monkeypatch):
    # the same ring and its mirror image, each named in REST through flat_sides, both come out of
    # `seated` lying on a flat side: the plate normal is vertical for each
    R = trimesh.transformations.rotation_matrix(0.9, [0.3, 0.8, 0.5])
    left = _ring_with_a_stub(R)
    right = left.copy()
    right.apply_transform(trimesh.transformations.scale_matrix(-1, direction=[1, 0, 0]))
    right.invert()
    parts = {"left": left, "right": right}
    monkeypatch.setattr(T, "REST", {k: T.flat_sides(m) for k, m in parts.items()})
    _out, log = T.seated(parts, [])
    for r in log:
        M = np.asarray(r["matrix"], float)[:3, :3]
        n = T.flat_sides(parts[r["part"]])[0]
        assert abs(abs(float((M @ n)[2])) - 1.0) < 1e-6, r["part"]


def test_cross_bars_keep_one_solid_card_that_still_comes_apart(kit):
    got = T.build(verbose=False, source=kit, rows=[["wheel"], ["block"], ["rod"]], cross=True)
    rep = T.round_trip(got, verbose=False)
    assert got["bodies"] == 1 and rep["ok"]


def test_a_nested_card_is_one_body_that_comes_apart(kit):
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    rep = T.round_trip(got, verbose=False)
    assert got["bodies"] == 1 and rep["ok"], got["notes"]
    assert not got["weak"], got["notes"]


def test_every_nested_part_is_held_from_two_sides(kit):
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    for n, m in got["parts"].items():
        hold = got["holds"][n]
        assert len(hold) >= 2, n
        c = np.asarray(m.centroid[:2])
        ang = [np.degrees(np.arctan2(y - c[1], x - c[0])) for x, y in hold]
        widest = max(abs((a - b + 180) % 360 - 180) for i, a in enumerate(ang) for b in ang[i + 1:])
        assert widest >= T.HOLD_SPREAD_DEG * 0.9, (n, ang)
        gates = [g for g in got["gates"] if g[0] == n]
        assert len(gates) >= 2, n


def test_web_runners_keep_their_gap(kit):
    from shapely.geometry import Polygon
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    W, H, _z = got["size"]
    net, holds, weak = T.web_runners(got["parts"], W, H)
    # A part's own runner ends may come to 0.6 of the gap at their corners, where its gates cross;
    # that is still clear air a slicer keeps apart. No runner ever touches a part.
    for n, m in got["parts"].items():
        fp = Polygon(T.footprint(m)).buffer(0)
        assert net.distance(fp) >= T.NEST_GAP * 0.6 - 1e-6, n


def test_the_nest_never_overlaps_two_parts(kit):
    parts, _made, _notes = kit()
    placed, moved, (W, H) = T.nest_outlines(parts, 60.0)
    from shapely.geometry import Polygon
    fps = {n: Polygon(T.footprint(m)).buffer(0) for n, m in placed.items()}
    names = sorted(fps)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert fps[a].distance(fps[b]) >= 2 * T.NEST_CORRIDOR - 2 * T.NEST_STEP, (a, b)


def test_a_named_card_carries_its_name(kit):
    plain = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    named = T.build(verbose=False, source=kit, nest=True, nest_width=60.0, plate="KIT")
    assert named["card"].volume > plain["card"].volume and named["bodies"] == 1


def test_the_numbers_follow_the_reading_order(kit):
    # the stamped numbers follow `rows` on a nested card too, which has no rows of its own
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0,
                  rows=[["wheel"], ["rod", "block"]])
    assert got["numbers"] == {"wheel": 1, "rod": 2, "block": 3}


def test_parts_no_row_names_are_numbered_after_in_alphabetical_order(kit):
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0, rows=[["wheel"]])
    assert got["numbers"] == {"wheel": 1, "block": 2, "rod": 3}
    plain = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    assert plain["numbers"] == {"block": 1, "rod": 2, "wheel": 3}


def test_the_nest_keeps_a_part_reading_the_right_way_when_it_costs_nothing(kit):
    parts, _made, _notes = kit()
    # the wheel is round, so any turn packs the same: the preferred one must win
    want = 0.7
    placed, moved, _size = T.nest_outlines(parts, 80.0, prefer={"wheel": want})
    R = np.asarray(moved["wheel"], float)[:3, :3]
    got = float(np.arctan2(R[1, 0], R[0, 0]))
    assert abs((got - want + np.pi) % (2 * np.pi) - np.pi) < 1e-6


def test_every_number_tag_sits_nearer_its_own_part(kit):
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    clear = T.tag_clearance(got["tags"], got["parts"])
    assert set(clear) == set(got["parts"])
    for n, (own, other, who) in clear.items():
        assert own + T.NEST_TAG_OWN <= other, (n, own, other, who)


def test_a_tag_skips_a_runner_that_is_nearer_another_part():
    from shapely.geometry import box
    # part a at x 0..10, part b at x 24..34; one runner between them but nearer b, one left of a
    a = trimesh.creation.box(bounds=[[0, 0, 0], [10, 10, 2]])
    b = trimesh.creation.box(bounds=[[24, 0, 0], [34, 10, 2]])
    net = box(20.2, -5, 21.8, 15).union(box(-12.1, -5, -10.5, 15))
    out, missing = T.number_tags({"a": a, "b": b}, {"a": 1, "b": 2}, net)
    assert not missing
    ax = (out["a"][0].bounds[0] + out["a"][0].bounds[2]) / 2.0
    assert ax < 0.0                                  # a's number went to the runner on its own side
    # the old rule, nearest runner only, would have put it between the two parts
    old, _m = T._number_tags({"a": a, "b": b}, {"a": 1}, net)
    assert (old["a"][0].bounds[0] + old["a"][0].bounds[2]) / 2.0 > 10.0


def test_the_footprint_is_the_real_shadow_when_the_exact_merge_fails(monkeypatch):
    # an exact merge of a fine mesh's triangles can stop with a GEOS topology error; the shadow
    # must still be the part's own outline, not its bounding box
    def broken(*_a, **_k):
        raise RuntimeError("TopologyException: side location conflict")
    monkeypatch.setattr(trimesh.path.polygons, "projected", broken)
    from shapely.geometry import Polygon
    ball = trimesh.creation.icosphere(subdivisions=4, radius=8.0)
    area = Polygon(T.footprint(ball)).area
    assert abs(area - np.pi * 64.0) < 0.02 * np.pi * 64.0   # a circle, not the 256 mm2 box



def test_no_two_number_tags_run_together(kit):
    # two tags side by side read as one number (a 5 beside a 2 reads 52)
    from shapely.geometry import box
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0)
    plates = [box(*b) for b in got["tags"].values()]
    for i, a in enumerate(plates):
        for b in plates[i + 1:]:
            assert a.distance(b) >= T.NEST_TAG_APART - 1e-6


def test_a_tag_with_no_clear_runner_stands_on_a_stub():
    from shapely.geometry import box
    # one runner, nearer b than a; a's number goes out into the open beside a, on a short stub
    a = trimesh.creation.box(bounds=[[0, 0, 0], [10, 10, 2]])
    b = trimesh.creation.box(bounds=[[24, 0, 0], [34, 10, 2]])
    net = box(20.2, -5, 21.8, 30)
    out, missing = T.number_tags({"a": a, "b": b}, {"a": 1, "b": 2}, net)
    assert not missing
    own, other, _who = T.tag_clearance({"a": T._tag_box(out["a"][1])}, {"a": a, "b": b})["a"]
    assert own + T.NEST_TAG_OWN <= other
    plate, stamp = out["a"]
    assert plate.area > box(*T._tag_box(stamp)).area + 1.0     # it carries its stub
    assert plate.intersects(net)                               # which reaches the runner


def test_build_says_which_parts_left_their_reading_turn(kit):
    got = T.build(verbose=False, source=kit, nest=True, nest_width=60.0,
                  upright={"block": "up", "rod": "long"})
    assert set(got["reads"]) == {"block", "rod"}
    assert got["off_reading"] == T.off_reading(
        {n: got["moved"][n] for n in got["reads"]}, got["reads"])
