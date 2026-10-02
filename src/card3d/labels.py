"""Small 3D number labels for finding the same part in two views of a kit.

`number` turns text into a flat extruded solid, `beside` places one next to a part, `reading_order`
numbers parts the way a person reads a card, and `spread` pushes overlapping labels apart.

A typical use is a card layout and an exploded assembly view that show parts in different
orientations. The card layout is decided by nesting and by the orientation each part needs to print,
so the views cannot always match. Numbering the parts in both views connects them without changing
either layout.

The labels are separate scene meshes, not features of the printed card. Embossing them onto the card
would change what prints and add one more feature for every downstream check to handle, to solve a
problem that only exists on screen.
"""
import numpy as np
import trimesh
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties
from shapely.geometry import Polygon
from shapely.ops import unary_union

# DejaVu Sans ships with matplotlib, so no font lookup is needed and the result is the same on
# every machine.
_FONT = FontProperties(family="DejaVu Sans", weight="bold")


def _glyph_polygons(text, size=1.0):
    """The text's outline as shapely polygons, holes included."""
    if not str(text).strip():
        return []                    # matplotlib's TextPath fails on an empty string
    path = TextPath((0, 0), str(text), size=size, prop=_FONT)
    rings = [np.asarray(p, float) for p in path.to_polygons(closed_only=True) if len(p) >= 4]
    if not rings:
        return []
    polys = [Polygon(r).buffer(0) for r in rings]
    # A '0' or an '8' is a ring inside a ring, and `to_polygons` returns both as outlines without
    # saying which is the hole. Symmetric difference gives the right result in either order.
    out = None
    for p in polys:
        if p.is_empty:
            continue
        out = p if out is None else out.symmetric_difference(p)
    if out is None or out.is_empty:
        return []
    return list(out.geoms) if hasattr(out, "geoms") else [out]


def number(text, height=6.0, depth=1.0):
    """One number as a solid, lying in the XY plane, centred on the origin."""
    polys = _glyph_polygons(text, size=height)
    if not polys:
        return None
    bits = []
    for p in polys:
        try:
            m = trimesh.creation.extrude_polygon(p, height=depth)
        except Exception:
            continue
        if m is not None and not m.is_empty:
            bits.append(m)
    if not bits:
        return None
    m = bits[0] if len(bits) == 1 else trimesh.util.concatenate(bits)
    m.apply_translation(-m.bounds.mean(axis=0))
    return m


def beside(mesh, text, height=6.0, depth=1.0, gap=2.0, where="below"):
    """A number placed just outside `mesh` ("below", "above" or "left"), flat, ready for a scene."""
    n = number(text, height=height, depth=depth)
    if n is None or mesh is None:
        return None
    lo, hi = mesh.bounds
    c = mesh.bounds.mean(axis=0)
    if where == "below":
        at = [c[0], float(lo[1]) - gap - 0.5 * float(n.extents[1]), float(hi[2]) + depth]
    elif where == "above":
        at = [c[0], float(hi[1]) + gap + 0.5 * float(n.extents[1]), float(hi[2]) + depth]
    else:                                        # "left"
        at = [float(lo[0]) - gap - 0.5 * float(n.extents[0]), c[1], float(hi[2]) + depth]
    n.apply_translation(np.asarray(at, float) - n.bounds.mean(axis=0))
    return n


def reading_order(pieces):
    """Number the pieces the way a person reads the card: top row first, left to right.

    The order follows the card layout, not the assembly order, because the number exists to find a
    part. Another view then uses the same numbers by part name, which keeps the two views in step.
    Returns a dict of name to number, starting at 1.
    """
    if not pieces:
        return {}
    rows = []
    items = sorted(pieces.items(),
                   key=lambda kv: -float(kv[1].bounds.mean(axis=0)[1]))
    tol = max(1.0, 0.5 * float(np.median([p.extents[1] for p in pieces.values()])))
    for name, m in items:
        y = float(m.bounds.mean(axis=0)[1])
        for row in rows:
            if abs(row[0] - y) <= tol:
                row[1].append((name, m))
                break
        else:
            rows.append((y, [(name, m)]))
    order = {}
    i = 1
    for _y, row in rows:
        for name, m in sorted(row, key=lambda kv: float(kv[1].bounds.mean(axis=0)[0])):
            order[name] = i
            i += 1
    return order


def spread(placed, min_gap=1.5, rounds=60):
    """Push apart any two numbers that land on top of each other.

    Each number is placed just outside its own part, so small parts that sit close together produce
    labels that overlap into an unreadable smear. An unreadable label is worse than none, because it
    suggests the card is labelled when it is not, and the problem is only visible in a render.

    The labels are relaxed apart in the plane a little at a time until nothing overlaps or `rounds`
    is reached. Each one moves only as far as it has to, so a label that was already clear stays next
    to its part.
    """
    keys = list(placed)
    if len(keys) < 2:
        return placed
    pos = {k: np.asarray(placed[k].bounds.mean(axis=0), float) for k in keys}
    rad = {k: 0.5 * float(np.linalg.norm(placed[k].extents[:2])) for k in keys}
    for _ in range(rounds):
        moved = False
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                d = pos[a][:2] - pos[b][:2]
                n = float(np.linalg.norm(d))
                want = rad[a] + rad[b] + min_gap
                if n >= want:
                    continue
                if n < 1e-6:
                    d = np.array([1.0, 0.0])
                    n = 1.0
                push = (want - n) * 0.5
                step = (d / n) * push
                pos[a][:2] += step
                pos[b][:2] -= step
                moved = True
        if not moved:
            break
    out = {}
    for k in keys:
        m = placed[k].copy()
        m.apply_translation(pos[k] - np.asarray(m.bounds.mean(axis=0), float))
        out[k] = m
    return out
