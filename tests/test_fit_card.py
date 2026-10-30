from base3d.nozzle import Nozzle

from card3d import labels as LB
from card3d.coupons import fit_card as FC

SPEC = FC.FitCardSpec(ball_sizes=(5.0,), tube_bores={"T1": 5.0, "T2": 5.3})


def test_every_piece_is_one_watertight_solid_and_named_by_what_it_varies():
    pieces, info = FC.build(SPEC)
    assert sorted(pieces) == sorted(
        ["socket 5A", "socket 5B", "socket 5C", "ball 5-1", "ball 5-2", "ball 5-3",
         "peg P1", "peg P2", "peg P3", "hole H1", "hole H2", "hole H3", "tube T1", "tube T2"])
    for name, m in pieces.items():
        assert m.is_watertight and len(m.split(only_watertight=False)) == 1, name
    # the sockets differ only in fit and the balls only in neck
    assert [info[f"socket 5{k}"]["gap"] for k in "ABC"] == [0.20, 0.28, 0.36]
    necks = [info[f"ball 5-{n}"]["neck"] for n in "123"]
    assert necks == sorted(necks) and necks[2] - necks[0] > 1.0


def test_the_layout_is_a_row_per_ball_size_then_pegs_and_holes_then_tubes():
    pieces, _ = FC.build(SPEC)
    placed = FC.layout(pieces, SPEC)
    y = {n: float(m.bounds[0][1]) for n, m in placed.items()}
    assert y["socket 5A"] == y["ball 5-3"] < y["peg P1"] == y["hole H3"] < y["tube T1"]
    assert all(abs(float(m.bounds[0][2])) < 1e-6 for m in placed.values())


def test_labels_print_as_two_lines_of_the_nozzle():
    for nozzle in (Nozzle(0.4), Nozzle(0.2, layer=0.1)):
        h = LB.fit_height("5-3", nozzle, FC.FitCardSpec().label_height)
        assert LB.stroke_width("5-3", height=h) >= nozzle.wall - 0.01


def test_no_tubes_when_none_are_asked_for():
    pieces, _ = FC.build(FC.FitCardSpec(ball_sizes=(4.0,)))
    assert not any(n.startswith("tube") for n in pieces)


def test_a_medium_socket_takes_its_thinnest_ball_holds_it_and_lets_it_turn():
    r = FC.check_pair(SPEC, 5.0, "B", "1")
    assert r["ok"] and r["turns_deg"] >= 30, r


def test_a_rim_grip_in_mm_is_the_same_for_every_ball_size():
    spec = FC.FitCardSpec(ball_sizes=(4.0, 6.0), fits={"D": (0.36, 0.07), "F": (0.36, 0.03)}, grip_mm=True,
                          necks={"2": 0.6}, pegs={}, holes={})
    assert FC.grip_of(spec, 4.0, "D") == FC.grip_of(spec, 6.0, "D") == 0.07
    _blk, _at, _axis, _r, info = FC.socket_geometry(spec, 6.0, "F")
    assert info["grip"] == 0.03 and info["gap"] == 0.36
    # the default reads its share of the joint's grip, which grows with the ball
    plain = FC.FitCardSpec()
    assert FC.grip_of(plain, 6.0, "C") > FC.grip_of(plain, 4.0, "C")


def test_a_piece_the_project_adds_gets_a_last_row():
    import trimesh
    pieces, _ = FC.build(SPEC)
    pieces["axle demo"] = trimesh.creation.box(extents=(20, 4, 4))
    placed = FC.layout(pieces, SPEC)
    assert float(placed["axle demo"].bounds[0][1]) > max(float(m.bounds[0][1]) for n, m in placed.items() if n != "axle demo")
