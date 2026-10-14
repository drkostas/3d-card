import numpy as np
import pytest
import trimesh

from card3d import joints as J
from card3d import labels as L
from card3d import roundtrip, simulator as S, sprue


@pytest.mark.parametrize("kind", ["peg", "pivot", "axle", "ball"])
def test_each_joint_fits_its_socket(kind):
    at, axis = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    peg = J.male(kind, 3.0, axis, at, backset=0.0)
    hole = J.female(kind, 3.0, axis, at)
    assert peg.volume > 0 and hole.volume > peg.volume
    outside = peg.difference(hole)
    assert outside.is_empty or outside.volume < 0.02 * peg.volume   # only grip, if any


@pytest.mark.parametrize("size", [3.0, 5.0])
def test_a_ball_can_be_pushed_home(size):
    from card3d.coupons import ball_coupon as C
    axis, at = np.array([0.0, 0.0, 1.0]), np.zeros(3)
    sock = C.socket_block(size, axis, at)
    squeeze, where = J.push_in(sock, size, axis, at)
    # only the rim may squeeze, and only by about its designed grip
    assert squeeze <= J.ball_grip(size) * C.PUSH_IN_SLACK + 0.02, (squeeze, where)
    assert squeeze > 0.0                       # and the rim does grip
    assert where < size / 2.0                  # where the slits are, not further out


def test_push_in_sees_a_blocked_socket():
    # a plain cylinder of material over the cavity's mouth: the ball cannot get past it
    size, axis, at = 3.0, np.array([0.0, 0.0, 1.0]), np.zeros(3)
    c = J.ball_centre(size, axis, at)
    blk = trimesh.creation.cylinder(radius=3.0, height=6.0)
    blk.apply_translation(c)
    cav = trimesh.creation.icosphere(subdivisions=3, radius=size / 2.0 + J.BALL_CLEAR)
    cav.apply_translation(c)
    bore = trimesh.creation.cylinder(radius=0.6, height=10.0)
    bore.apply_translation(c - np.array([0.0, 0.0, 5.0]))
    sock = blk.difference(trimesh.boolean.union([cav, bore]))
    squeeze, _where = J.push_in(sock, size, axis, at)
    assert squeeze > 0.8


def test_flat_card_round_trip():
    plates = {}
    for i, (w, h) in enumerate([(30, 12), (18, 18), (40, 8)]):
        m = trimesh.creation.box(extents=(w, h, J.PLATE))
        m.apply_translation((0, 0, J.PLATE / 2))
        plates[f"p{i}"] = m
    card, (W, H), place, gates = sprue.make_card(plates, J.PLATE, inner_w=120)
    mesh = trimesh.Trimesh(*_tess(card))
    rep = roundtrip.check(plates, mesh, gates, J.PLATE)
    assert rep["ok"], rep
    assert len(rep["matched"]) == 3


def _tess(part):
    v, f = part.tessellate(0.01, 0.2)
    return np.array([(p.X, p.Y, p.Z) for p in v]), np.array(f)


def test_overhangs():
    box = trimesh.creation.box(extents=(10, 10, 10))
    box.apply_translation((0, 0, 5))
    r = S.overhang_report(box)
    assert r["support_area"] == 0 and r["bed_area"] == pytest.approx(100, rel=1e-6)
    tee = trimesh.util.concatenate([box, _shelf()])
    assert S.overhang_report(tee)["support_area"] > 0


def _shelf():
    s = trimesh.creation.box(extents=(30, 10, 2))
    s.apply_translation((0, 0, 11))
    return s


def test_number_labels():
    m = L.number("12", height=6.0, depth=1.0)
    assert m is not None and m.volume > 0
    assert m.extents[2] == pytest.approx(1.0, abs=1e-6)
    assert L.number("", height=6.0) is None


def test_a_box_stands(tmp_path):
    pytest.importorskip("mujoco")
    pytest.importorskip("coacd")
    box = trimesh.creation.box(extents=(30, 30, 10))
    box.apply_translation((0, 0, 5))
    pieces = S.convex_pieces(box, "box", tmp_path)
    r = S.stand_test(pieces, tmp_path, seconds=1.0)
    assert r["tilt_deg"] < 5
