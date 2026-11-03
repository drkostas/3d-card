import numpy as np
import trimesh

from card3d import tosprue as T

from test_card import _twin_kit


def _record(got):
    """Everything a nested build decides, in plain values, to compare two builds."""
    def m(x):
        return np.asarray(x, float)
    return {
        "moved": {n: m(v) for n, v in got["moved"].items()},
        "to_card": {n: m(v) for n, v in got["to_card"].items()},
        "parts": {n: (m(p.vertices), np.asarray(p.faces)) for n, p in got["parts"].items()},
        "gates": [(g[0],) + tuple(m(v) for v in g[1:]) for g in got["gates"]],
        "gate_axes": [m(a) for a in got["gate_axes"]],
        "tags": {n: m(b) for n, b in got["tags"].items()},
        "holds": {n: m(h) for n, h in got["holds"].items()},
        "card": (m(got["card"].vertices), np.asarray(got["card"].faces)),
        "same": (got["numbers"], got["crowded_tags"], got["weak"], got["notes"], got["off_reading"],
                 got["bodies"], got["fits_bed"], got["packed"], m(got["size"]), got["first_layer_mm2"]),
    }


def _assert_same(a, b, path="got"):
    if isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _assert_same(a[k], b[k], f"{path}[{k!r}]")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _assert_same(x, y, f"{path}[{i}]")
    elif isinstance(a, np.ndarray):
        assert a.shape == b.shape, path
        if a.dtype.kind == "f":
            assert np.allclose(a, b, rtol=0.0, atol=1e-9), path
        else:
            assert np.array_equal(a, b), path
    elif isinstance(a, float):
        assert abs(a - b) <= 1e-9, path
    else:
        assert a == b, path


def _build(monkeypatch, size, source, **kw):
    monkeypatch.setattr(T, "OUTLINE_CACHE", size)
    T.clear_outline_cache()
    return T.build(verbose=False, source=source, nest=True, **kw)


def test_a_nested_card_is_the_same_with_and_without_the_outline_cache(monkeypatch, kit):
    # several nest tries, so the later tries are served from the cache
    monkeypatch.setattr(T, "NEST_TRIES", 3)
    calls = []
    fresh = T._footprint
    monkeypatch.setattr(T, "_footprint", lambda m: calls.append(1) or fresh(m))
    for source, kw in ((_twin_kit(), {"nest_width": 45.0, "seat": False}),
                       (kit, {"nest_width": 60.0, "plate": "KIT"})):
        calls.clear()
        off = _record(_build(monkeypatch, 0, source, **kw))
        uncached = len(calls)
        calls.clear()
        on = _record(_build(monkeypatch, 1024, source, **kw))
        _assert_same(off, on)
        assert len(calls) < uncached / 2, (len(calls), uncached)


def test_a_changed_mesh_gets_its_own_outline():
    T.clear_outline_cache()
    box = trimesh.creation.box(extents=(10.0, 4.0, 3.0))
    first = T.footprint(box)
    assert np.allclose(first.max(axis=0) - first.min(axis=0), (10.0, 4.0))
    # edited in place, the same object must not get the old outline back
    box.vertices[:, 0] *= 2.0
    assert np.allclose(np.ptp(T.footprint(box), axis=0), (20.0, 4.0))
    box.apply_translation((5.0, -3.0, 0.0))
    got = T.footprint(box)
    assert np.allclose(got.min(axis=0), (-5.0, -5.0)) and np.allclose(got.max(axis=0), (15.0, -1.0))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 0, 1)))
    assert np.allclose(np.ptp(T.footprint(box), axis=0), (4.0, 20.0))
    # and every answer is the one a fresh projection gives
    assert np.array_equal(T.footprint(box), T._footprint(box)[0])


def test_the_returned_outline_cannot_change_the_kept_one():
    T.clear_outline_cache()
    disc = trimesh.creation.cylinder(radius=5.0, height=2.0, sections=32)
    a = T.footprint(disc)
    a += 100.0
    assert np.allclose(T.footprint(disc), T._footprint(disc)[0])
