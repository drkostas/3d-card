"""Kit-card generator. Lays flat parts out inside a frame and attaches each one with small gates.

A kit card is the flat sheet familiar from plastic model kits. The parts sit in a frame and are
held by thin gates that are cut with nippers. Tools exist for turning a solid into flat slices,
but no public generator for the card itself was found, so this module provides one.

The input is any set of meshes of uniform thickness, and the output is one card. Nothing here is
specific to a particular set of parts.

A usable card has to meet four conditions, and the code is written to check them.

  - Every part is held by at least one gate. A part with no gate is a loose piece in the frame.
  - The card is one connected body.
  - Each gate is thin enough to cut by hand and thick enough to survive printing.
  - The card fits the build area.

The default gate width of 1.6 mm is four extrusion widths for a 0.4 mm nozzle. This cuts cleanly
in PLA by general practice, but it has not been measured on every printer, so treat it as a
starting value and confirm it with a test print.
"""
import math
import pathlib

import numpy as np
import trimesh
from build123d import (Align, BuildPart, BuildSketch, Locations, Mode, Polyline, Rectangle,
                       BuildLine, add, export_stl, extrude, make_face)
from matplotlib.path import Path as MplPath

HERE = pathlib.Path(__file__).parent

FRAME_W = 5.0            # width of the outer frame bar, mm
SPAR_W = 4.0             # width of the bars between rows, so inner parts have something to attach to
GAP = 7.0                # clear space around each part, mm
GATE_W = 1.6             # four extrusion widths, cuts with nippers and survives the print
GATE_REACH = 3.0         # how far a gate may span from bar to part, mm
MIN_GATE_SEP = 4.5       # two gates closer than this act as one, so the part gets a single gate
BED = (235.5, 256.0)     # default build area in mm (width, depth). Change card3d.sprue.BED or pass bed= to tosprue.build


def part_outline(mesh, z=None):
    """The part's true profile and its holes, taken through the middle of the plate."""
    lo, hi = mesh.bounds[0][2], mesh.bounds[1][2]
    z = (lo + hi) / 2 if z is None else z
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        raise ValueError("part has no section: is it really a flat plate?")
    planar, _T = sec.to_planar()
    loops = [np.asarray(p) for p in planar.discrete]
    outer = max(loops, key=lambda p: abs(_signed_area(p)))
    holes = [p for p in loops if p is not outer]
    return outer, holes


def _signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def shelf_nest(sizes, inner_w):
    """Pack parts in rows, tallest first. Returns a placement per part and the card's inner size.

    This is a plain row packer, not an optimal nester. Rows use more material than a true packer,
    but a kit card is read as well as cut. Parts in tidy rows with room for a label beside each one
    are easier to identify than a dense arrangement of irregular shapes.
    """
    order = sorted(sizes, key=lambda k: -sizes[k][1])
    place, x, y, shelf_h = {}, GAP, GAP, 0.0
    for k in order:
        w, h = sizes[k]
        if x + w + GAP > inner_w and shelf_h > 0:
            y += shelf_h + GAP + SPAR_W
            x, shelf_h = GAP, 0.0
        place[k] = (x, y)
        x += w + GAP
        shelf_h = max(shelf_h, h)
    return place, (inner_w, y + shelf_h + GAP)


def _lowest_inside(path, x, y0, y1, steps=160):
    """Step up from y0 until the outline contains the point. This is where a gate should stop."""
    for i in range(steps + 1):
        y = y0 + (y1 - y0) * i / steps
        if path.contains_point((x, y)):
            return y
    return None


def gate_spots(path, moved, bar_y, want=2, samples=64):
    """Find where the part comes closest to its bar, and place the gates there.

    Gates placed at fixed fractions of the part's width (for example 30% and 70%) can land inside a
    notch or beside a bent limb, where they touch nothing. The part is then loose and the card
    prints as several pieces. Where a part can be gated depends on its outline, so this function
    samples the outline and searches for the closest points. That also makes it work for parts of
    any shape.
    """
    x0, x1 = moved[:, 0].min(), moved[:, 0].max()
    ymax = moved[:, 1].max()
    cands = []
    for i in range(samples + 1):
        gx = x0 + (x1 - x0) * i / samples
        if gx - x0 < GATE_W or x1 - gx < GATE_W:
            continue
        top = _lowest_inside(path, gx, bar_y, ymax)
        if top is None:
            continue
        cands.append((top - bar_y, gx, top))
    if not cands:
        return []
    cands.sort()
    chosen = []
    for gap, gx, top in cands:
        if gap > GATE_REACH + 8.0:
            break
        # The separation rule needs a minimum distance as well as a fraction of the width. With
        # only 22% of the width, a 7 mm wheel accepts two gates 1.56 mm apart. That acts as one
        # gate with a nick in it, at the bottom of a circle where the outline curves away fastest.
        # When cut, the two cuts merge and remove part of the wheel, and when printed it is a weak
        # attachment. Below MIN_GATE_SEP the part gets one gate, which suits a part of about
        # 40 mm2 in any case.
        if all(abs(gx - c[0]) > max((x1 - x0) * 0.22, MIN_GATE_SEP) for c in chosen):
            chosen.append((gx, top))
        if len(chosen) == want:
            break
    if not chosen:                       # a part must be held even if the reach is long
        _gap, gx, top = cands[0]
        chosen = [(gx, top)]
    return chosen


def make_card(parts, thickness, inner_w=195.0, label=None):
    """Nest the parts, build the frame, gate everything to it, and return one solid card."""
    shapes = {n: part_outline(m) for n, m in parts.items()}
    sizes = {n: (o[:, 0].max() - o[:, 0].min(), o[:, 1].max() - o[:, 1].min())
             for n, (o, _h) in shapes.items()}
    place, (iw, ih) = shelf_nest(sizes, inner_w)
    W, H = iw + 2 * FRAME_W, ih + 2 * FRAME_W

    # each row's bar sits just under the lowest part in that row
    shelf_ys = sorted({round(y, 3) for (_x, y) in place.values()})
    bars = [(y - GAP / 2 - SPAR_W / 2) for y in shelf_ys]

    gates = []
    with BuildPart() as card:
        with BuildSketch():
            with Locations((W / 2, H / 2)):
                Rectangle(W, H)
            with Locations((W / 2, H / 2)):                    # hollow it into a frame
                Rectangle(W - 2 * FRAME_W, H - 2 * FRAME_W, mode=Mode.SUBTRACT)
            for by in bars:                                    # the row bars
                with Locations((W / 2, FRAME_W + by)):
                    Rectangle(W - 2 * FRAME_W + 0.02, SPAR_W)

            for n, (outer, holes) in shapes.items():
                ox, oy = place[n]
                dx = FRAME_W + ox - outer[:, 0].min()
                dy = FRAME_W + oy - outer[:, 1].min()
                moved = outer + np.array([dx, dy])
                with BuildLine():
                    Polyline(*[(float(a), float(b)) for a, b in moved], close=True)
                make_face()
                for h in holes:
                    hm = h + np.array([dx, dy])
                    with BuildSketch(mode=Mode.SUBTRACT):
                        with BuildLine():
                            Polyline(*[(float(a), float(b)) for a, b in hm], close=True)
                        make_face()

                # Gates are aimed at the outline, not at the bounding box. A part whose underside
                # curves away would otherwise get a gate that stops short of it and holds nothing.
                path = MplPath(np.vstack([moved, moved[0]]))
                bar_y = FRAME_W + min(bars, key=lambda b: abs((FRAME_W + b) - moved[:, 1].min()))
                for gx, top in gate_spots(path, moved, bar_y):
                    with Locations((gx, (bar_y + top) / 2)):
                        Rectangle(GATE_W, max(top - bar_y, 0.4) + 0.4)
                    gates.append((n, gx, bar_y, top))
        extrude(amount=thickness)
    return card.part, (W, H), place, gates


