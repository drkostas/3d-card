"""Read a sliced plate back and check it against the card it was sliced from.

A slicer can drop an override, slice for the wrong plate, start a card in the air, or leave a thin
part out, and none of that shows in the slicer's own summary. This module reads the G-code 3MF that
Bambu Studio and OrcaSlicer write (`read_3mf`), the settings block in the G-code (`settings_in`)
and the extrusion moves of every layer (`toolpath`, arcs included), and checks them against the
card's mesh (`check`, `coverage`):

- every setting you asked for is in the G-code,
- the slice is for the plate you meant,
- the first layer carries more filament than any other layer, since a card that starts in the air
  lays a few mm on layer 1 and hundreds on layer 4,
- every island of the card on the plate gets first-layer lines and a brim ring,
- each piece of the card, cut every few layers, has its walls drawn.

The slicer may move and turn the card on the plate. `placed_as_sliced` finds the quarter turn and
the move that put it there, so the checks read the card where it was printed.

    sliced = read_3mf("card.gcode.3mf")
    card, turns = placed_as_sliced(card, sliced)
    report = check(sliced, card, overrides={"brim_width": "5"}, bed_type="Textured PEI Plate")
    report["uncovered"] = coverage(card, sliced, report["shift_mm"])
"""
import io
import pathlib
import re
import zipfile

import numpy as np

def read_3mf(path: pathlib.Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        gcode = z.read(next(n for n in names if n.endswith("plate_1.gcode"))).decode("utf-8", "replace")
        info = z.read("Metadata/slice_info.config").decode() if "Metadata/slice_info.config" in names else ""
        png = z.read("Metadata/plate_1.png") if "Metadata/plate_1.png" in names else None
    return {"gcode": gcode, "slice_info": info, "plate_png": png}


def settings_in(gcode: str) -> dict:
    """The `; key = value` settings block the slicer writes into the G-code."""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^; ([a-z0-9_]+) = (.*)$", gcode, re.M)}


def _arc(x, y, nx, ny, i, j, clockwise, step_mm=0.5):
    """The points along a G2/G3 arc from (x, y) to (nx, ny) about the centre (x + i, y + j)."""
    import math
    cx, cy = x + i, y + j
    r = math.hypot(i, j)
    a0 = math.atan2(y - cy, x - cx)
    a1 = math.atan2(ny - cy, nx - cx)
    if clockwise:
        sweep = (a0 - a1) % (2 * math.pi) or 2 * math.pi
        sweep = -sweep
    else:
        sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    n = max(2, int(abs(sweep) * r / step_mm) + 1)
    return [(cx + r * math.cos(a0 + sweep * k / (n - 1)), cy + r * math.sin(a0 + sweep * k / (n - 1)))
            for k in range(n)]


def toolpath(gcode: str, every: dict | None = None):
    """Per layer: (z, filament mm) and the first layer's extrusion segments with their feature. Pass
    a dict as `every` to have each layer's extrusion segments put in it, keyed by the layer's z."""
    layers, segs = [], []
    x = y = z = 0.0
    e_rel, feature, layer = True, "", 0
    cur = 0.0
    for line in gcode.splitlines():
        if line.startswith("; CHANGE_LAYER"):
            if layer:
                layers.append((z, cur))
            layer += 1
            cur = 0.0
            continue
        if line.startswith("; Z_HEIGHT:"):
            z = float(line.split(":")[1])
            continue
        if line.startswith("; FEATURE:"):
            feature = line.split(":", 1)[1].strip()
            continue
        if line.startswith("M83"):
            e_rel = True
        elif line.startswith("M82"):
            e_rel = False
        if not (line.startswith("G1 ") or line.startswith("G0 ") or line.startswith("G2 ") or line.startswith("G3 ")):
            continue
        code = line.split(";", 1)[0]
        vals = dict((w[0], float(w[1:])) for w in code.split()[1:] if len(w) > 1 and w[0] in "XYZEIJ" and
                    re.fullmatch(r"-?(\d+\.?\d*|\.\d+)", w[1:]))   # Bambu writes .0321, no leading zero
        nx, ny = vals.get("X", x), vals.get("Y", y)
        e = vals.get("E", 0.0)
        if e > 0 and e_rel:
            cur += e
            # Round walls are arcs. The slicer fits arcs (G2 clockwise, G3 counter-clockwise, centre
            # at I, J from the start), and a full circle is one arc that ends where it starts: read as
            # a straight move it has no length, and a round part's wall would vanish from the check.
            pts = _arc(x, y, nx, ny, vals.get("I", 0.0), vals.get("J", 0.0), line.startswith("G2")) \
                if line[:2] in ("G2", "G3") else [(x, y), (nx, ny)]
            for (a, b), (c, d) in zip(pts[:-1], pts[1:]):
                if layer == 1:
                    segs.append((a, b, c, d, feature))
                if every is not None:
                    every.setdefault(round(z, 3), []).append((a, b, c, d))
        x, y = nx, ny
    if layer:
        layers.append((z, cur))
    return layers, segs


def _same(want: str, got: str | None) -> bool:
    if got is None:
        return False
    g = got.strip().strip('"')
    w = str(want).strip()
    if w == g:
        return True
    try:
        return all(abs(float(a) - float(w)) < 1e-6 for a in g.split(","))
    except ValueError:
        return False


def first_layer_islands(card, z=0.1):
    """The card's cross-section just above the plate, as shapely polygons (one per island)."""
    sec = card.section(plane_origin=[0, 0, float(card.bounds[0][2]) + z], plane_normal=[0, 0, 1])
    if sec is None:
        return []
    planar, T = sec.to_2D(to_2D=np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -z], [0, 0, 0, 1.0]]),
                              normal=[0, 0, 1], check=False)
    return list(planar.polygons_full)


def placed_as_sliced(card, sliced):
    """The card turned and moved to where the slicer put it on the plate: (mesh, quarter turns).

    A slicer turns a card a quarter when it fits the plate better, so a card lined up by a move alone
    can lie across its own toolpath, with islands that read as having no first layer. Each quarter
    turn whose outline is the size of the first layer's lines is tried, and the one with the most of
    those lines inside the card's outline wins, which also tells a turn from its half-turn twin.
    Returns (card, 0) when no turn matches, and `check` then reports `lined_up` false.
    """
    import trimesh
    from shapely.geometry import Point
    from shapely.affinity import translate
    from shapely.ops import unary_union
    _layers, segs = toolpath(sliced["gcode"])
    body = [sg for sg in segs if any(w in sg[4].lower() for w in ("wall", "surface", "infill", "gap"))]
    if not body:
        return card, 0
    bx = np.array([[a, b] for a, b, c, d, _f in body] + [[c, d] for a, b, c, d, _f in body])
    (gx0, gy0), (gx1, gy1) = bx.min(axis=0), bx.max(axis=0)
    mids = [Point((a + c) / 2, (b + d) / 2) for a, b, c, d, _f in body]
    best = None
    for k in range(4):
        m = card.copy()
        m.apply_transform(trimesh.transformations.rotation_matrix(k * np.pi / 2, [0, 0, 1]))
        islands = first_layer_islands(m)
        if not islands:
            continue
        cx0, cy0, cx1, cy1 = unary_union(islands).bounds
        if abs((gx1 - gx0) - (cx1 - cx0)) >= 2.0 or abs((gy1 - gy0) - (cy1 - cy0)) >= 2.0:
            continue
        dx, dy = (gx0 + gx1) / 2 - (cx0 + cx1) / 2, (gy0 + gy1) / 2 - (cy0 + cy1) / 2
        inside = unary_union([translate(p, dx, dy) for p in islands])
        score = sum(1 for q in mids if inside.contains(q))
        if best is None or score > best[0]:
            m.apply_translation([dx, dy, 0.0])
            best = (score, m, k)
    return (best[1], best[2]) if best else (card, 0)


def check(sliced: dict, card, overrides=None, bed_type=None, brim_width=None) -> dict:
    """Read a slice against its card: settings, plate, first layer, islands and brims.

    `sliced` is `read_3mf`'s result and `card` the mesh as it lies on the plate in the G-code's
    frame (see `placed_as_sliced`). `overrides` is {setting: wanted value}, each checked in the
    G-code's settings block. `bed_type` is the plate's name as the slicer writes it. `brim_width`
    (mm) is how far from an island its brim may run, by default the `brim_width` override or 5.
    Returns a report whose `ok` is true only when every check passed.
    """
    overrides = dict(overrides or {})
    gcode = sliced["gcode"]
    s = settings_in(gcode)
    landed = {k: {"want": str(v), "got": s.get(k), "ok": _same(v, s.get(k))} for k, v in overrides.items()}
    bed = {"want": bed_type, "got": s.get("curr_bed_type"),
           "ok": bed_type is None or s.get("curr_bed_type") == bed_type}
    layers, segs = toolpath(gcode)
    per_layer = [mm for _z, mm in layers]
    first_is_largest = bool(bool(per_layer) and per_layer[0] >= max(per_layer))
    brim_w = float(brim_width if brim_width is not None else overrides.get("brim_width", 5))

    from shapely.geometry import LineString, Point
    from shapely.affinity import translate
    islands = first_layer_islands(card)
    brim = [sg for sg in segs if "brim" in sg[4].lower()]
    # the card's own lines only: the printer's start sequence and any purge are not the card
    body = [sg for sg in segs if any(w in sg[4].lower() for w in ("wall", "surface", "infill", "gap"))]
    out_islands = []
    shift = None
    if islands and body:
        # line the card's first layer up with the G-code's by the middle of their outlines, and
        # refuse the reading if their sizes do not match (a card the slicer turned, unturned)
        bx = np.array([[a, b] for a, b, c, d, _f in body] + [[c, d] for a, b, c, d, _f in body])
        from shapely.ops import unary_union
        u = unary_union(islands)
        cx0, cy0, cx1, cy1 = u.bounds
        gx0, gy0 = bx.min(axis=0)
        gx1, gy1 = bx.max(axis=0)
        size_ok = abs((gx1 - gx0) - (cx1 - cx0)) < 2.0 and abs((gy1 - gy0) - (cy1 - cy0)) < 2.0
        shift = [float((gx0 + gx1) / 2 - (cx0 + cx1) / 2), float((gy0 + gy1) / 2 - (cy0 + cy1) / 2)]
        mids = [Point((a + c) / 2, (b + d) / 2) for a, b, c, d, _f in body]
        brims = [LineString([(a, b), (c, d)]) for a, b, c, d, _f in brim if (a, b) != (c, d)]
        for poly in sorted(islands, key=lambda p: -p.area):
            p = translate(poly, *shift)
            fed = sum(1 for m in mids if p.contains(m))
            ring = p.exterior.buffer(brim_w + 1.0)
            ringed = any(ring.intersects(b) for b in brims) if brims else False
            out_islands.append({"area_mm2": round(float(poly.area), 1), "first_layer_moves": fed,
                                "brim": bool(ringed)})
    else:
        size_ok = False
    info = sliced.get("slice_info") or ""
    pred = re.search(r'key="prediction" value="([\d.]+)"', info)
    weight = re.search(r'key="weight" value="([\d.]+)"', info)
    warnings = re.findall(r'<warning[^>]*msg="([^"]*)"', info)
    ok = (all(v["ok"] for v in landed.values()) and bed["ok"] and first_is_largest and size_ok
          and all(i["first_layer_moves"] > 0 and i["brim"] for i in out_islands) and bool(out_islands))
    return {"ok": bool(ok), "time_s": float(pred.group(1)) if pred else None,
            "grams": float(weight.group(1)) if weight else None, "layers": len(layers),
            "first_layer_mm": round(per_layer[0], 1) if per_layer else None,
            "largest_layer_mm": round(max(per_layer), 1) if per_layer else None,
            "first_layer_is_largest": first_is_largest, "settings": landed, "bed": bed,
            "islands": out_islands, "lined_up": bool(size_ok), "shift_mm": shift, "slicer_warnings": warnings,
            "per_layer_mm": [round(v, 1) for v in per_layer]}


def coverage(card, sliced, shift, line_w=0.42, step=5):
    """Every `step`-th layer, the card cut at that height and how much of each cut piece's walls (its
    outer two line widths, all of a thin piece) the sliced lines cover. A wall the slicer did not
    print reads near 0. Returns the pieces under 60% covered, least covered first."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from shapely.affinity import translate
    every = {}
    toolpath(sliced["gcode"], every)
    z0 = float(card.bounds[0][2])
    low = []
    zs = sorted(every)
    for i, z in enumerate(zs):
        if i % step or z < 0.3:
            continue
        sec = card.section(plane_origin=[0, 0, z0 + z - 0.1], plane_normal=[0, 0, 1])
        if sec is None:
            continue
        try:
            planar, _T = sec.to_2D(to_2D=np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -(z0 + z - 0.1)], [0, 0, 0, 1.0]]),
                                       normal=[0, 0, 1], check=False)
        except Exception:
            continue
        lines = [LineString([(a, b), (c, d)]) for a, b, c, d in every[z] if (a, b) != (c, d)]
        if not lines:
            continue
        printed = unary_union([ln.buffer(line_w / 2, cap_style=2) for ln in lines])
        for poly in planar.polygons_full:
            p = translate(poly, *shift)
            if p.area < 0.5:
                continue
            # the walls only: the outer two line widths of the piece (all of a thin piece), since the
            # inside of a thick piece is sparse infill by design
            band = p.difference(p.buffer(-2 * line_w))
            if band.area < 0.3:
                continue
            got = band.intersection(printed).area / band.area
            if got < 0.6:
                c = p.representative_point()
                low.append({"z": round(z, 2), "area_mm2": round(float(p.area), 2), "covered": round(float(got), 2),
                            "at": [round(float(c.x - shift[0]), 1), round(float(c.y - shift[1]), 1)]})
    # A piece the card does not hold is the section's mistake, not the slicer's. Where two sheets of
    # a mesh touch along an edge, trimesh's section can close a loop with a straight chord, and the
    # "piece" it makes is air (a bore read as 0% printed while the G-code drew the whole band round
    # it). Each low piece is kept only if the card holds its own point at that height.
    if low:
        pts = np.array([[r["at"][0], r["at"][1], z0 + r["z"] - 0.1] for r in low])
        held = card.contains(pts)
        for r, h in zip(low, held):
            r["in_card"] = bool(h)
    return sorted([r for r in low if r.get("in_card", True)], key=lambda r: r["covered"])


def picture(card, sliced, rep, path: pathlib.Path):
    """The first layer as sliced over the card's own outline, beside the slicer's picture of the plate."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.affinity import translate
    _layers, segs = toolpath(sliced["gcode"])
    fig = plt.figure(figsize=(14, 7), dpi=110, facecolor="#16181b")
    ax = fig.add_subplot(1, 2, 1, facecolor="#16181b")
    for poly in first_layer_islands(card):
        p = translate(poly, *(rep["shift_mm"] or [0, 0]))
        xs, ys = p.exterior.xy
        ax.fill(xs, ys, color="#5a5f66", lw=0)
        for hole in p.interiors:                     # the frame's windows are open, not card
            hx, hy = hole.xy
            ax.fill(hx, hy, color="#16181b", lw=0)
    for a, b, c, d, f in segs:
        ax.plot([a, c], [b, d], color="#e8a33d" if "brim" in f.lower() else "#7fb2ff", lw=0.35)
    ax.set_aspect("equal")
    ax.set_title("first layer as sliced: the card in grey, its lines in blue, the brim in orange",
                 color="#e2e8ee", fontsize=10)
    ax.tick_params(colors="#9aa3ad")
    ax2 = fig.add_subplot(1, 2, 2, facecolor="#16181b")
    if sliced["plate_png"]:
        import matplotlib.image as mpimg
        ax2.imshow(mpimg.imread(io.BytesIO(sliced["plate_png"]), format="png"))
    ax2.axis("off")
    ax2.set_title(f"the slicer's own picture of the plate      {rep['time_s'] / 3600:.1f} h, {rep['grams']:.0f} g",
                  color="#e2e8ee", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path
