from base3d.nozzle import Nozzle

from card3d import labels as LB


def test_the_thinnest_stroke_scales_with_the_height():
    w4 = LB.stroke_width("6-1", height=4.0)
    w8 = LB.stroke_width("6-1", height=8.0)
    assert 0.3 < w4 < 0.7 and abs(w8 - 2 * w4) < 0.05


def test_a_printed_label_is_tall_enough_for_two_lines_of_the_nozzle():
    for nozzle in (Nozzle(0.4), Nozzle(0.2, layer=0.1), Nozzle(0.6, layer=0.3)):
        h = LB.fit_height("4A", nozzle)
        assert LB.stroke_width("4A", height=h) >= nozzle.wall - 0.01
        assert LB.stroke_width("4A", height=h - 0.5) < nozzle.wall


def test_number_grows_for_the_nozzle_and_keeps_two_layers():
    small = LB.number("P2", height=4.0, depth=0.2)
    printed = LB.number("P2", height=4.0, depth=0.2, nozzle=Nozzle(0.4))
    assert printed.extents[1] > small.extents[1] * 1.4
    assert abs(printed.extents[2] - 0.4) < 1e-6
    # a height already big enough is kept
    big = LB.number("P2", height=9.0, nozzle=Nozzle(0.4))
    assert abs(big.extents[1] - LB.number("P2", height=9.0).extents[1]) < 1e-6
