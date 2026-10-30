"""Whether a loose part will stay on the plate, judged by the shape of its first layer, and mouse ears
for one that will not.

A part printed on its own (not held by runners to a frame) stays down only by its first layer. Its
area (`tosprue.bed_area`) is not enough to judge that. A rod laid on its flat side can have a first
layer of nearly 20 mm2, above the area where parts are starved, spread as a single strip 2 mm wide
and 17 mm long, under a round body that is more than twice as wide a millimetre higher. Such a part
peels from its ends as it cools, the nozzle catches it, and it is dragged across the plate.

`footing(mesh)` reads the first layer the way that failure happens: its widest solid spot (the
diameter of the largest circle that fits inside it), its length, and how much the part grows in the
first `RISE_MM` above the plate. `ears(mesh)` adds a thin disc under each end of the first layer,
the mouse ears printers cut off after printing, without changing the part's own shape.

    f = footing(axle)            # {"area_mm2", "width_mm", "length_mm", "growth", "narrow", "why"}
    if f["narrow"]:
        axle = ears(axle)        # two 7 mm discs, two layers thick, under its ends
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
#: mouse ear size: diameter and thickness (two 0.2 mm layers)
EAR_D = 7.0
EAR_H = 0.4


def _section(mesh, z):
    """The part's cross-section at height z above its lowest point, as one shapely geometry."""
    sec = mesh.section(plane_origin=[0, 0, float(mesh.bounds[0][2]) + z], plane_normal=[0, 0, 1])
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


def ears(mesh, d: float = EAR_D, h: float = EAR_H, inset: float = 1.5, layer: float = 0.2):
    """The part with a thin disc of diameter `d` and height `h` under each end of its first layer.

    The ends are the two ends of the first layer's long axis, `inset` in from each tip, so each ear
    sits under the part and holds it from below. Cut them off after printing."""
    first = _section(mesh, layer / 2.0)
    if first.is_empty:
        raise ValueError("the part has no first layer to put ears under")
    rect = first.minimum_rotated_rectangle
    c = np.asarray(rect.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    axis = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    half = float(np.linalg.norm(axis)) / 2.0
    u = axis / (2.0 * half)
    mid = np.asarray(rect.centroid.coords[0])
    z0 = float(mesh.bounds[0][2])
    parts = [mesh]
    for sgn in (-1.0, 1.0):
        at = mid + sgn * (half - inset) * u
        disc = trimesh.creation.cylinder(radius=d / 2.0, height=h, sections=48)
        disc.apply_translation([at[0], at[1], z0 + h / 2.0])
        parts.append(disc)
    return trimesh.boolean.union(parts)
