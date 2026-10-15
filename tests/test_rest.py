import numpy as np
import trimesh

from card3d import tosprue as T


def _wheel():
    """A wheel 11.8 mm across and 7 mm wide on a 3 mm bore, its axle along y."""
    rim = trimesh.creation.cylinder(radius=5.9, height=7.0, sections=96)
    bore = trimesh.creation.cylinder(radius=1.5, height=9.0, sections=48)
    w = rim.difference(bore)
    w.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return w


def test_a_named_face_is_the_one_that_rests_on_the_plate(monkeypatch):
    monkeypatch.setattr(T, "REST", {"wheel": [[0.0, 1.0, 0.0]]})
    out, log = T.seated({"wheel": _wheel()}, [])
    w, rec = out["wheel"], log[0]
    assert rec["rest"] == "named"
    assert rec["sole_mm"] == 0.0                       # its side is flat, so nothing is cut
    assert abs(float(w.extents[2]) - 7.0) < 0.05       # lying on its side, axle upright
    # the tread is whole: every point of the rim is still 5.9 mm from the axle
    c = w.bounds.mean(axis=0)
    r = np.linalg.norm(np.asarray(w.vertices)[:, :2] - c[:2], axis=1)
    assert abs(float(r.max()) - 5.9) < 0.02
    assert float(np.sort(r)[-96:].min()) > 5.85


def test_a_part_not_named_is_scored_as_before(monkeypatch):
    monkeypatch.setattr(T, "REST", {"something else": [[0.0, 0.0, 1.0]]})
    _out, log = T.seated({"wheel": _wheel()}, [])
    assert log[0]["rest"] == "scored"
