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
