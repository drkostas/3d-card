"""Joint templates for parts that are printed separately and pushed together by hand.

Every joint is an instance of a named template (peg, axle, pivot, ball, tab, lap). Each template has
one free dimension, `size`, and every other dimension is derived from it and from the measured
clearances below. Joints built this way stay consistent with each other, can be checked, and can be
regenerated at another scale.

`male` builds the feature that sticks out and `female` builds the cutter for the matching hole. The
female feature is the male feature plus the clearance, so changing a clearance in one place refits
every joint.

Clearances are measured, not chosen. They come from fit coupons printed on a real printer, and a
different printer or material should be measured again before use.
"""
import math

import numpy as np
import trimesh

# The two base numbers every joint is cut from, measured with fit coupons in PLA on the reference
# printer. Measure your own before building on another printer.
CLEAR = 0.30              # mm of running clearance
PLATE = 1.60              # mm, the card thickness

# A joint is a point, an axis and one of these templates. `size` is the template's one free
# dimension in mm. Everything else is derived, which keeps the set consistent.
TEMPLATES = {
    "peg": {
        "label": "Peg and socket",
        "size": 3.0, "range": (1.6, 8.0),
        "holds": "still",
        "about": "A round peg on one part, a socket on the other, like a toy-figure joint. Pushes "
                 "together, pulls apart, does not rotate once seated because the socket bottoms out.",
    },
    "axle": {
        "label": "Axle (turns)",
        "size": 2.4, "range": (1.2, 6.0),
        "holds": "turns",
        "about": "A round pin with clearance all round so the other part spins on it. Use it for "
                 "wheels and anything else that must spin freely. The rotation check is about this joint.",
    },
    "pivot": {
        "label": "Pivot (turns and holds)",
        "size": 3.4, "range": (2.0, 8.0),
        "holds": "turns and stays",
        "about": "A plain round post in a plain round hole, with enough grip to hold a pose and "
                 "enough freedom to be turned by hand. Use it for "
                 "posable limbs, which have to be moved again after the toy is assembled.",
    },
    "ball": {
        "label": "Ball and socket",
        "size": 5.0, "range": (3.0, 10.0),
        "holds": "poseable",
        "about": "A ball on one part in a cup on the other: the joint that lets a limb be posed "
                 "after assembly rather than only at assembly.",
    },
    "tab": {
        "label": "Tab and slot",
        "size": 6.0, "range": (3.0, 16.0),
        "holds": "still",
        "about": "A flat tongue of card thickness into a matching slot. The joint a flat kit is "
                 "made of, and the one that survives being punched out of a card.",
    },
    "lap": {
        "label": "Cross lap",
        "size": 10.0, "range": (4.0, 30.0),
        "holds": "still",
        "about": "Two plates notched halfway so they pass through each other at right angles. "
                 "Holds itself square with no peg at all.",
    },
}

SOCKET_DEPTH = 1.15       # how much deeper the hole is than the peg, so it always bottoms out
AXLE_PLAY = 0.45          # extra all round on a turning joint, on top of CLEAR
# Pivot clearance, measured with a coupon of six levers at 0.15, 0.20, 0.25, 0.30, 0.35 and 0.40 mm.
# Each lever carries a matching number of notches so the coupon stays readable later. 0.20 mm gave
# the best balance between turning by hand and holding a pose.
#
# This is tighter than the 0.30 mm published for pose-holding joints (UCL's JointFit), which also
# reports that 0.20 mm fuses. That figure is for print-in-place joints, where the two faces are
# printed against each other and a 0.20 mm gap welds shut. A joint pushed together after printing
# cannot fuse. For that case Formlabs' assembled ball-and-socket results apply. They report that
# 0.0 to 0.2 mm moves smoothly and holds position, which matches the coupon.
PIVOT_CLEAR = 0.20        # measured: second hole on the printed pivot coupon

# ----------------------------------------------------------------- the ball joint
# Two kinds of turning joint. A ball gives two degrees of freedom and a pivot gives one. Use a ball
# where a part has to be twisted in any direction and a pivot where it only has to rotate.
#
# A socket that is a full spherical cavity, whose only opening is the stem bore, cannot be
# assembled. The bore is narrower than the ball, so the ball has no way in. That geometry only works
# for print-in-place joints. For parts printed flat and separately, the socket needs a mouth
# narrower than the ball, plus slits so the mouth can spring over it. The narrow mouth gives the
# retention and the slits let the ball pass it. That is what makes it a snap fit.
BALL_TRUNC_DEG = 70.0     # how much of the sphere survives, measured from the equator
BALL_CLEAR = PIVOT_CLEAR  # per side, in the cavity, the same measured value as the pivot
# A fixed cup depth leaves a small ball with almost no grip. The rim radius is
# sqrt((R+clear)^2 - depth^2), and the clearance is a constant 0.20 mm, so it takes a bigger share
# of a small ball. At depth 0.55R a 6 mm ball gripped by 0.258 mm a side and a 3 mm ball by
# 0.014 mm, which is less than one layer and would not hold. Joints of 2.4 to 4.5 mm are common,
# so the small end is the normal case.
#
# So the grip is the input and the depth is derived. Choose the interference wanted, then reach as
# far past the equator as that requires.
BALL_GRIP_MM = 0.12       # least interference worth having: about half a layer line
BALL_GRIP_FRAC = 0.07     # or this much of the radius on a bigger ball, whichever is more


def ball_grip(size):
    """How much the rim must spring, per side, for this ball to pass it."""
    return max(BALL_GRIP_MM, (size / 2.0) * BALL_GRIP_FRAC)


def ball_depth(size, gap=None):
    """How far past the equator the cup has to reach to achieve that grip."""
    R = size / 2.0
    gap = BALL_CLEAR if gap is None else gap
    want = R - ball_grip(size)                       # the rim radius we need
    d2 = (R + gap) ** 2 - want ** 2
    # never so deep that the cup closes over the ball and cannot be sprung at all
    return float(min(math.sqrt(max(d2, 1e-9)), (R + gap) * 0.80))
BALL_NECK = 0.34          # neck diameter, and its length, as a fraction of the ball's diameter
BALL_WALL = 1.00          # material left around the cavity, so the socket has something to spring
BALL_SLITS = 4            # relief cuts through the mouth
BALL_SLIT_W = 0.55        # each slit's width, wider than a nozzle so the slicer draws it


def ball_reach(size):
    """The default distance from the joint point to the ball's centre."""
    return size * BALL_NECK + size / 2.0


def ball_centre(size, axis, at, reach=None):
    """Where the ball's centre sits: down the axis from the joint point.

    Both halves of the joint must agree on this or the socket is cut in the wrong place, so it is
    one function rather than the same arithmetic in two places.

    The default reach is not always enough. The joint point sits on the child part's own end face,
    and the two parts do not necessarily touch. If the parent's surface is, for example, 4.37 mm away,
    a ball placed 2.9 mm along the axis is still 1.5 mm outside the parent, and shows as a stalk with
    a knob on it. Pass `reach` when the distance to the parent is known. The neck grows to span the
    gap.
    """
    a = np.asarray(axis, float)
    n = np.linalg.norm(a)
    a = np.array([0.0, 0.0, 1.0]) if n < 1e-9 else a / n
    return np.asarray(at, float) + a * (ball_reach(size) if reach is None else float(reach))
# A peg that starts exactly at the joint point is a loose stub. The joint sits on the receiving
# part's surface, and the part carrying the peg can be a little way back from it, so a feature built
# only forwards floats in the gap and the union leaves two separate bodies. The male feature is
# extended backwards by this much so it is buried in its own part.
BACKSET = 3.5


def _weld(pieces):
    """One solid out of several overlapping ones, by a real boolean union.

    `trimesh.util.concatenate` is not a union. It appends vertices and faces, so two overlapping
    spheres stay two complete shells with their intersecting surfaces still in the mesh. Used as a
    cutter, that leaves internal walls. The result can still report `is_watertight`, so a
    watertightness check does not catch the mistake. Concatenation is only the fallback when the
    boolean fails.
    """
    pieces = [p for p in pieces if p is not None and len(p.faces)]
    if not pieces:
        return None
    if len(pieces) == 1:
        return pieces[0].copy()
    try:
        out = trimesh.boolean.union(pieces)
        if out is not None and len(out.faces):
            return out
    except Exception:
        pass
    return trimesh.util.concatenate(pieces)      # last resort, and the result will look wrong


def _axis_frame(axis):
    """A rotation that takes +Z onto `axis`. Every feature below is modelled along Z."""
    a = np.asarray(axis, float)
    n = np.linalg.norm(a)
    a = np.array([0.0, 0.0, 1.0]) if n < 1e-9 else a / n
    return trimesh.geometry.align_vectors([0.0, 0.0, 1.0], a)


def male(kind, size, axis, at, length=None, backset=None):
    """The feature that sticks out, at nominal size.

    `backset` is the buried part of the feature and a fit check must not include it. It exists so
    the feature merges into the part that carries it, and it sits inside that part's own material.
    Sweeping it into the socket asks whether the root of the peg fits through the hole, which it
    never has to, and reports a sound joint as blocked. Pass `backset=0` to get only the part that
    enters the socket.
    """
    L = length if length is not None else _default_length(kind, size)
    back = BACKSET if backset is None else backset
    if kind == "ball":
        # Truncated at both poles, never split at the equator. A ball halved at its equator puts
        # both first layers and the seam on the band the socket grips. A first layer flares
        # 0.15 to 0.25 mm per side while the whole clearance budget is 0.1 to 0.3 mm, so the seam
        # uses up the budget. Two polar flats cost little. At 70 degrees from the equator the flat
        # is 0.34 of the diameter across and removes 3% of the radius, under one layer at this
        # size, and it gives the print a face to sit on.
        R = size / 2.0
        keep = R * math.sin(math.radians(BALL_TRUNC_DEG))
        m = trimesh.creation.icosphere(subdivisions=3, radius=R)
        box = trimesh.creation.box(extents=[size * 3, size * 3, keep * 2])
        m = m.intersection(box)
        reach = ball_reach(size) if length is None else float(length)
        neck_d = size * BALL_NECK
        neck_l = reach + back + keep
        stem = trimesh.creation.cylinder(radius=neck_d / 2.0, height=neck_l)
        # the neck runs from inside the child's own material up to the middle of the ball
        stem.apply_translation([0, 0, -neck_l / 2.0])
        m = _weld([m, stem])
        # put the ball's centre where `ball_centre` says it is, measured from the joint point
        m.apply_translation([0, 0, reach])
    elif kind in ("peg", "axle", "pivot"):
        m = trimesh.creation.cylinder(radius=size / 2.0, height=L + back)
        m.apply_translation([0, 0, (L - back) / 2.0])
    elif kind in ("tab", "lap"):
        m = trimesh.creation.box(extents=[size, PLATE, L + back])
        m.apply_translation([0, 0, (L - back) / 2.0])
    else:
        raise KeyError(kind)
    m.apply_transform(_axis_frame(axis))
    m.apply_translation(at)
    return m


def female(kind, size, axis, at, length=None, slit_phase=0.0):
    """The feature that is cut away: the male feature plus the clearance the printer needs.

    `slit_phase` turns the ball socket's relief slits about the joint axis, in radians. Without it
    the slits point wherever `_axis_frame` happens to put them. On a part that is thinner in one
    direction, two of the four slits then point into the thin side, where they can break through the
    outer wall (for example, slits reaching 2.70 mm from the axis in a part with 2.38 mm of material)
    or cut the wall around the socket into thin prongs. Choose the phase that keeps them in thick
    material. The pattern is four-fold symmetric, so the useful range is 0 to pi/2.
    """
    L = length if length is not None else _default_length(kind, size)
    gap = (PIVOT_CLEAR if kind == "pivot" else CLEAR) + (AXLE_PLAY if kind == "axle" else 0.0)
    if kind == "ball":
        # The cut is the cavity the ball turns in, the mouth it is pushed through, the channel the
        # neck sweeps as the part is twisted, and the slits that let the mouth open to admit it.
        R = size / 2.0
        c = ball_reach(size) if length is None else float(length)   # ball centre, from the joint point
        gap = BALL_CLEAR
        # A cylindrical mouth through a full spherical cavity cannot retain anything. The cavity is
        # the ball plus clearance, so at every height it is wider than the ball. The band where a
        # bore of radius m is narrower than the cavity is the same band where it is narrower than
        # the ball, so the lip never touches. Probed along the axis it reads free at every height
        # and the retention volume is 0.00 mm3.
        #
        # Instead the cup itself is the mouth. It wraps past the ball's equator and stops, so its
        # rim is narrower than the ball by construction and no separate mouth feature is needed.
        depth = ball_depth(size)                      # derived from the grip we need, not fixed
        cav = trimesh.creation.icosphere(subdivisions=3, radius=R + gap)
        keep = trimesh.creation.box(extents=[size * 4, size * 4, (R + gap) * 2])
        keep.apply_translation([0, 0, (R + gap) - depth])
        cav = cav.intersection(keep)
        cav.apply_translation([0, 0, c])
        mouth_r = math.sqrt(max((R + gap) ** 2 - depth ** 2, 1e-9))    # the rim, and the retention

        # The neck needs room to swing, or the joint has two degrees of freedom on paper and none in
        # practice. Below the rim the cut opens into a cone. That is the volume the neck sweeps as
        # the part is twisted, and it also works as a lead-in that guides the ball to the rim
        # during assembly.
        swing = trimesh.creation.cone(radius=R * 1.35, height=(c + R))
        swing.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
        swing.apply_translation([0, 0, c - depth])

        # Union, not concatenate. With `util.concatenate` the cutters stay separate interpenetrating
        # shells, the difference leaves walls where they overlap, and the socket comes out with
        # sealed internal voids and phantom interference (46 mm3 in one case). A cutter has to be
        # one solid before it can cut. A body count or watertight flag does not reveal this.
        m = _weld([cav, swing])

        # Slits, so the mouth can spring open far enough to pass the ball and close behind it. A
        # solid socket with a mouth 14% under the ball does not flex. It either splits during
        # assembly or refuses the ball.
        #
        # A slit must not cross the axis. Cut as a box through the full diameter, two slits at right
        # angles divide the cup into separate pieces. Like a collet, each slit runs inward from the
        # rim and stops short of the centre, so the fingers stay joined to the cup.
        outer = R + gap + BALL_WALL
        for i in range(BALL_SLITS):
            a = 2 * math.pi * i / BALL_SLITS + float(slit_phase)
            span = outer - mouth_r * 0.55            # rim inwards, stopping inside the mouth wall
            s = trimesh.creation.box(extents=[BALL_SLIT_W, span, R * 1.35])
            # slide it out along +Y so its inner end stops short of the axis, then swing it round
            s.apply_translation([0.0, mouth_r * 0.55 + span / 2.0, 0.0])
            s.apply_transform(trimesh.transformations.rotation_matrix(a, [0, 0, 1]))
            # from the rim to a little past the equator, the part that has to open
            s.apply_translation([0, 0, c - R * 0.72])
            m = _weld([m, s])
    elif kind in ("peg", "axle", "pivot"):
        m = trimesh.creation.cylinder(radius=(size + gap) / 2.0, height=L + SOCKET_DEPTH)
        m.apply_translation([0, 0, (L + SOCKET_DEPTH) / 2.0])
    elif kind in ("tab", "lap"):
        m = trimesh.creation.box(extents=[size + gap, PLATE + gap, L + SOCKET_DEPTH])
        m.apply_translation([0, 0, (L + SOCKET_DEPTH) / 2.0])
    else:
        raise KeyError(kind)
    m.apply_transform(_axis_frame(axis))
    m.apply_translation(at)
    return m


def _default_length(kind, size):
    """How far a feature reaches in. Proportional to its size, so the set stays consistent."""
    # a pivot is deeper than a peg on purpose: a short post in a round hole wobbles, and a joint
    # that wobbles will not hold a pose
    return {"peg": 2.2, "axle": 3.0, "pivot": 2.6, "ball": 1.6, "tab": 2.5, "lap": 1.0}[kind] * size


def spins(size, hole_wall_mm, board_gap_mm):
    """Whether a part on this axle can turn.

    Three conditions must hold together: the axle is thick enough not to snap, the hole has enough
    wall around it, and the turning part clears its support by at least the running clearance.
    Returns (ok, reasons).
    """
    gap = CLEAR + AXLE_PLAY
    reasons = []
    if size < 1.6:
        reasons.append(f"axle {size:.1f} mm is thinner than 1.6 mm and will snap")
    if hole_wall_mm < 0.8:
        reasons.append(f"only {hole_wall_mm:.2f} mm of wall around the hole (needs 0.8)")
    if board_gap_mm < gap:
        reasons.append(f"the turning part rubs its support: {board_gap_mm:.2f} mm gap, needs {gap:.2f}")
    return (not reasons), reasons


def slit_tips(size, axis, at, length, phase, count=None):
    """Where the relief slits reach, in world coordinates, for a given phase.

    It uses `_axis_frame`, the same rotation `female` builds the slits with, rather than a basis of
    its own. A measurement that rebuilds the frame it measures can disagree with the geometry it
    claims to describe.
    """
    n = BALL_SLITS if count is None else int(count)
    R = size / 2.0
    outer = R + BALL_CLEAR + BALL_WALL
    c = ball_reach(size) if length is None else float(length)
    M = _axis_frame(axis)
    at = np.asarray(at, float)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + float(phase)
        # the slit runs from the rim past the equator, and its far corner is where it breaks out
        local = np.array([outer * math.cos(a), outer * math.sin(a), c - R * 0.72, 1.0])
        pts.append((M @ local)[:3] + at)
    return np.asarray(pts, float)


def socket_reach(size):
    """How far the whole ball socket reaches from its centre, the distance a wall must clear.

    `R + BALL_CLEAR + BALL_WALL` is the slits' radius, not their reach, and is not enough as a
    requirement. Each slit is a box `R * 1.35` tall sitting `R * 0.72` below the ball centre, so its
    far bottom corner is out at `outer` radially and down by `R * 1.35 / 2 + R * 0.72` at the same
    time. The reach is the hypotenuse of those two, which a radius-only check cannot see.

    For example, with a radius of 2.70 mm the corner is at 3.41 mm. A part with 3.23 mm of material
    passes the radius check but still gets a tunnel through it (genus 1), while 3.39 mm only just
    clears.
    """
    R = size / 2.0
    outer = R + BALL_CLEAR + BALL_WALL
    below = R * 1.35 / 2.0 + R * 0.72
    return float(math.hypot(outer, below))
