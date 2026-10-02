"""Round-trip check for a kit card. Cuts the gates and confirms every part comes back intact.

A kit exists in three forms, and this module checks that they agree.

    parts  --nest+gate-->  card  --cut gates-->  pieces  --place-->  assembly

Checking each form on its own is not enough. The parts can be manifold, the card can be one body
and the assembly can stand, while the card still does not contain the parts correctly. A gate in
the wrong place, two parts nested so they overlap, or a slot clipped by the nesting all pass those
separate checks. Going through the full loop catches them, because the pieces recovered from the
card are the ones a person would hold.

The cut is real geometry, not an assumption. Each gate is subtracted where the card generator
placed it, and the card is then split into connected bodies, as nippers would do. If a piece comes
back joined to its neighbour, in two halves, or not at all, the count is wrong and the report names
the part.

Recovered pieces are matched to parts by shape, not by order. `split()` returns bodies in an
arbitrary order, so each piece is matched by cross-sectional area and bounding box. Matching by
index would pass a card whose pieces had been swapped.
"""
import pathlib

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).parent

GATE_CUT = 2.2          # width of the cut, mm. The gate is 1.6 mm, plus a margin each side
AREA_TOL = 0.04         # a recovered piece may differ from its part by this fraction of area
# A piece loses some extent where its gate is cut, so the bounding-box tolerance must be at least
# half the cut width. A piece with 0.4% of its area missing is whole for practical purposes, but
# its bounding box can be 0.63 mm shorter than the modelled part. The cut is GATE_CUT wide across
# the part's lowest point, so up to half of it removes extent. Deriving the tolerance from GATE_CUT
# keeps it correct if the cut width changes.
BBOX_TOL = GATE_CUT / 2 + 0.3          # mm, on each in-plane dimension

# The area tolerance also has to scale with part size. A gate stub is the same size whatever it is
# attached to, so it is 1% of a 2000 mm2 plate and 12% of a 40 mm2 part. One fixed tolerance would
# pass every large part and fail every small one, so parts below SMALL_MM2 get a looser tolerance.
SMALL_MM2 = 150.0
SMALL_AREA_TOL = 0.35
DUST_MM2 = 2.0          # a recovered fragment below this area is left over from a gate cut, not a part


def _footprint(mesh):
    """Return the cross-sectional area and in-plane size at mid thickness of a flat piece."""
    z = (mesh.bounds[0][2] + mesh.bounds[1][2]) / 2
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return 0.0, (0.0, 0.0)
    p2, _T = sec.to_2D()
    area = sum(g.area for g in p2.polygons_full)
    b = mesh.bounds[1] - mesh.bounds[0]
    return float(area), (float(b[0]), float(b[1]))


def snip(card_mesh, gates, plate, verbose=False):
    """Cut every gate and return the resulting pieces, frame included.

    A gate is a span, not a point. The card generator records `(name, x, bar_y, top)`, and the
    gate runs in Y from the row bar up to where it meets the part. A cut placed at `bar_y` alone
    lands on the bar, severs nothing, and returns the card in one piece. That result looks like a
    broken card when the fault is in the test, so the cut covers the whole span.
    """
    cutters = []
    for g in gates:
        x = float(g[1])
        y0, y1 = float(g[2]), float(g[3])
        mid, span = (y0 + y1) / 2, abs(y1 - y0)
        # The cutter must be close to the gate width, not much wider. A 3 mm cutter on a 1.6 mm
        # gate removes 3 mm from the part it is attached to, and on a 7 mm wheel with two gates
        # that is most of the part, so the part is reported missing.
        # The cutter must also cover the whole gate. Cutting only 80% of the span leaves a 0.35 mm
        # sliver at each end. That is enough to keep a small part attached, and the part is then
        # reported as never released from the card. The extra 1.0 mm on the span prevents this.
        box = trimesh.creation.box(extents=[GATE_CUT, span + 1.0, plate * 3])
        box.apply_translation([x, mid, plate / 2])
        cutters.append(box)
    cut = trimesh.util.concatenate(cutters)
    opened = card_mesh.difference(cut)
    if verbose:
        print(f"    snip: card {card_mesh.volume:.0f} mm3 -> {opened.volume:.0f} mm3 "
              f"across {len(cutters)} gates")
    return opened.split(only_watertight=False)


def check(parts, card_mesh, gates, plate):
    """Cut the card and report which parts came back whole and which did not.

    Returns a dict with the number of loose pieces, the matched parts, the missing parts, any
    pieces that match no part, the count of small fragments, and an overall "ok" flag.
    """
    want = {n: _footprint(m) for n, m in parts.items()}
    pieces = snip(card_mesh, gates, plate, verbose=True)
    got = [(_footprint(p), p) for p in pieces]

    # the frame is the piece with the largest bounding box, and every other piece should be a part
    frame_i = max(range(len(got)), key=lambda i: got[i][0][1][0] * got[i][0][1][1])
    # Fragments below DUST_MM2 are left over from gate cuts, not parts. A cut can leave a 0.4 mm2
    # fragment, and reporting it as an unidentified piece would hide a real failure among noise.
    # These are counted but not matched.
    loose = [g for i, g in enumerate(got) if i != frame_i and g[0][0] >= DUST_MM2]
    dust = len(got) - 1 - len(loose)

    unmatched = dict(want)
    matched, wrong = {}, []
    for (area, size), mesh in loose:
        best, score = None, None
        for n, (wa, ws) in unmatched.items():
            if wa <= 0:
                continue
            da = abs(area - wa) / wa
            db = max(abs(size[0] - ws[0]), abs(size[1] - ws[1]))
            s = da + db / 10.0
            if score is None or s < score:
                best, score = n, s
        if best is None:
            wrong.append(("extra piece", area, size))
            continue
        wa, ws = unmatched[best]
        da = abs(area - wa) / wa if wa else 1.0
        db = max(abs(size[0] - ws[0]), abs(size[1] - ws[1]))
        tol_a = SMALL_AREA_TOL if wa < SMALL_MM2 else AREA_TOL
        tol_b = BBOX_TOL + (2.0 * GATE_CUT if wa < SMALL_MM2 else 0.0)
        if da <= tol_a and db <= tol_b:
            matched[best] = (area, size, len(mesh.split(only_watertight=False)))
            del unmatched[best]
        else:
            wrong.append((f"{best}?", area, size))
    return {"pieces": len(loose), "matched": matched, "missing": list(unmatched),
            "wrong": wrong, "dust": dust,
            "ok": not unmatched and not wrong}


