"""Fit card. One print that finds the ball-joint fit, the neck strength, the peg fit and the axle fit
of a kit by hand, before the kit itself is printed.

A ball joint can fail two ways. The socket is too tight or too loose (a fit problem), or the neck
behind the ball snaps (a strength problem). A card that only varies one of them cannot say which went
wrong. So for each ball size the card prints sockets that differ only in fit (`fits`, letters A, B,
C ...) and balls that differ only in neck thickness (`necks`, numbers 1, 2, 3 ...), and any ball
goes into any socket of its size. The fit is read off the socket's letter and the strength off the
ball's number, and a fit that is right with a neck that is too weak is fixed by trying a thicker
ball in the same socket.

Beside them it prints pegs of several heights (P1, P2 ...) with holes of several clearances (H1,
H2 ...), for a part that pushes onto a post, and short tubes with several bores (T1, T2 ...), for
an axle that must turn freely.

    from card3d.coupons import fit_card as FC
    spec = FC.FitCardSpec(ball_sizes=(4.0, 5.0, 6.0), tube_bores={"T1": 5.03, "T2": 5.33})
    pieces, info = FC.build(spec)          # {name: mesh}, {name: what it varies}
    placed = FC.layout(pieces, spec)       # one row per ball size, then pegs and holes, then tubes
    report = FC.checks(spec)               # each socket with its thinnest and thickest neck

Every piece carries a raised label sized for the nozzle (`labels.number(..., nozzle=...)`), so the
letters print as two lines and stay readable. Each socket opens upward with its rim just under the
block's top, as a socket sits in a body, and each ball lies on its side at the end of a short stub,
as a limb prints on a kit card, with a thin flat sole so it has a first layer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import trimesh
from base3d.nozzle import DEFAULT as DEFAULT_NOZZLE, Nozzle

from card3d import joints as J
from card3d import labels as LB
from card3d.coupons import ball_coupon as BC


def _fits():
    return {"A": (0.20, 1.0), "B": (0.28, 0.75), "C": (0.36, 0.5)}


def _necks():
    return {"1": 0.0, "2": 0.6, "3": 1.2}


def _pegs():
    return {"1": 3.5, "2": 5.0, "3": 6.5}


def _holes():
    return {"1": 0.20, "2": 0.30, "3": 0.40}


@dataclass(frozen=True)
class FitCardSpec:
    #: the ball diameters to test, in mm
    ball_sizes: tuple = (4.0, 5.0, 6.0)
    #: socket letter -> (gap per side in the cavity, share of the joint's default rim grip), or with
    #: `grip_mm` (gap, rim grip in mm per side). A third number adds friction ridges standing that far
    #: in from the cavity wall (`ridges`); one larger than the gap rubs the ball.
    fits: dict = field(default_factory=_fits)
    #: the second number of each fit is the rim grip itself in mm, the same for every ball size.
    #: A printed card showed the fit follows the rim's grip in mm and not the ball size: sockets with
    #: 0.07 mm of grip took their ball at every size, and at 0.088 mm or more none went in easily,
    #: while the default grip grows with the ball.
    grip_mm: bool = False
    #: ball number -> mm added to the joint's default neck (`joints.ball_neck`)
    necks: dict = field(default_factory=_necks)
    socket_wall: float = 1.6      # four lines of a 0.4 mm nozzle; 1.0 mm sockets broke on a printed kit
    socket_floor: float = 1.2     # material under the cavity
    rim_below_top: float = 0.5    # how far the rim sits under the socket block's top
    sole: float = 0.3             # flat cut under a ball lying on its side, its first layer
    stub_length: float = 14.0     # the limb stub behind each ball
    stub_extra: float = 1.2       # how much thicker than its neck the stub is
    peg_d: float = 3.0
    #: peg number -> height in mm
    pegs: dict = field(default_factory=_pegs)
    #: hole number -> diametral clearance round the peg, in mm
    holes: dict = field(default_factory=_holes)
    hole_depth: float = 7.0
    #: tube name -> bore in mm; empty for no tubes
    tube_bores: dict = field(default_factory=dict)
    tube_length: float = 9.0
    tube_wall: float = 1.6
    tube_sole: float = 0.4        # flat cut under a tube lying on its side
    nozzle: Nozzle = DEFAULT_NOZZLE
    label_height: float = 4.0     # the smallest label; it grows to two lines of the nozzle
    tab_thickness: float = 1.6


def _labelled(spec, body, text, at_xy, along=0.0):
    """A flat tab with raised text sized for the nozzle, joined to `body` with its near edge at
    `at_xy` and pointing along the angle `along` (radians) from +x."""
    txt = LB.number(text, height=spec.label_height, depth=spec.nozzle.plate, nozzle=spec.nozzle)
    tx, ty, tz = (float(v) for v in txt.extents)
    margin = spec.nozzle.lines(2)
    L, W, T = tx + 2 * margin + 0.6, ty + 2 * margin, spec.tab_thickness
    tab = trimesh.creation.box(extents=[L, W, T])
    tab.apply_translation([L / 2.0, 0.0, T / 2.0])
    txt.apply_translation(-txt.bounds.mean(axis=0))
    # the text reads upright on the card whichever way its tab points
    txt.apply_transform(trimesh.transformations.rotation_matrix(-along, [0, 0, 1]))
    txt.apply_translation([L / 2.0 + 0.3, 0.0, T + tz / 2.0])
    piece = trimesh.boolean.union([tab, txt])
    piece.apply_transform(trimesh.transformations.rotation_matrix(along, [0, 0, 1]))
    piece.apply_translation([at_xy[0], at_xy[1], 0.0])
    return trimesh.boolean.union([body, piece])


def grip_of(spec, size, letter):
    """The rim's grip per side in mm for one socket: the fit's own number with `grip_mm`, else its
    share of the joint's default for this ball size."""
    second = spec.fits[letter][1]
    return float(second) if spec.grip_mm else J.ball_grip(size) * second


#: friction ridges: how many, their width across, and how far above the ball's centre they reach, as
#: a share of its radius (they stay below the rim, which does the clicking)
RIDGES = 4
RIDGE_W = 0.8
RIDGE_TOP = 0.3


def ridges(size, gap, ridge, centre, count=RIDGES, width=RIDGE_W, phase=None):
    """Thin ridges on a ball cavity's wall that stand `ridge` mm in from it, to rub a ball that would
    otherwise turn freely in a clean print. They run from the cavity's floor to `RIDGE_TOP` of the
    radius above the ball's centre, midway between the joint's slits, so the slits can still spring."""
    R = size / 2.0
    outer = R + gap + 0.05                       # into the wall a little, so they join it
    inner = R + gap - ridge
    c = np.asarray(centre, float)
    shell = trimesh.creation.icosphere(subdivisions=4, radius=outer).difference(
        trimesh.creation.icosphere(subdivisions=4, radius=inner))
    shell.apply_translation(c)
    phase = math.pi / J.BALL_SLITS if phase is None else phase
    out = []
    for i in range(count):
        a = 2 * math.pi * i / count + phase
        slab = trimesh.creation.box(extents=[outer + 0.5, width, 2 * outer + 1.0])
        slab.apply_translation([(outer + 0.5) / 2.0, 0.0, 0.0])
        slab.apply_transform(trimesh.transformations.rotation_matrix(a, [0, 0, 1]))
        top = R * RIDGE_TOP
        cap = trimesh.creation.box(extents=[2 * outer + 2, 2 * outer + 2, outer + top])
        cap.apply_translation([0.0, 0.0, top - (outer + top) / 2.0])
        slab.apply_translation(c)
        cap.apply_translation(c)
        out.append(trimesh.boolean.intersection([shell, slab, cap]))
    return trimesh.boolean.union(out)


def socket_geometry(spec, size, letter):
    """(block without label, joint point, axis, outer radius, info). The cavity opens upward with
    its rim `rim_below_top` under the block's top, so the mouth is not a channel as long as the neck."""
    gap = spec.fits[letter][0]
    grip = grip_of(spec, size, letter)
    R = size / 2.0
    zc = spec.socket_floor + R + gap                         # the ball's centre, seated
    depth = J.ball_depth(size, gap, grip)
    H = zc + depth + spec.rim_below_top
    at = np.array([0.0, 0.0, zc + J.ball_reach(size)])
    axis = np.array([0.0, 0.0, -1.0])
    r = R + gap + spec.socket_wall + 0.6
    blk = trimesh.creation.cylinder(radius=r, height=H, sections=64)
    blk.apply_translation([0, 0, H / 2.0])
    blk = blk.difference(J.female("ball", size, axis, at, gap=gap, grip=grip, wall=spec.socket_wall))
    ridge = float(spec.fits[letter][2]) if len(spec.fits[letter]) > 2 else 0.0
    if ridge > 0:
        blk = trimesh.boolean.union([blk, ridges(size, gap, ridge, (0.0, 0.0, zc))])
    info = {"gap": gap, "grip": round(grip, 3), "top": round(H, 2)}
    if ridge > 0:
        info["ridge"] = ridge
    return blk, at, axis, r, info


def socket(spec, size, letter):
    """A block standing on the plate, its ball socket opening upward, and its label."""
    blk, _at, _axis, r, info = socket_geometry(spec, size, letter)
    return _labelled(spec, blk, f"{size:g}{letter}", (r - 0.5, 0.0)), info


def ball_centre(spec, size):
    """Where a ball piece's ball centre is, in the piece's own frame (it points along +x)."""
    return np.array([J.ball_reach(size), 0.0, size / 2.0 - spec.sole])


def ball(spec, size, num):
    """A ball on its side at the end of a limb stub, with a flat sole under both and its label behind."""
    neck = J.ball_neck(size) + spec.necks[num]
    R = size / 2.0
    zc = R - spec.sole
    m = J.male("ball", size, (1.0, 0.0, 0.0), (0.0, 0.0, zc), neck=neck, backset=2.0)
    rs = (neck + spec.stub_extra) / 2.0
    L = spec.stub_length
    stub = trimesh.creation.cylinder(radius=rs, height=L, sections=48)
    stub.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    stub.apply_translation([-L / 2.0, 0.0, zc])
    keel = trimesh.creation.box(extents=[L, rs * 1.4, zc])
    keel.apply_translation([-L / 2.0, 0.0, zc / 2.0])
    body = trimesh.boolean.union([m, stub, keel])
    floor = trimesh.creation.box(extents=[200, 200, 50])
    floor.apply_translation([0, 0, -25.0])
    body = body.difference(floor)
    body = _labelled(spec, body, f"{size:g}-{num}", (-L + 0.5, 0.0), along=np.pi)
    return body, {"neck": round(neck, 2), "stub": round(2 * rs, 2), "reach": round(J.ball_reach(size), 2)}


def peg(spec, num):
    """A peg standing on a small base, and its label."""
    h = spec.pegs[num]
    base = trimesh.creation.box(extents=[9.0, 9.0, 2.0])
    base.apply_translation([0, 0, 1.0])
    pin = trimesh.creation.cylinder(radius=spec.peg_d / 2.0, height=h, sections=48)
    pin.apply_translation([0, 0, 2.0 + h / 2.0])
    return _labelled(spec, trimesh.boolean.union([base, pin]), f"P{num}", (4.0, 0.0)), {"height": h}


def hole(spec, num):
    """A block with a blind hole opening upward, `hole_depth` deep, and its label."""
    clear = spec.holes[num]
    d = spec.peg_d + clear
    depth = spec.hole_depth
    blk = trimesh.creation.box(extents=[10.0, 10.0, depth + 1.2])
    blk.apply_translation([0, 0, (depth + 1.2) / 2.0])
    h = trimesh.creation.cylinder(radius=d / 2.0, height=depth + 1.0, sections=48)
    h.apply_translation([0, 0, 1.2 + (depth + 1.0) / 2.0])
    return _labelled(spec, blk.difference(h), f"H{num}", (4.5, 0.0)), {"clearance": clear, "hole_d": round(d, 2)}


def tube(spec, name):
    """A short tube lying on its side along y, with a flat sole, and its label."""
    bore = spec.tube_bores[name]
    L = spec.tube_length
    ro = bore / 2.0 + spec.tube_wall
    t = trimesh.creation.cylinder(radius=ro, height=L, sections=64).difference(
        trimesh.creation.cylinder(radius=bore / 2.0, height=L + 2.0, sections=64))
    t.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    t.apply_translation([0, 0, ro - spec.tube_sole])
    floor = trimesh.creation.box(extents=[50, 50, 20])
    floor.apply_translation([0, 0, -10.0])
    t = t.difference(floor)
    return _labelled(spec, t, name, (ro - 1.5, 0.0)), {"bore": round(bore, 2), "length": round(L, 2)}


def build(spec: FitCardSpec | None = None):
    """Every piece, as ({name: mesh}, {name: what it varies}). Names are "socket 5B", "ball 5-2",
    "peg P1", "hole H1" and "tube T1"."""
    spec = spec or FitCardSpec()
    pieces, info = {}, {}
    for s in spec.ball_sizes:
        for k in spec.fits:
            pieces[f"socket {s:g}{k}"], info[f"socket {s:g}{k}"] = socket(spec, s, k)
        for n in spec.necks:
            pieces[f"ball {s:g}-{n}"], info[f"ball {s:g}-{n}"] = ball(spec, s, n)
    for n in spec.pegs:
        pieces[f"peg P{n}"], info[f"peg P{n}"] = peg(spec, n)
    for n in spec.holes:
        pieces[f"hole H{n}"], info[f"hole H{n}"] = hole(spec, n)
    for t in spec.tube_bores:
        pieces[f"tube {t}"], info[f"tube {t}"] = tube(spec, t)
    return pieces, info


def layout(pieces, spec: FitCardSpec | None = None, gap: float = 4.0, max_width: float = 240.0):
    """The pieces on a card that reads as a table: one row per ball size (its sockets, then its
    balls), then the pegs and holes, then the tubes, then any other piece a project added (an axle
    to try in the tubes, say) in a last row. A row wider than `max_width` (mm) wraps onto the next
    line, so a long row of tubes still fits the plate. Each piece sits on the plate at z = 0."""
    spec = spec or FitCardSpec()
    rows = [[n for n in pieces if n.startswith((f"socket {s:g}", f"ball {s:g}-"))] for s in spec.ball_sizes]
    rows += [[n for n in pieces if n.startswith(("peg ", "hole "))], [n for n in pieces if n.startswith("tube ")]]
    placed_names = {n for row in rows for n in row}
    rows.append([n for n in pieces if n not in placed_names])
    placed, y = {}, 0.0
    for row in rows:
        x, row_h = 0.0, 0.0
        for name in row:
            m = pieces[name].copy()
            lo, hi = m.bounds
            if x > 0 and x + (hi[0] - lo[0]) > max_width:   # the row would leave the plate: wrap it
                x, y = 0.0, y + row_h + gap
                row_h = 0.0
            m.apply_translation([x - lo[0], y - lo[1], -lo[2]])
            placed[name] = m
            x += hi[0] - lo[0] + gap
            row_h = max(row_h, hi[1] - lo[1])
        if row:
            y += row_h + gap
    return placed


def check_pair(spec, size, letter, num, min_turn=30):
    """One socket with one ball, measured on the socket as it prints: pushed in it meets only the
    rim, it resists being pulled out, and it tilts at least `min_turn` degrees all round."""
    sock, at, axis, _r, _info = socket_geometry(spec, size, letter)
    neck = J.ball_neck(size) + spec.necks[num]
    R = size / 2.0
    grip = grip_of(spec, size, letter)
    ballm = J.male("ball", size, axis, at, backset=3.0, neck=neck)
    c = at + axis * J.ball_reach(size)
    squeeze, _where = J.push_in(sock, size, axis, at)
    held = 0.0
    for d in np.arange(0.0, R * 1.2, R * 0.12):
        b = ballm.copy()
        b.apply_translation(-axis * float(d))
        held = max(held, abs(sock.intersection(b).volume))
    free = 0
    for deg in (10, 15, 20, 25, 30, 35, 40, 45):
        worst = 0.0
        for az in range(0, 360, 45):
            T = (trimesh.transformations.rotation_matrix(np.radians(az), [0, 0, 1], c)
                 @ trimesh.transformations.rotation_matrix(np.radians(deg), [1, 0, 0], c))
            b = ballm.copy()
            b.apply_transform(T)
            worst = max(worst, abs(sock.intersection(b).volume))
        if worst >= 1.0:
            break
        free = deg
    goes_in = squeeze <= grip * BC.PUSH_IN_SLACK + 0.02
    return {"ok": bool(goes_in and held > 0.05 and free >= min_turn), "turns_deg": free,
            "push_in_mm": round(float(squeeze), 3), "holds_mm3": round(float(held), 3), "grip": round(grip, 3)}


def checks(spec: FitCardSpec | None = None):
    """Every socket with the thinnest and the thickest neck of its size."""
    spec = spec or FitCardSpec()
    ends = (next(iter(spec.necks)), list(spec.necks)[-1])
    return {f"{s:g}{k} with ball {s:g}-{n}": check_pair(spec, s, k, n)
            for s in spec.ball_sizes for k in spec.fits for n in dict.fromkeys(ends)}


def main():
    """Write the default card as fit-card.stl in the current folder and print its checks."""
    import pathlib
    spec = FitCardSpec(tube_bores={"T1": 5.0, "T2": 5.3, "T3": 5.6})
    pieces, _info = build(spec)
    card = trimesh.util.concatenate(list(layout(pieces, spec).values()))
    card.export(pathlib.Path.cwd() / "fit-card.stl")
    print("fit-card.stl", [round(float(v), 1) for v in card.extents], "mm,", len(pieces), "pieces")
    for k, v in checks(spec).items():
        print(f"  {k:22s} {'ok ' if v['ok'] else 'BAD'} turns {v['turns_deg']:2d} deg")


if __name__ == "__main__":
    main()
