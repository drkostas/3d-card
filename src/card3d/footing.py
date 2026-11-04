"""Whether a loose part will stay on the plate, judged by the shape of its first layer, and mouse ears
for one that will not.

A part printed on its own (not held by runners to a frame) stays down only by its first layer. Its
area (`tosprue.bed_area`) is not enough to judge that. A rod laid on its flat side can have a first
layer of nearly 20 mm2, above the area where parts are starved, spread as a single strip 2 mm wide
and 17 mm long, under a round body that is more than twice as wide a millimetre higher. Such a part
peels from its ends as it cools, the nozzle catches it, and it is dragged across the plate.

`footing(mesh)` reads the first layer the way that failure happens: its widest solid spot (the
diameter of the largest circle that fits inside it), its length, and how much the part grows in the
first `RISE_MM` above the plate. `ears(mesh)` adds a one-layer disc at each end of the first layer,
the mouse ears printers peel off after printing, without changing the part's own shape.

⛔ EARS UNDER THE PART DO NOT COME OFF. The first ears were two layers thick and sat wholly under the
ends of a printed axle, and the person could not remove them. An ear is one layer and reaches only
`EAR_OVERLAP` under the tip, the rest of it beyond the part, so it holds the tip down and peels away.

    f = footing(axle)            # {"area_mm2", "width_mm", "length_mm", "growth", "narrow", "why"}
    if f["narrow"]:
        axle = ears(axle)        # two 7 mm discs, two layers thick, under its ends

`sheet(meshes)` is the other answer, for a whole card: one layer under everything, which the round
sides of the parts rest on while they print and which comes away from the card in one piece.
A part lying on its round side (a rod, a ball, a curved limb) stands on a narrow first layer, and
its sides grow outwards over the next millimetre with nothing under them. Without a brim those
sides droop and curl, the nozzle catches them, and the part is torn off the plate. A brim holds them,
but it is welded to every part and has to be cut away ring by ring. The sheet holds them the way a
support does: it keeps `SHEET_GAP_XY` away from every first-layer outline and the card is left
empty for `SHEET_GAP_Z` above it, so nothing is welded to it.

    sheet_mesh, (card, black), info = sheet([card, black])
"""
from __future__ import annotations

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

#: a first layer whose widest solid spot is under this is a strip, not a foot
FOOT_MIN_W = 3.0
#: and it peels when it is also this many times longer than wide
FOOT_MAX_ASPECT = 4.0
#: or when the part above it grows to this many times the first layer's area within RISE_MM
FOOT_MAX_GROWTH = 2.0
#: how high above the plate the growth is read
RISE_MM = 1.0
#: mouse ear size: diameter and thickness (one 0.2 mm layer, so it peels off by hand)
EAR_D = 7.0
EAR_H = 0.2
#: how far an ear reaches under the part's tip; the rest of the disc lies beyond it
EAR_OVERLAP = 1.5


def _section(mesh, z):
    """The part's cross-section at height z above its lowest point, as one shapely geometry."""
    return _cut(mesh, float(mesh.bounds[0][2]) + z)


def _cut(mesh, z):
    """The mesh's cross-section at the absolute height z, as one shapely geometry."""
    if not float(mesh.bounds[0][2]) < z < float(mesh.bounds[1][2]):
        return Polygon()
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return Polygon()
    polys = []
    for loop in sec.discrete:
        if len(loop) >= 3:
            p = Polygon(np.asarray(loop)[:, :2]).buffer(0)
            if not p.is_empty:
                polys.append(p)
    if not polys:
        return Polygon()
    # an outline inside another is a hole: the symmetric difference sorts that out in any order
    out = polys[0]
    for p in polys[1:]:
        out = out.symmetric_difference(p)
    return out


def footing(mesh, layer: float = 0.2) -> dict:
    """How the part stands on the plate: the first layer's area, its widest solid spot (`width_mm`,
    the diameter of the largest circle inside it), its `length_mm` (the long side of the smallest
    rectangle round it), and `growth`, the part's area `RISE_MM` up over the first layer's. `narrow`
    is True when the widest spot is under `FOOT_MIN_W` and the strip is either longer than
    `FOOT_MAX_ASPECT` times its width or carries a part that grows past `FOOT_MAX_GROWTH`."""
    first = _section(mesh, layer / 2.0)
    area = float(first.area)
    if area <= 0:
        return {"area_mm2": 0.0, "width_mm": 0.0, "length_mm": 0.0, "growth": float("inf"),
                "narrow": True, "why": "no first layer"}
    width = 2.0 * float(shapely.maximum_inscribed_circle(first, 0.01).length)
    rect = first.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = [float(np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i])) for i in range(2)]
    length = max(sides)
    above = float(_section(mesh, min(RISE_MM, float(mesh.extents[2]) - layer / 2.0)).area)
    growth = above / area
    why = []
    if width < FOOT_MIN_W:
        if length > FOOT_MAX_ASPECT * width:
            why.append(f"a strip {width:.2f} mm wide and {length:.1f} mm long")
        if growth > FOOT_MAX_GROWTH:
            why.append(f"{growth:.1f} times as wide {RISE_MM:g} mm up")
    return {"area_mm2": round(area, 1), "width_mm": round(width, 2), "length_mm": round(length, 1),
            "growth": round(growth, 2), "narrow": bool(why), "why": "; ".join(why)}


def ears(mesh, d: float = EAR_D, h: float = EAR_H, overlap: float = EAR_OVERLAP, layer: float = 0.2):
    """The part with a thin disc of diameter `d` and height `h` at each end of its first layer.

    The ends are the two ends of the first layer's long axis. Each disc reaches `overlap` under the
    tip and lies beyond it otherwise, so it holds the tip down and peels off by hand."""
    first = _section(mesh, layer / 2.0)
    if first.is_empty:
        raise ValueError("the part has no first layer to put ears under")
    rect = first.minimum_rotated_rectangle
    c = np.asarray(rect.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    axis = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    u = axis / float(np.linalg.norm(axis))
    # ⛔ AT THE FIRST LAYER'S OWN ENDS, NOT THE RECTANGLE'S. On a curved part (an arm) the ends of
    # the first layer lie off the rectangle's centre line, and a disc on that line missed the part.
    # Each ear is centred beyond the farthest point of the first layer along its long axis.
    geoms = getattr(first, "geoms", [first])
    pts = np.vstack([np.asarray(g.exterior.coords)[:, :2] for g in geoms])
    proj = pts @ u
    z0 = float(mesh.bounds[0][2])
    parts = [mesh]
    for sgn in (-1.0, 1.0):
        tip = pts[int(np.argmax(sgn * proj))]
        at = tip + sgn * (d / 2.0 - overlap) * u
        disc = trimesh.creation.cylinder(radius=d / 2.0, height=h, sections=48)
        disc.apply_translation([at[0], at[1], z0 + h / 2.0])
        parts.append(disc)
    return trimesh.boolean.union(parts)


#: the sheet: one layer thick, how far it keeps from the card's first-layer outlines, the empty
#: layer between it and the card above it, and how far it reaches past what it carries
SHEET_H = 0.2
SHEET_GAP_XY = 0.3
SHEET_GAP_Z = 0.2
SHEET_MARGIN = 3.0
#: the heights above the plate whose outlines the sheet is drawn under (the sides that need it)
SHEET_READ_AT = (0.3, 0.5, 0.8, 1.2, 1.6, 2.0)


def _extrude(poly, h):
    """A shapely (multi)polygon extruded `h` up from z = 0, as one watertight trimesh.

    manifold3d's cross-section takes every ring at once with the even-odd fill, which stays a closed
    volume where a hole runs close to an outline; trimesh's own extrusion did not, piece by piece."""
    from manifold3d import CrossSection, FillRule
    rings = []
    for g in getattr(poly, "geoms", [poly]):
        if g.is_empty:
            continue
        rings.append(np.asarray(g.exterior.coords)[:-1, :2])
        rings.extend(np.asarray(r.coords)[:-1, :2] for r in g.interiors)
    if not rings:
        return None
    m = CrossSection(rings, FillRule.EvenOdd).extrude(h).to_mesh()
    return trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts), process=True)


def _shadow(meshes, heights):
    """The union of the meshes' cross-sections at the absolute `heights`."""
    from shapely.ops import unary_union
    out = []
    for m in meshes:
        for z in heights:
            g = _cut(m, z)
            if not g.is_empty:
                out.append(g)
    return unary_union(out) if out else Polygon()


def sheet(meshes, parts=None, margin: float = SHEET_MARGIN, gap_xy: float = SHEET_GAP_XY,
          gap_z: float = SHEET_GAP_Z, h: float = SHEET_H, layer: float = 0.2):
    """A one-layer sheet under a card, and the card's meshes made ready to print on it.

    `meshes` is every body of the card on the plate (the card, and any body in a second colour),
    all in the same frame; the lowest point of them all is the plate. `parts` is each part as it
    lies on the card. The sheet keeps clear of the parts and is welded to everything else that
    stands on the plate (the frame and its runners), so it lifts off the plate with the card in one
    piece and stays on the frame when the parts are cut free. Without `parts`, everything on the plate
    is kept clear of and the largest piece of sheet is kept. Returns `(sheet, trimmed, info)`:

    - `sheet` is one layer `h` thick. It lies under the card's outlines from `SHEET_READ_AT` (the
      parts' sides and the gates in the first two millimetres) widened by `margin`, keeps `gap_xy` from every part's
      first layer, joins the frame and stays inside the card's outline. A piece of it that cannot reach the frame (inside a ring,
      say) would stay on the plate as a scrap, so it is left out and its area reported.
    - `trimmed` is `meshes` emptied for `gap_z` above the sheet, except over the frame, so the
      parts' sides start one layer clear of it and are not welded to it.
    - `info` has the sheet's area, the area left out and the volume taken from each mesh.
    """
    from shapely.ops import unary_union
    z0 = min(float(m.bounds[0][2]) for m in meshes)
    lift = lambda m: m.copy().apply_translation([0.0, 0.0, -z0])
    rel = [lift(m) for m in meshes]
    first = unary_union([_cut(m, layer / 2.0) for m in rel])
    if parts is None:
        held, frame = rel, Polygon()
    else:
        held = [lift(p) for p in parts]
        clear_of = unary_union([_cut(p, layer / 2.0) for p in held])
        frame = first.difference(clear_of.buffer(0.05))
    clear = unary_union([_cut(m, layer / 2.0) for m in held] +
                        ([] if parts is None else [first.difference(frame)]))
    # under the parts' sides, and under whatever joins them to the frame (the gates), so the sheet
    # round each part reaches the frame along its gate
    reach = _shadow(rel, SHEET_READ_AT).union(clear).buffer(margin)
    area = reach.union(frame).difference(clear.buffer(gap_xy))
    if not frame.is_empty:
        # inside the card's outline: past the frame's outer edge the sheet would be a brim
        from shapely.geometry import Polygon as _P
        outline = unary_union([_P(g.exterior) for g in getattr(first, "geoms", [first])])
        area = area.intersection(outline)
    pieces = [p for p in getattr(area, "geoms", [area]) if not p.is_empty]
    if not pieces:
        raise ValueError("the card leaves no room for a sheet under it")
    if parts is None or frame.is_empty:
        pieces.sort(key=lambda p: -p.area)
        kept, out = pieces[:1], pieces[1:]
    else:
        joined = frame.buffer(0.01)
        kept = [p for p in pieces if p.intersects(joined)]
        out = [p for p in pieces if not p.intersects(joined)]
    keep = unary_union(kept).simplify(0.02)
    s = _extrude(keep, h)
    s.apply_translation([0.0, 0.0, z0])
    # the empty layer goes over the sheet but not over the frame, which stays whole
    open_ = keep.difference(frame.buffer(0.01)) if not frame.is_empty else keep
    cut = _extrude(open_, gap_z) if open_.area > 1e-6 else None
    trimmed, taken = [], []
    for m in meshes:
        lo, hi = float(m.bounds[0][2]), float(m.bounds[1][2])
        if cut is None or hi <= z0 + h or lo >= z0 + h + gap_z:
            trimmed.append(m)
            taken.append(0.0)
            continue
        lifted = cut.copy()
        lifted.apply_translation([0.0, 0.0, z0 + h])
        t = trimesh.boolean.difference([m, lifted])
        trimmed.append(t)
        taken.append(round(float(m.volume - t.volume), 3))
    info = {"area_mm2": round(float(keep.area), 1),
            "left_out_mm2": round(float(sum(p.area for p in out)), 1), "taken_mm3": taken}
    return s, trimmed, info
