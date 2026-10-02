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
