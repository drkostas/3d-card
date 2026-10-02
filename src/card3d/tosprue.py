"""Turn a set of 3D-printable parts into one printable card.

A card is a flat frame with fully three-dimensional parts attached to it by small gates, like the
sprue of an injection-moulded model kit. The parts keep their joints (posts and sockets) and hang
off the frame until they are snipped.

The pipeline seats each part on its best face for printing, lays the parts out on the card, runs
runner bars across or through the layout, places gates from the runner to each part, and unions
everything into one solid. A round trip then cuts every gate and checks that each part comes off
clean.

The frame is flat and the parts are not, so the card is as tall as its tallest part. That height
is checked against the build volume. Every gate sits at the bottom, in the frame's own plane. A
gate higher up would print in mid-air, and a gate on a post would break the joint.

Main entry points:
    build       build the card from a source of parts and joints
    best_card   build with each layout option and keep the first that passes its own checks
    snip        cut every gate the way flush nippers would
    round_trip  snip a built card and match every piece back to its part
    export      build and write the card to an STL file
"""
import json
import pathlib

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon, box as shapely_box

from base3d.mesh import surface_points as _surface_points
from card3d import joints as J
from card3d import simulator as S
from card3d import sprue

OUT = pathlib.Path.cwd() / "card"

FRAME_W = 6.0            # the border bar, wide because it carries the whole card
FRAME_T = 2.4            # the frame's own thickness, 12 layers at 0.2
# This margin is added on top of the packer's own `sprue.GAP` (7 mm). It is a safety margin, not a
# second copy of the gap. When both were full gaps the parts sat 15 mm apart and a card came out
# 84% empty space (412 cm2 of bed for 67 cm2 of parts), which costs print time and plate space.
GAP = 2.0                # extra clear space around each part, on top of sprue.GAP
BAR_BACK = 3.2           # how far the shelf bar sits behind the parts it carries
GATE = 1.8               # the gate's width, which snips with nippers and survives the print
GATE_H = 2.0             # how tall a gate is: it lives in the frame, never up the part
BED = sprue.BED


SLIVER_MM3 = 1.0         # a shell smaller than this is tessellation noise, not a part


def heal(mesh, verbose=False):
    """Close the few broken faces a large union leaves, so the card is a volume and not only a shape.

    A mesh that is one connected body with consistent winding is not necessarily a solid. A handful
    of broken faces in a mesh of hundreds of thousands (a few tiny holes, `is_watertight` False) is
    enough for a boolean engine to refuse it with "Not all meshes are volumes!", and the body count
    says nothing about it.

    The result is checked afterwards. If the repair does not produce a volume, the original mesh
    is returned unchanged.
    """
    m = mesh.copy()
    m.merge_vertices()
    try:
        m.update_faces(m.nondegenerate_faces())
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
    except Exception:
        pass
    if not m.is_watertight:
        try:
            trimesh.repair.fill_holes(m)
        except Exception:
            pass
    if not m.is_winding_consistent:
        try:
            trimesh.repair.fix_winding(m)
        except Exception:
            pass
    if verbose:
        print(f"  heal: watertight {mesh.is_watertight} -> {m.is_watertight}, "
              f"volume {mesh.is_volume} -> {m.is_volume}")
    return m if m.is_volume else mesh


def _despeckle(mesh):
    """Drop the zero-volume shells a large union leaves behind, so a body count means something."""
    pieces = mesh.split(only_watertight=False)
    if len(pieces) <= 1:
        return mesh
    keep = [p for p in pieces if abs(p.volume) >= SLIVER_MM3]
    if not keep:
        return mesh
    return trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]


def footprint(mesh):
    """The whole part's shadow on the frame plane, which is the space it actually occupies.

    A thin slice near the frame is not a footprint. A tilted part can be small at the bottom and
    lean far out higher up, so nesting by a low slice lets it hang over its neighbours and the
    frame. What must not overlap is the whole part.
    """
    try:
        g = trimesh.path.polygons.projected(mesh, normal=[0.0, 0.0, 1.0])
        if g is not None and not g.is_empty:
            if g.geom_type == "MultiPolygon":
                g = max(g.geoms, key=lambda q: q.area)
            return np.asarray(g.exterior.coords)[:-1]
    except Exception:
        pass
    b = mesh.bounds
    return np.array([[b[0][0], b[0][1]], [b[1][0], b[0][1]],
                     [b[1][0], b[1][1]], [b[0][0], b[1][1]]])


def low_edge(mesh, height=None):
    """Where the part still has material down at frame level, and how far forward it reaches.

    A gate has to meet solid material, and near the frame that means whatever sits in the gate's
    own height band. Asking about the whole part can aim a gate at the underside of a surface that
    curves away.
    """
    height = GATE_H if height is None else height
    band = mesh.slice_plane([0, 0, mesh.bounds[0][2] + height], [0, 0, -1], cap=True)
    if band is None or band.is_empty or band.volume <= 0:
        band = mesh
    v = band.vertices
    lo = float(v[:, 1].min())
    near = v[v[:, 1] < lo + 1.5]
    return lo, float(near[:, 0].min()), float(near[:, 0].max())


MARK_H = 4.2             # cap height of the part numbers stamped on the frame
MARK_DEPTH = 0.6          # how far they stand off the frame, 3 layers at 0.2
MARK_SINK = 0.4           # and how far they reach down into it, so the union is a real join
GATE_BITE = 2.0          # how far a gate reaches into the part, enough to hold and short to snip


def _glyphs(text, size):
    """A string as 2D polygons, holes included.

    `TextPath.to_polygons` returns rings, not shapes. The outside of a 6 and the inside of its loop
    arrive as two equal rings, and unioning them fills the hole. A ring that contains another is
    treated as that one's outline, and the inner ring as its hole.
    """
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    rings = [Polygon(r).buffer(0) for r in
             TextPath((0, 0), text, size=size,
                      prop=FontProperties(family="DejaVu Sans", weight="bold")).to_polygons()
             if len(r) > 2]
    rings = [r for r in rings if not r.is_empty]
    rings.sort(key=lambda g: -g.area)
    out = None
    for g in rings:
        out = g if out is None else (out.difference(g) if out.contains(g) else out.union(g))
    return out


def number_stamp(text, at, height=MARK_H, depth=MARK_DEPTH):
    """One part number, standing proud of the frame so it survives handling."""
    g = _glyphs(text, height * 1.38)
    if g is None or g.is_empty:
        return None
    pieces = g.geoms if g.geom_type == "MultiPolygon" else [g]
    solids = []
    for q in pieces:
        try:
            solids.append(trimesh.creation.extrude_polygon(q, depth))
        except Exception:
            continue
    if not solids:
        return None
    m = trimesh.util.concatenate(solids)
    m.apply_translation([-m.bounds.mean(axis=0)[0], -m.bounds[0][1], 0])
    m.apply_translation(at)
    return m
GATE_MAX = 6.0            # a gate longer than this leaves a long whisker on the part
GATE_ROOT = 1.6          # and into the frame


def _thickness_at(part, a, b):
    """How much material the part has at `a`, measured along the direction the gate comes from.

    The gate arrives from `b` on the frame, so the cutter drives along b->a and keeps going. What
    matters is how far it can travel inside the part before coming out the other side. That is
    the thickness the cut has to survive.
    """
    d = np.asarray(a, float) - np.asarray(b, float)
    n = float(np.linalg.norm(d))
    if n < 1e-9:
        return None
    u = d / n
    try:
        hits = part.ray.intersects_location(
            ray_origins=np.atleast_2d(a - u * 0.05), ray_directions=np.atleast_2d(u))[0]
    except Exception:
        return None
    if not len(hits):
        return None
    return float(np.max(np.linalg.norm(hits - np.asarray(a, float), axis=1)))


def _hemisphere(k=36):
    """`k` directions spread evenly over the unit sphere (a Fibonacci lattice), fixed, not random."""
    i = np.arange(k, dtype=float) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / k)
    th = np.pi * (1.0 + 5.0 ** 0.5) * i
    return np.column_stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)])


def visibility(scene, points, normals, k=36):
    """How much of the world each point on the assembled model can see, from 0 (hidden) to 1.

    A gate leaves a mark however cleanly it is cut, so the useful question is where the mark ends
    up. A point counts as hidden when the rays leaving it run into another part (the inside of a
    cap, a joint face, an armpit) or point steeply downwards, where nobody looks at a model
    standing on a table.
    """
    dirs = _hemisphere(k)
    out = np.ones(len(points))
    try:
        ray = scene.ray
    except Exception:
        return out
    for i, (p, n) in enumerate(zip(np.asarray(points, float), np.asarray(normals, float))):
        d = dirs[dirs @ n > 0.08]
        if not len(d):
            continue
        down = d[:, 2] < -0.35
        o = np.repeat((p + n * 0.08)[None, :], len(d), axis=0)
        try:
            hit = ray.intersects_any(o, d)
        except Exception:
            hit = np.zeros(len(d), bool)
        out[i] = float(np.mean(~(hit | down)))
    return out


def _gates_for(part, frame_mesh, want=2, seed=11, keep_out=(), seen=None):
    """One or two thin bridges from the frame to this part, aimed by geometry.

    Sampling is seeded so the same design always gets the same gates. With random sampling, two
    builds of one design placed gates slightly differently, and one build freed every part while
    the next left one attached. A result that changes between runs cannot be trusted or debugged.
    """
    pts = _surface_points(part, 4000, seed=seed)
    close, dist, _tri = trimesh.proximity.closest_point(frame_mesh, pts)
    order = np.argsort(dist)
    # Among the points that can carry a gate, the least visible ones come first. The frame decides
    # which points are reachable (near it, low on the plate). Inside that set a point is ranked by
    # how visible it is on the assembled model, and distance only breaks ties. `seen` maps card
    # points back to the assembled model and measures them there.
    if seen is not None:
        ok = [i for i in order if pts[i][2] <= GATE_H * 1.6 and dist[i] <= GATE_MAX][:320]
        if ok:
            _c, _d, tri = trimesh.proximity.closest_point(part, pts[ok])
            v = seen(pts[ok], part.face_normals[tri])
            score = v + 0.015 * dist[ok]
            front = [ok[j] for j in np.argsort(score, kind="stable")]
            rest = [i for i in order if i not in set(front)]
            order = np.asarray(front + rest)

    # A filter must never leave a part without gates. A part with one gate instead of two can fail
    # to come off the card at all. So the thickness rule is a preference: pick with it first, and
    # if that cannot find enough places, pick again without it. A part gated through a thin
    # section might break, but a part with no gate is certainly lost.
    picked = []
    for fussy in (True, False):
        picked = _choose(part, pts, close, dist, order, want, keep_out, fussy)
        if len(picked) >= want:
            break
    return _gates_from(picked, frame_mesh)


def _choose(part, pts, close, dist, order, want, keep_out, fussy):
    """Which points on the part to gate from. `fussy` applies the thickness and length rules."""
    picked = []
    for i in order:
        a = np.asarray(pts[i], float)              # on the part
        b = np.asarray(close[i], float)            # on the frame
        if a[2] > GATE_H * 1.6:                    # a gate must stay down at frame level
            continue
        # Measure gate separation in the plane, not in 3D. Two gates 1.7 mm apart across the part
        # but a few millimetres apart in Z would pass a 3D distance test, yet they behave as one
        # wide gate with a nick in it and the part does not come off.
        if any(np.linalg.norm(a[:2] - q[:2]) < sprue.MIN_GATE_SEP for q in picked):
            continue
        # Never gate onto a joint. A post can be thinner than the nipper's bite (for example a
        # 2.8 mm post against a 3.06 mm bite), so a gate that lands on one severs it outright. On
        # a seated part the material nearest the frame is often exactly a post sticking out.
        if any(float(np.linalg.norm(a - k)) < r for k, r in keep_out):
            continue
        # Avoid thin sections too. Where the part is barely thicker than the nipper's bite, the
        # cut goes straight through it, and a slender part comes off in pieces. Keeping clear of
        # the joints is not enough when the whole part is thin.
        if fussy:
            # A gate must also stay short. Searching for thick material can move the attachment
            # point up into the part, and the gate grows to span the distance (over 10 mm against
            # about 7 mm for a good gate). A long gate leaves a long whisker, the recovered piece
            # comes out much longer than its part, and the round trip then mismatches parts.
            # A wider cutter does not fix this. It does not reduce the whisker, and its larger
            # bite starts severing thin parts again.
            if float(dist[i]) > GATE_MAX:
                continue
            thick = _thickness_at(part, a, b)
            if thick is not None and thick < GATE * NIPPER * 1.6:
                continue
        picked.append(a)
        if len(picked) >= want:
            break
    return picked


def _gates_from(picked, frame_mesh):
    """Build the gate solids for the chosen points."""
    out = []
    for a in picked:
        _c, _d, _t = trimesh.proximity.closest_point(frame_mesh, a.reshape(1, 3))
        b = np.asarray(_c[0], float)
        d = a - b
        L = float(np.linalg.norm(d))
        if L < 1e-6:
            d, L = np.array([0.0, 1.0, 0.0]), 1.0
        u = d / L
        p0 = b - u * GATE_ROOT
        p1 = a + u * GATE_BITE
        length = float(np.linalg.norm(p1 - p0))
        u2 = (p1 - p0) / length
        g = trimesh.creation.box(extents=[GATE, GATE, length])
        g.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], u2))
        g.apply_translation((p0 + p1) / 2.0)
        # A gate must not reach below the plate. It is aimed at the closest point on the part, and
        # a part resting on the plate touches z=0 there, so the gate would be a bar centred on
        # z=0 with half of it below the plate. The slicer then lowers the whole card until that
        # nub touches the bed, and the frame and every part start several layers up, printing
        # into the air.
        #
        # Translating the finished gate upwards does not fix it. A gate is built to span exactly
        # from the frame to the part, and moving it bodily detaches it from both, leaving loose
        # bars and unattached parts.
        #
        # So the aim is raised, not the gate. Both endpoints are moved up before the gate is
        # built, so it clears the plate by construction and still lands on the two things it
        # joins. The frame is solid from z=0 to FRAME_T, so a root at this height is still inside
        # it, and `low_edge` only offers part material within the gate's height band.
        # The floor applies to the box, not its axis. A square bar's lowest corner can sit up to
        # half its diagonal below its centreline (1.27 mm for a 1.8 mm section, not 0.9). A gate
        # only microns below the plate still triggers the z=0 trim in `build`, and that trim can
        # leave holes that make the whole card impossible to cut.
        floor = GATE * 0.75
        if p0[2] < floor or p1[2] < floor:
            p0 = np.array([p0[0], p0[1], max(float(p0[2]), floor)])
            p1 = np.array([p1[0], p1[1], max(float(p1[2]), floor)])
            length = float(np.linalg.norm(p1 - p0))
            if length < 1e-6:
                continue
            u2 = (p1 - p0) / length
            g = trimesh.creation.box(extents=[GATE, GATE, length])
            g.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], u2))
            g.apply_translation((p0 + p1) / 2.0)
        # A gate that is only a hair below the plate is lifted, not re-aimed. Re-aiming would move
        # it off the two things it joins, while a lift of a few microns cannot detach anything and
        # keeps the card off the trim path.
        dip = -float(g.bounds[0][2])
        if 0 < dip <= 0.15:
            g.apply_translation([0.0, 0.0, dip])
            p0 = np.asarray(p0, float) + np.array([0.0, 0.0, dip])
            p1 = np.asarray(p1, float) + np.array([0.0, 0.0, dip])
        # keep the axis and the span, so the nippers can be built to overshoot it exactly
        out.append((g, (float(a[0]), float(b[1]), float(a[1])),
                    (p0.tolist(), p1.tolist())))
    return out


def oriented(parts, made, verbose=False):
    """Turn every part so its posts lie in the print plane where possible.

    A post printed standing in Z shears along its layer lines, so posts should print lying down.

    Bed adhesion normally outranks support. `simulator.best_orientation` scores contact area first
    because a part balanced on a post tip with about 11 mm2 on the plate comes loose part way
    through the print, however little support it needed.
    """
    # On a sprue, bed adhesion is partly the frame's job. A part gated to a frame with a large
    # footprint is held down even with very little contact of its own. What the frame cannot fix
    # is a post printed standing in Z, or support scarring a mating face. So the same candidate
    # orientations are scored for this situation instead of the stand-alone one.
    axes = {}
    for j in made:
        axes.setdefault(j["child"], []).append(j["axis"])
    out, log = {}, []
    for n, m in parts.items():
        best = None
        for rot in S.candidate_orientations():
            q = m.copy()
            if rot is not None:
                q.apply_transform(rot)
            q.apply_translation([0, 0, -q.bounds[0][2]])
            rep = S.overhang_report(q)
            pegs = max((S.peg_axis_vs_plate(a, rot) for a in axes.get(n, ())), default=0.0)
            # This function is not on the default path. `build` runs `seated()` and reaches
            # `oriented()` only when seat=False. Changes here do not show up in a default build.
            # A part with no first layer is not printable however little support it needs. The
            # bed term is capped at 0.35 while support scores up to 2.0, so without a penalty an
            # orientation with marginally less overhang can win even with the part standing on
            # end. Starvation is penalised rather than contact rewarded, so nothing changes for a
            # part that already has a first layer.
            starved = max(0.0, 1.0 - rep["bed_area"] / 14.0)
            score = (-rep["support_frac"] * 2.0
                     - (pegs / 90.0) * 1.6
                     - starved * 1.2
                     + min(rep["bed_area"], 300.0) / 300.0 * 0.35)
            if best is None or score > best[0]:
                best = (score, rep, pegs, q)
        if best is None:
            out[n] = m
            continue
        _score, rep, pegs, turned = best
        out[n] = turned
        log.append({"part": n, "support_frac": round(rep["support_frac"], 3),
                    "bed_mm2": round(rep["bed_area"], 1), "post_off_plate_deg": round(pegs, 1)})
    if verbose:
        for r in sorted(log, key=lambda r: -r["support_frac"]):
            print(f"  {r['part']:12s} support {r['support_frac']*100:4.1f}%  "
                  f"bed {r['bed_mm2']:6.1f} mm2  post {r['post_off_plate_deg']:4.1f} deg off plate")
    return out, log


SOLE = 0.9               # how much is shaved off a part's underside to make it a real first layer
# The smallest sole step must fit parts with very little room before a post. A part that clears
# only 0.23 mm before its post cannot take a 0.3 mm cut, and without a sole it prints on a few
# mm2 of line contact. 0.2 mm is one layer at this layer height, which is the smallest useful cut.
SOLE_STEPS = (0.0, 0.2, 0.3, 0.6, 0.9, 1.2, 1.5)
SOLE_CLEAR = 0.4         # and how far the cut must stay clear of any post or socket
MIN_BED = 30.0           # the smallest first layer a part is allowed to print on
REST_FACES = 60          # how many resting directions to try, biggest hull face first


def bed_area(mesh, layer=0.20):
    """The area the first layer lays down, which is all that holds a part to the plate.

    This number decides whether a print survives. A part with under about 5 mm2 of first layer
    comes loose in the first few layers and the nozzle drags it, turning the plate into a tangle.
    Only parts with a real footprint stay on the plate.
    """
    z = float(mesh.bounds[0][2]) + layer / 2.0
    try:
        sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            return 0.0
        flat, _ = sec.to_2D()
        return float(sum(abs(p.area) for p in flat.polygons_full))
    except Exception:
        return 0.0


def rest_orientations(mesh, n=REST_FACES):
    """Every direction this part can actually rest on, biggest resting face first.

    Axis-aligned rotations are not enough for a part modelled at an angle, for example a limb in
    a diagonal pose, where no quarter turn lays it flat. The directions a part can rest on are the
    normals of its own convex hull, which is what a part does when dropped on a table.
    """
    hull = mesh.convex_hull
    normals = np.asarray(hull.face_normals, float)
    areas = np.asarray(hull.area_faces, float)
    keep = []
    for i in np.argsort(-areas):
        v = normals[i]
        if all(float(np.dot(v, k)) < 0.985 for k in keep):
            keep.append(v)
        if len(keep) >= n:
            break
    return keep


def _feature_floor(part_name, made, R):
    """How low the lowest post or socket wall sits once the part is turned this way.

    A sole cut through a post is a broken joint, and nothing downstream would catch it: the joint
    check rebuilds each post from its template rather than reading it off the part, so a shaved
    post still reports as fitting. The cut has to be stopped here, by the geometry itself.
    """
    floor = np.inf
    for j in made:
        if part_name == j["child"]:
            # The post is measured without its backset. `male` normally carries a 3.5 mm backset
            # so the post unions cleanly with its part. That tail is buried inside the part and
            # needs no protecting, but on a thin part it reaches out through the opposite face,
            # reads as "a post at the very bottom" in every direction and blocks every sole.
            # What must survive a sole is the post that sticks out.
            f = J.male(j["type"], j["size"], j["axis"], j["at"], backset=0.0)
        elif part_name == j["parent"]:
            # The hole is a void, and what must survive is the wall around it, starting at the mouth.
            # A protective solid carrying the backset would reach out of the part into open air
            # and block soles that would never touch the socket.
            f = J.male(j["type"], j["size"] + 2.0, j["axis"], j["at"], backset=0.0,
                       length=J._default_length(j["type"], j["size"]) + J.SOCKET_DEPTH)
        else:
            continue
        q = f.copy()
        q.apply_transform(R)
        floor = min(floor, float(q.bounds[0][2]))
    return floor


def seated(parts, made, verbose=False):
    """Sit every part on a face it can rest on, then shave that face flat.

    The flat sole lets orientation serve the posts. Bed contact and post direction otherwise pull
    against each other. A flat sole gives a rounded part a real first layer in any orientation,
    so the turn can be chosen for the posts.

    The cost is small. A 0.9 mm sole takes 0.2 to 12 percent of a part's volume, from a face that
    is already the gate-mark side. The alternative is splitting rounded parts and gluing them.
    """
    out, log, notes_bad = {}, [], []
    for n, m in parts.items():
        best = None
        for v in rest_orientations(m):
            R = trimesh.geometry.align_vectors(np.asarray(v, float), [0.0, 0.0, -1.0])
            q = m.copy()
            q.apply_transform(R)
            drop = float(q.bounds[0][2])
            q.apply_translation([0, 0, -drop])
            T = np.eye(4)
            T[:3, :3] = R[:3, :3]
            T[:3, 3] = R[:3, 3] - np.array([0.0, 0.0, drop])
            headroom = _feature_floor(n, made, T) - SOLE_CLEAR
            # The sole's own drop belongs in the recorded matrix. Cutting at z=d and then standing
            # the part back on the plate moves it another d. Leaving that out puts every soled
            # part d millimetres off when it is mapped back to check its joints.
            s, d, a, drop2 = q, 0.0, bed_area(q), 0.0
            for d in SOLE_STEPS:
                if d > headroom:
                    break
                s, drop2 = q, 0.0
                if d > 0:
                    # A rejected cut must not be left in `s`. `continue` skips the rest of the
                    # body but does not undo an assignment above it, so the last rejected slice
                    # would be what the loop exits holding.
                    cut = q.slice_plane(plane_origin=[0, 0, d], plane_normal=[0, 0, 1], cap=True)
                    if (cut is None or not len(cut.faces) or not cut.is_watertight
                            or len(cut.split(only_watertight=False)) > 1 or not cut.is_volume):
                        s, drop2 = q, 0.0          # keep the last sound shape, not the failed cut
                        continue
                    # A sole deep enough to split the part into several bodies is a cut, not a
                    # sole. A part that is not a single volume fails the whole card union, which
                    # then falls back to a plain concatenation and leaves loose pieces. No repair
                    # can rejoin severed bodies, so that depth is refused above.
                    s = cut.copy()
                    drop2 = float(s.bounds[0][2])
                    s.apply_translation([0, 0, -drop2])
                a = bed_area(s)
                if a >= MIN_BED:
                    break
            T = T.copy()
            T[2, 3] -= drop2
            rep = S.overhang_report(s)
            posts = [np.asarray(j["axis"], float) for j in made if j["child"] == n]
            tilt = max((abs(float(np.degrees(np.arcsin(
                np.clip(abs((T[:3, :3] @ p)[2]), 0, 1))))) for p in posts), default=0.0)
            # bed first, because that is what makes a print fail. Posts and support decide between
            # the orientations that clear the bar
            # The starvation term is a guard. Bed area is scored proportionally, so 5 mm2 and
            # 30 mm2 differ by only 0.6 of the 3.0 available, which is less than the tilt term can
            # swing. Without the guard a starved orientation could win on a small gain in post
            # angle. It does not help a part whose best available orientation is itself starved.
            starved = max(0.0, 1.0 - a / 14.0)
            score = (min(a, 120.0) / 120.0 * 3.0
                     - (tilt / 90.0) * 1.0
                     - starved * 1.5
                     - rep["support_frac"] * 0.8)
            if best is None or score > best[0]:
                best = (score, s, T, a, d, tilt, rep["support_frac"])
        if best is None:
            out[n] = m
            continue
        _sc, mesh, T, a, d, tilt, sup = best
        # Seating can break a part that was sound. The turn plus the trim at z=0 can leave a few
        # degenerate faces, and one bad part fails the whole card union. Repair it here, where the
        # damage happens, and report it if the repair does not work.
        if not mesh.is_volume:
            fixed = heal(mesh)
            if fixed is not None and fixed.is_volume:
                mesh = fixed
            else:
                notes_bad.append(n)
        out[n] = mesh
        log.append({"part": n, "bed_mm2": round(a, 1), "sole_mm": d,
                    "post_off_plate_deg": round(tilt, 1), "support_frac": round(sup, 3),
                    "matrix": T.tolist(),
                    # the size as seated, so a later step can tell a pure slide on the card from a
                    # rotation the packer applied, instead of assuming which one happened
                    "size_mm": [float(v) for v in (mesh.bounds[1] - mesh.bounds[0])],
                    # and where it sat before the layout moved it. `seated` only drops a part to
                    # z=0, so its x and y are wherever the turn left them. Reading the slide off
                    # the placed part's corner alone would count that offset twice.
                    "origin_mm": [float(v) for v in mesh.bounds[0]],
                    "lost_pct": round(100.0 * (1.0 - mesh.volume / parts[n].volume), 1)})
    if verbose:
        for r in sorted(log, key=lambda r: r["bed_mm2"]):
            print(f"  {r['part']:12s} bed {r['bed_mm2']:7.1f} mm2  sole {r['sole_mm']:.1f} mm  "
                  f"post {r['post_off_plate_deg']:4.1f} deg  support {r['support_frac']*100:4.1f}%  "
                  f"-{r['lost_pct']:.1f}% volume")
    if notes_bad:
        print(f"  ! seating left {', '.join(notes_bad)} not a volume and the repair did not take, "
              f"the card union will fail and leave every part loose")
    return out, log


def _slide(mesh, by, matrix):
    """Translate `mesh` and return the running record of every move applied to it.

    Where a part ended up on the card cannot be recovered from the part itself. A part reaches
    the card by a turn (`seated`, which records its matrix) and then a layout move, and the layout
    move may include a 90 degree spin as well as a slide. Reading the move back off the placed
    mesh's corner gives the wrong answer for the spun parts, with no way to tell which those were.
    Recording each move as it is made avoids that.
    """
    by = np.asarray(by, float)
    mesh.apply_translation(by)
    T = np.eye(4)
    T[:3, 3] = by
    return T @ matrix


BAR_PITCH = 34.0         # roughly how often a bar should cross the card, when there is room
BAR_CLEAR = 3.0          # a bar must miss every part by at least this
# Runner bars are narrower than the outer frame. The frame carries the whole card, while a runner bar
# only carries parts. Reserving the frame's width for each bar lane wastes the difference on
# every row (18 mm over six rows), which can decide whether a card fits the bed. One constant is
# used by both the lane and the bar box so they cannot drift apart.
BAR_W = 3.0              # the runner bars that cross the card, narrower than the frame


def _free_bands(placed, H, want=BAR_PITCH, clear=BAR_CLEAR):
    """Heights at which a bar can cross the whole card without touching a part."""
    spans = sorted((float(p.bounds[0][1]) - clear, float(p.bounds[1][1]) + clear)
                   for p in placed.values())
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    gaps = []
    prev = FRAME_W
    for lo, hi in merged:
        if lo - prev > 3.2:
            gaps.append((prev, lo))
        prev = max(prev, hi)
    if H - FRAME_W - prev > 3.2:
        gaps.append((prev, H - FRAME_W))
    bars = []
    for lo, hi in gaps:
        n = max(1, int((hi - lo) // want))
        for i in range(n):
            bars.append(lo + (hi - lo) * (i + 0.5) / n)
    return bars


def lay_out_packed(parts, inner_w=200.0, inner_h=250.0):
    """Nest with MaxRects instead of rows, and rotate parts 90 degrees where that helps.

    There are no shelves in this layout, so bar positions cannot be derived from rows. The runner
    has to be routed separately (see `routed_runner`). Gates are aimed by geometry, so a bar only
    has to be near a part, not directly underneath it.
    """
    placed, moved = {}, {}
    for n, m in parts.items():
        p = m.copy()
        placed[n] = p
        moved[n] = _slide(p, [0, 0, -p.bounds[0][2]], np.eye(4))
    pad = GAP + sprue.GAP
    sizes = {n: (float(p.bounds[1][0] - p.bounds[0][0]) + pad,
                 float(p.bounds[1][1] - p.bounds[0][1]) + pad) for n, p in placed.items()}
    got = maxrects(sizes, inner_w, inner_h)
    if got is None:
        return None
    shapes, top = {}, 0.0
    for n, (x, y, rot) in got.items():
        p = placed[n]
        if rot:
            R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1])
            p.apply_transform(R)
            moved[n] = R @ moved[n]
            moved[n] = _slide(p, [0, 0, -p.bounds[0][2]], moved[n])
        dx = FRAME_W + x + pad / 2 - float(p.bounds[0][0])
        dy = FRAME_W + y + pad / 2 - float(p.bounds[0][1])
        moved[n] = _slide(p, [dx, dy, 0.0], moved[n])
        shapes[n] = footprint(p)
        top = max(top, float(p.bounds[1][1]))
    H = top - FRAME_W + pad / 2 + FRAME_W * 2
    return placed, shapes, (inner_w + 2 * FRAME_W, H), None, moved


# Reading-order layout. The caller fills these in through build(rows=..., down=..., across=...).
# Laying the parts out in the order they assemble (top to bottom) makes a kit that
# can be put together without instructions, because the card itself shows where each part goes.
#
# Spinning a part about Z after `seated` has chosen its resting face changes nothing about its
# bed contact, overhangs or first layer, so the reading order costs nothing that matters for print.
#
# ANATOMY is a list of rows of part names in reading order, top row first. Parts not named in any
# row are placed in a last row.
ANATOMY = []
# DOWN is the set of parts whose long axis should point down the card, for example long thin
# parts that hang. Every part of the same kind should be listed, or an unlisted one keeps its
# original angle and can set the width of the whole card by itself.
DOWN = set()
# how far a row must sit above its own bar so the bar's edge, not its centreline, keeps clear
BAR_ROOM = BAR_CLEAR + FRAME_W / 2.0
# ACROSS is the set of parts whose long axis should lie across the card. A long flat part standing
# lengthwise makes its row as tall as the part, which can push the card past the bed. Turned
# across, its row is only as tall as its width.
ACROSS = set()


def _spin_flat(mesh, want):
    """Turn a part about Z so its long axis lies the way the card wants it.

    Only about Z. Any other axis would change which face is on the plate, and `seated` chose that
    face to give the part a first layer.
    """
    if want is None:
        return mesh, 0.0
    v = np.asarray(mesh.vertices, float)[:, :2]
    c = v.mean(axis=0)
    u, s, vt = np.linalg.svd(v - c, full_matrices=False)
    ang = float(np.arctan2(vt[0][1], vt[0][0]))          # where its long axis points now
    target = np.pi / 2 if want == "down" else 0.0
    turn = target - ang
    # There is no search for a narrower angle here. The card's width is set by its widest row, so
    # turning each part to its narrowest angle looks useful, but narrowing a part makes it taller
    # and every row grows with it. Measured on one card, a free search took the length from
    # 235.6 mm to 265.4 mm (past a 256 mm bed) and did not reduce the width at all.
    # The intent is then enforced on the bounding box, which is what the card pays for. "down"
    # means the part's long dimension runs down the card. The SVD is only a guess at which
    # dimension that is, and on a bent part with a large end it can guess wrong, leaving one part
    # wide enough to set the width of the whole card.
    # This costs no row height in practice. It only ever swaps a part's two box sides, and a row
    # is as tall as its tallest part, so turning a part upright rarely makes the row taller.
    for extra in (0.0, np.pi / 2):
        t = turn + extra
        R = trimesh.transformations.rotation_matrix(t, [0, 0, 1], mesh.bounds.mean(axis=0))
        pts = trimesh.transform_points(np.asarray(mesh.vertices, float), R)
        wide = float(pts[:, 0].max() - pts[:, 0].min())
        tall = float(pts[:, 1].max() - pts[:, 1].min())
        if (want == "down" and tall >= wide) or (want == "across" and wide >= tall):
            turn = t
            break
    m = mesh.copy()
    m.apply_transform(trimesh.transformations.rotation_matrix(
        turn, [0, 0, 1], mesh.bounds.mean(axis=0)))
    # The drop to the plate is the caller's job. The caller rebuilds this function's work from the
    # returned `turn`, which is a rotation only, and then slides the part down itself. Dropping
    # here as well would leave the caller's slide at zero and the recorded transform missing a
    # translation that was actually applied.
    return m, turn


def lay_out_anatomical(parts, inner_w=200.0, rows=None, down=None, across=None):
    """Lay the card out in reading order: the rows given, top to bottom, then any other parts.

    The layout is 2D and the model is 3D, so it is a reading order rather than a literal exploded
    view. A row that will not fit the card's width wraps, and any part the rows do not name is
    added in a last row rather than dropped.
    """
    rows = ANATOMY if rows is None else rows
    down = DOWN if down is None else set(down)
    across = ACROSS if across is None else set(across)
    placed, shapes, moved = {}, {}, {}
    order, seen = [], set()
    for row in rows:
        keep = [n for n in row if n in parts]
        if keep:
            order.append(keep)
        seen.update(keep)
    leftover = sorted(n for n in parts if n not in seen)
    if leftover:
        order.append(leftover)                            # parts no row named

    for n, m in parts.items():
        want = "down" if n in down else ("across" if n in across else None)
        p, turn = _spin_flat(m.copy(), want)
        placed[n] = p
        R = np.eye(4)
        if turn:
            R = trimesh.transformations.rotation_matrix(turn, [0, 0, 1], m.bounds.mean(axis=0))
        moved[n] = _slide(p, [0, 0, -p.bounds[0][2]], R)

    # The card is as wide as its widest row, not as wide as the bed. A fixed width leaves empty
    # frame beside narrow rows, which wastes filament and makes the reading order harder to see.
    need = 0.0
    for row in order:
        need = max(need, sum(float(placed[n].bounds[1][0] - placed[n].bounds[0][0]) + GAP
                             for n in row))
    # The width needs a little slack, or the row that defined it wraps out of it. Without slack the
    # usable width equals `need` exactly, and the last part on the widest row can fail
    # `wide + w > usable` on floating point alone. That throws it onto a line of its own and costs
    # a whole runner lane plus its height.
    inner_w = min(inner_w, max(need + 2 * BAR_CLEAR + 0.5, 60.0))

    y = FRAME_W + GAP / 2 + BAR_W + 2 * BAR_CLEAR
    at, bar_ys = {}, []
    # Y grows upwards, so the first row placed is the bottom one. The rows are placed in reverse
    # so the first row given ends up at the top and the card reads from the top down.
    for row in reversed(order):
        # a row wider than the card wraps onto the next line rather than running off the edge
        # A part that reaches the side rail is welded to it, and snipping its gates cannot free
        # it, because the gates are not what holds it. The usable width is the inside of the
        # frame less that clearance at each end.
        usable = inner_w - 2 * BAR_CLEAR
        lines, line, wide = [], [], 0.0
        for n in row:
            w = float(placed[n].bounds[1][0] - placed[n].bounds[0][0]) + GAP
            if line and wide + w > usable:
                lines.append(line)
                line, wide = [], 0.0
            line.append(n)
            wide += w
        if line:
            lines.append(line)
        for line in lines:
            widths = [float(placed[n].bounds[1][0] - placed[n].bounds[0][0]) + GAP for n in line]
            tall = max(float(placed[n].bounds[1][1] - placed[n].bounds[0][1]) for n in line)
            # centred, so it reads straight, and never nearer the rail than a part may sit
            x = FRAME_W + BAR_CLEAR + max(0.0, (usable - sum(widths))) / 2.0
            for n, w in zip(line, widths):
                dx = x + GAP / 2 - float(placed[n].bounds[0][0])
                dy = y - float(placed[n].bounds[0][1])
                moved[n] = _slide(placed[n], [dx, dy, 0.0], moved[n])
                shapes[n] = footprint(placed[n])
                # `at` is relative to the inside of the frame, not an absolute position. The
                # shelf bar placer reads it as `FRAME_W + at.y + GAP/2 - BAR_BACK`, so absolute
                # coordinates would count the frame twice and put every bar through the row above.
                at[n] = (x - FRAME_W, y - FRAME_W - GAP / 2)
                x += w
            # A bar is a box with width, not a line. Deriving its position from `at` with the
            # shelf packer's formula can put its edge inside a row. So this layout places its own
            # bars: the bar's centre sits half its width plus the clearance below the row it
            # carries, and the next row starts beyond it.
            bar_ys.append(y - BAR_CLEAR - BAR_W / 2.0)
            # No extra `GAP` on top of the lane. The lane already has BAR_CLEAR on both sides of
            # the bar, so adding the part gap again would charge for the same clearance twice
            # (12 mm over six rows, enough to decide whether the card fits the bed).
            y += tall + GAP + BAR_W + 2 * BAR_CLEAR
    H = y - GAP / 2 + FRAME_W
    return placed, shapes, (inner_w + 2 * FRAME_W, H), at, moved, bar_ys


def lay_out(parts, inner_w=200.0):
    """Drop every part onto the frame plane and nest them in shelves, keeping each one's orientation.

    Nesting uses the bounding box, not the projected outline. The projection can under-report what
    a part occupies (a post, a brim, a piece the projector simplifies away), and parts nested by it
    can overlap each other. Fused parts cannot be snipped apart. The outline is still what
    the gates aim at. It does not decide how much room a part needs.
    """
    placed, shapes, moved = {}, {}, {}
    for n, m in parts.items():
        p = m.copy()
        placed[n] = p
        # stand it on the frame plane
        moved[n] = _slide(p, [0, 0, -p.bounds[0][2]], np.eye(4))
    sizes = {n: (float(p.bounds[1][0] - p.bounds[0][0]) + GAP,
                 float(p.bounds[1][1] - p.bounds[0][1]) + GAP) for n, p in placed.items()}
    at, (iw, ih) = sprue.shelf_nest(sizes, inner_w)
    for n, p in placed.items():
        dx = FRAME_W + at[n][0] + GAP / 2 - float(p.bounds[0][0])
        dy = FRAME_W + at[n][1] + GAP / 2 - float(p.bounds[0][1])
        moved[n] = _slide(p, [dx, dy, 0.0], moved[n])
        shapes[n] = footprint(p)
    return placed, shapes, (iw + 2 * FRAME_W, ih + 2 * FRAME_W), at, moved


# build() options.
# seat=True (default) runs `seated`, which gives each part a flat sole and a real first layer.
# orient=True runs `oriented` instead when seat=False. It lays posts in the print plane and makes
# the card flatter, but on some geometry it has left parts attached to the frame after snipping,
# for reasons not yet found, so it is off by default. `best_card` tries the options and keeps the
# one that passes the round trip.
# with_base=True adds a base plate from `base_for(parts)`. A model whose centre of mass is high
# over a small footprint topples, and a base fixes that. A model that stands on its own (its
# centre of mass projects inside its contact footprint) does not need one, so it is off by default.
def build(inner_w=200.0, verbose=True, with_base=False, orient=False, pack=True, seat=True,
          anatomical=True, source=None, base_for=None, rows=None, down=None, across=None, bed=None):
    # the parts, the joints between them and the notes come from the caller's source
    if source is None:
        raise ValueError("build() needs source=: a callable returning (parts, made, notes)")
    parts, made, notes = source()
    if with_base:
        # The base is part of the kit when the model cannot stand without it.
        base, spec = base_for(parts) if base_for else (None, None)
        if base is not None:
            parts["base"] = base
            notes.append(f"base {spec['size_mm'][0]}x{spec['size_mm'][1]} mm, sized for a "
                         f"{spec['tip_deg']} degree lean at a {spec['com_mm']} mm centre of mass")
    orient_log = []
    seat_log = []
    assembled = {n: m.copy() for n, m in parts.items()}
    if seat:
        # Each part needs its own first layer. The frame does not hold parts down at the start of
        # a print, because a gate at 2 mm height does not exist yet when layer 1 goes down. Parts
        # with under about 5 mm2 of first layer are dragged off the plate by the nozzle.
        parts, seat_log = seated(parts, made)
    elif orient:
        parts, orient_log = oriented(parts, made)
    # The reading-order layout is the default, because a kit that can be assembled without
    # instructions is worth more than a slightly denser pack.
    own_bars = None
    packed = lay_out_packed(parts, inner_w) if (pack and not anatomical) else None
    used_pack = packed is not None
    if packed is not None:
        placed, shapes, (W, H), at, moved = packed
    elif anatomical:
        placed, shapes, (W, H), at, moved, own_bars = lay_out_anatomical(parts, inner_w, rows=rows, down=down, across=across)
    else:
        placed, shapes, (W, H), at, moved = lay_out(parts, inner_w)

    if at is None:
        shelf_ys = []
    elif False:
        # Disabled. Density and runner access pull against each other. A dense MaxRects pack can
        # halve the card's area, but it leaves no full-width band for a bar to cross. Bars at a
        # fixed pitch run straight through parts and fuse them to the frame. Bars in the gaps
        # the packing left are what this branch would do. The routed runner replaced it.
        shelf_ys = [y - FRAME_W for y in _free_bands(placed, H)]
    else:
        shelf_ys = sorted({round(v[1], 3) for v in at.values()})
    # The bar must clear the parts by a margin. At 2.0 mm back it left 0.5 mm to the nearest part,
    # which is within the tolerance of a printed layer. A part touching its bar is fused to the
    # frame, and snipping its gates does not free it.
    # A layout that places its own bars returns them. The shelf packer's bars are inferred from
    # the row positions.
    bars = own_bars if own_bars is not None else [
        FRAME_W + y + GAP / 2 - BAR_BACK for y in shelf_ys]

    frame = [trimesh.creation.box(extents=[W, FRAME_W, FRAME_T],
                                  transform=trimesh.transformations.translation_matrix(
                                      [W / 2, FRAME_W / 2, FRAME_T / 2])),
             trimesh.creation.box(extents=[W, FRAME_W, FRAME_T],
                                  transform=trimesh.transformations.translation_matrix(
                                      [W / 2, H - FRAME_W / 2, FRAME_T / 2])),
             trimesh.creation.box(extents=[FRAME_W, H, FRAME_T],
                                  transform=trimesh.transformations.translation_matrix(
                                      [FRAME_W / 2, H / 2, FRAME_T / 2])),
             trimesh.creation.box(extents=[FRAME_W, H, FRAME_T],
                                  transform=trimesh.transformations.translation_matrix(
                                      [W - FRAME_W / 2, H / 2, FRAME_T / 2]))]
    # Tangent is not joined. A bar spanning exactly from one rail's inner face to the other's
    # touches them without overlapping, so each bar unions into a separate body. The bars run the
    # full width so they overlap both rails.
    for by in bars:
        frame.append(trimesh.creation.box(
            extents=[W, BAR_W, FRAME_T],
            transform=trimesh.transformations.translation_matrix(
                [W / 2, by, FRAME_T / 2])))

    # Part numbers go on the runner, as on a model kit. They are stamped on the frame rather than
    # on the part, so nothing is left on a piece after it is snipped. Numbering is alphabetical by
    # part name, so it does not change between builds.
    order = sorted(shapes)
    numbers = {n: i + 1 for i, n in enumerate(order)}
    for n, i in numbers.items():
        # With a branching runner there may be no bars to be nearest to. This is only used to
        # place the number (`_gates_for` aims at the frame mesh by geometry), so it is optional.
        lowest, xlo, xhi = low_edge(placed[n])
        bar = min(bars, key=lambda b: abs(b - lowest)) if bars else lowest
        # The stamp is sunk into the frame. Sitting it on the frame's top face leaves the two
        # touching without overlap, which unions as a separate body.
        # It also stays off the gates. Gates leave the bar on the side facing the part, so a
        # number centred on the bar can merge with a gate and survive the snip, holding the part
        # on. The far side of the bar is empty by construction.
        stamp = number_stamp(str(i), [(xlo + xhi) / 2, bar - 1.5 - MARK_H, FRAME_T - MARK_SINK],
                             depth=MARK_DEPTH + MARK_SINK)
        if stamp is not None:
            frame.append(stamp)

    # A dense pack is gated from a branching runner. There is no full-width band left for a bar,
    # so the runner branches in between the parts, as an injection-moulded sprue does. A branch
    # that would clip a part it is not serving is refused.
    unreached = []
    if used_pack:
        branches, unreached = routed_runner(placed, trimesh.util.concatenate(frame), W, H)
        frame.extend(branches)
        if unreached:
            notes.append(f"runner could not reach: {', '.join(unreached)}")

    frame_mesh = trimesh.util.concatenate(frame)
    seat_m = {r["part"]: np.asarray(r["matrix"], float) for r in seat_log}
    gates, gate_solids, gate_axes = [], [], []
    try:
        _scene = trimesh.util.concatenate([m for m in assembled.values()])
    except Exception:
        _scene = None
    for n in shapes:
        # Gates run from where the frame actually is to where the part actually is. Assuming the
        # part's lowest point sits directly above the nearest bar fails for a leaning part and
        # leaves it unattached. Closest point to closest point cannot miss.
        # The part's own joints are carried into the card frame so gates can avoid them. Each is a
        # sphere around the joint point, large enough to cover the post and the cutter's bite.
        # A joint has to be found where it ended up, not where it was modelled. A part reaches the
        # card by two moves (the seating turn, then the layout move), and applying only one puts
        # the keep-out sphere far from the post it protects.
        keep_out = []
        M = seat_m.get(n, np.eye(4))
        L = moved.get(n, np.eye(4))
        for j in made:
            if n not in (j["child"], j["parent"]):
                continue
            p = np.asarray(j["at"], float)
            p = (L @ M @ np.append(p, 1.0))[:3]
            keep_out.append((p, float(j["size"]) * 0.5 + GATE * 1.2))
        _home = np.linalg.inv(L @ M)

        def _seen(pp, nn, _home=_home):
            ph = trimesh.transform_points(np.asarray(pp, float), _home)
            nh = np.asarray(nn, float) @ _home[:3, :3].T
            nh = nh / np.maximum(np.linalg.norm(nh, axis=1, keepdims=True), 1e-9)
            return visibility(_scene, ph, nh)
        for g, span, ends in _gates_for(placed[n], frame_mesh, keep_out=keep_out,
                                        seen=_seen if _scene is not None else None):
            gate_solids.append(g)
            gate_axes.append(ends)
            gates.append((n,) + span)

    # "Not all meshes are volumes!" does not say which mesh. If the union fails, the report names
    # every input that is not a volume, or says that all inputs are volumes.
    named = ([(n, m) for n, m in placed.items()]
             + [(f"frame[{i}]", m) for i, m in enumerate(frame)]
             + [(f"gate[{i}] on {gates[i][0]}", m) for i, m in enumerate(gate_solids)])
    try:
        card = trimesh.boolean.union([m for _n, m in named])
    except Exception as e:
        rotten = [n for n, m in named if not m.is_volume]
        card = trimesh.util.concatenate([m for _n, m in named])
        notes.append(f"card union failed ({e}); parts left loose"
                     + (f", not a volume: {', '.join(rotten)}" if rotten
                        else ", every input IS a volume, so the union itself failed"))

    # Count bodies only after dropping slivers. The union leaves tiny shells of zero or negative
    # volume at the seams, and counting them makes a fully connected card look like several bodies.
    card = _despeckle(card)
    # The plate is the floor. Lifting the gates fixes the usual cause, and this trim is the guarantee,
    # because anything that dips below z=0 makes the slicer lift the whole card off the plate.
    if float(card.bounds[0][2]) < -1e-6:
        cut = card.slice_plane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], cap=True)
        if cut is not None and len(cut.faces):
            card = _despeckle(cut)
            notes.append("trimmed material that hung below the plate")
    card.apply_translation([0, 0, -float(card.bounds[0][2])])
    # Heal last, after the trim. Healing first and then slicing at z=0 can break the mesh again.
    # A few broken faces are invisible to every other measurement here and stop a boolean.
    if not card.is_volume:
        card = heal(card)
    if not card.is_volume:
        notes.append(f"THE CARD IS NOT A SOLID: watertight={card.is_watertight}, "
                     f"winding={card.is_winding_consistent}, no gate can be cut")
    # How much of the card touches the plate on layer one. A card that rests only on gate nubs
    # (a few mm2 out of a card hundreds of millimetres across) prints in the air.
    first_layer = bed_area(card)
    if first_layer < 2000.0:
        notes.append(f"FIRST LAYER IS ONLY {first_layer:.0f} mm2, the card is not sitting on the "
                     f"plate and will print in the air")
    tall = float(card.bounds[1][2] - card.bounds[0][2])
    # The bed check measures the built card, not the plan. `W` and `H` from the layout are an
    # accumulation of row heights and say whether the layout fits, not whether the built card
    # does. Anything that reaches past the frame (number stamps, for example) can make the built
    # card larger than planned. One measured case was 17.8 mm longer than its plan.
    # That error can stay hidden while the card still fits, and only show once an unrelated change
    # moves the parts. The plan is kept beside the measurement so a divergence is reported.
    planned = (float(W), float(H))
    W = float(card.bounds[1][0] - card.bounds[0][0])
    H = float(card.bounds[1][1] - card.bounds[0][1])
    if abs(W - planned[0]) > 0.5 or abs(H - planned[1]) > 0.5:
        notes.append(f"the card came back {W:.1f} x {H:.1f} mm where the layout planned "
                     f"{planned[0]:.1f} x {planned[1]:.1f}, something reaches past the frame")
    bed = sprue.BED if bed is None else bed
    fits = W <= bed[0] and H <= bed[1]
    bodies = len(card.split(only_watertight=False))
    if verbose:
        print(f"  {len(placed)} parts on a card {W:.1f} x {H:.1f} x {tall:.1f} mm, "
              f"{len(gates)} gates, {bodies} body(ies)")
        print(f"  first layer on the plate: {first_layer:.0f} mm2")
        print(f"  fits the bed {bed[0]} x {bed[1]}: {fits}")
        print(f"  mass {card.volume * S.PLA_DENSITY / 1e6:.1f} g")
        for x in notes:
            print(f"  ! {x}")
    return {"card": card, "parts": placed, "gates": gates, "gate_solids": gate_solids,
            "gate_axes": gate_axes, "frame": frame_mesh, "numbers": numbers,
            "size": (W, H, tall), "fits_bed": bool(fits), "bodies": bodies,
            "first_layer_mm2": float(first_layer),
            "notes": notes, "joints": made, "orient": orient_log, "seat": seat_log,
            # The layout's own record of where each part went, kept by `_slide`. Re-deriving the
            # move from a placed part's corner, and detecting a spin by comparing bounding-box
            # extents, fails for a part with a round footprint: a spun disc has the same extents,
            # so it is mapped back to the wrong place.
            "moved": moved,
            "packed": used_pack}


NIPPER = 1.35            # how much wider than the gate the cutter is: a real nipper's bite


OVERSHOOT = 1.6          # mm the nippers reach past each end of the gate
VOL_TOL = 0.18           # a snipped part loses its gate stubs, and this is what that costs
BBOX_TOL = 4.0           # and the nipper bites GATE*NIPPER wide plus the overshoot
# The volume tolerance scales with part size, as `roundtrip.py` already does for area. A gate stub
# is the same size whatever it is attached to, so a flat fraction passes every large part and
# fails every small one. A part's volume goes as the cube of its scale while its stub does not:
# scaling a model down to 0.92 raised the stub's share by about a third, and four identical small
# parts recovered at 14.7% to 19.4% off, either side of a flat 18% bar.
# This does not hide a fused part. A part that never comes off stays inside the frame body, so it
# fails on identity before any tolerance is consulted.
SMALL_VOL_MM3 = 60.0     # below this a part is mostly gate stub by volume
SMALL_VOL_TOL = 0.35     # the same allowance `roundtrip.SMALL_AREA_TOL` makes, for the same reason


def vol_tol_for(part_volume):
    """How far a recovered piece may differ from its part, given how small that part is."""
    return SMALL_VOL_TOL if float(part_volume) < SMALL_VOL_MM3 else VOL_TOL


def snip(card, gate_solids, gate_axes=None, parts=None, owners=None):
    """Cut every gate, overshooting at the frame end, the way nippers would.

    The shared `roundtrip.snip` cannot do this. It builds each cutter as a box running in Y at a
    fixed x, because on a flat card every gate hangs straight down from a shelf bar. These gates
    are aimed by geometry and run at angles, so a Y-aligned box would miss them.

    Scaling the gate about its centre is not enough either. A proportional scale extends a short
    gate by very little, which can leave a part welded to the frame by a fraction of a millimetre
    at each end. A fixed overshoot does not depend on the gate's length.
    """
    cutters = []
    for i, g in enumerate(gate_solids):
        if gate_axes and i < len(gate_axes):
            p0, p1 = (np.asarray(v, float) for v in gate_axes[i])
            d = p1 - p0
            L = float(np.linalg.norm(d))
            if L > 1e-6:
                u = d / L
                # The cutter is round. `align_vectors` fixes the axis but not the roll around it,
                # so a square cutter and a square gate can sit turned relative to each other. A
                # 1.8 mm square turned 45 degrees needs 2.55 mm of clearance, and corners left
                # behind form hairline webs that hold a part on the frame and are invisible to
                # distance and overlap checks. A round cutter has no roll.
                # The cutter must not cut into the part. The gate already reaches GATE_BITE into
                # the part, so an overshoot at that end goes deep inside it and can split a small
                # part with a bore through it. A flush cutter stops at the part's surface and
                # takes its overshoot only at the frame end, where there is nothing to damage.
                surface = p1 - u * GATE_BITE          # where the gate meets the part
                start = p0 - u * OVERSHOOT            # and well inside the frame
                end = surface + u * 0.25              # a whisker past the skin, no more
                span = float(np.linalg.norm(end - start))
                if span < 1e-6:
                    continue
                # The cutter radius needs real margin. A 1.8 mm square gate has a half diagonal
                # of 1.273 mm. A radius of 0.72 x 1.8 = 1.296 mm clears it on paper but not in
                # floating point, and the corners survive as webs. 0.85 x 1.8 = 1.53 mm gives a
                # real margin.
                # The cut follows the part's own surface, the way a flush cutter is used. A cutter
                # that stops square to the gate meets a curved part at an angle, so one side of
                # the gate stands proud as a small cube and the other side bites a notch into the
                # part. Stopping square can only trade one defect for the other.
                # So when the part is known, the cutter reaches deep into the part and the part
                # itself is subtracted from the cutter. Everything of the gate outside the part is
                # removed and nothing of the part is. The gate's buried root stays inside the
                # part, where it cannot be seen.
                own = None
                if parts is not None and owners is not None and i < len(owners):
                    own = parts.get(owners[i])
                if own is not None:
                    end = surface + u * (GATE_BITE + 0.4)
                    span = float(np.linalg.norm(end - start))
                c = trimesh.creation.cylinder(radius=GATE * 0.85, height=span, sections=32)
                c.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], u))
                c.apply_translation((start + end) / 2.0)
                if own is not None:
                    try:
                        cc = c.difference(own)
                        if cc is not None and not cc.is_empty and len(cc.faces):
                            c = cc
                        else:
                            c = None
                    except Exception:
                        c = None
                    if c is None:              # fall back to the square stop
                        end = surface + u * 0.25
                        span = float(np.linalg.norm(end - start))
                        c = trimesh.creation.cylinder(radius=GATE * 0.85, height=span, sections=32)
                        c.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], u))
                        c.apply_translation((start + end) / 2.0)
                cutters.append(c)
                continue
        c = g.copy()
        c.apply_transform(trimesh.transformations.scale_matrix(NIPPER, c.bounds.mean(axis=0)))
        cutters.append(c)
    # `trimesh.util.concatenate` is not a boolean union. It merges face lists and nothing else.
    # Two gates on one part can sit closer together than a cutter is wide, so their cutters
    # overlap, and concatenating them gives a self-intersecting solid. A difference against that
    # is undefined in the overlap and can leave a thin web that holds the part on the card.
    # The cutters are unioned properly, with a fallback of cutting one at a time, which is slower
    # but always correct.
    try:
        tool = trimesh.boolean.union(cutters)
    except Exception:
        tool = None
    if tool is None or tool.is_empty or not len(tool.faces):
        opened = card
        for c in cutters:
            try:
                opened = opened.difference(c)
            except Exception:
                continue
    else:
        opened = card.difference(tool)
    return [p for p in opened.split(only_watertight=False) if abs(p.volume) >= SLIVER_MM3]


def round_trip(got, verbose=True):
    """Snip the whole card and match every recovered piece back to its part, by shape.

    Matching is global, not greedy. Giving each piece its own closest part is first come, first
    served: one piece that takes the wrong part leaves the rightful piece with nothing, and the
    report then says a part never came off the card. Matching is an assignment problem (n pieces,
    n parts, one pairing that minimises the total mismatch), and solving it as one is both correct
    and cheap.
    """
    pieces = snip(got["card"], got["gate_solids"], got.get("gate_axes"),
                  parts=got.get("parts"), owners=[g[0] for g in got.get("gates", [])])
    want = {n: (float(m.volume), m.bounds[1] - m.bounds[0]) for n, m in got["parts"].items()}
    frame_i = max(range(len(pieces)), key=lambda i: pieces[i].bounds[1][0] - pieces[i].bounds[0][0])
    loose = [p for i, p in enumerate(pieces) if i != frame_i]
    # Cutting debris is removed before matching. A global assignment uses every piece it is given,
    # so a small crumb takes a slot and pushes a real part onto the wrong name. Anything far
    # smaller than the smallest real part is debris.
    if want:
        crumb = min(v for v, _e in want.values()) * 0.25
        swarf = [p for p in loose if abs(p.volume) < crumb]
        loose = [p for p in loose if abs(p.volume) >= crumb]
        if swarf and verbose:
            print(f"  ignored {len(swarf)} crumb(s) of cutting debris under {crumb:.0f} mm3: "
                  f"{', '.join(f'{abs(p.volume):.1f}' for p in swarf)}")

    names = list(want)
    cost = np.zeros((len(loose), len(names)))
    for i, p in enumerate(loose):
        v, e = float(p.volume), p.bounds[1] - p.bounds[0]
        for j, n in enumerate(names):
            wv, we = want[n]
            cost[i, j] = abs(v - wv) / max(wv, 1e-6) + float(np.max(np.abs(e - we))) / 10.0

    from scipy.optimize import linear_sum_assignment
    rows, cols = linear_sum_assignment(cost)

    matched, wrong = {}, []
    taken = set()
    for i, j in zip(rows, cols):
        n = names[j]
        v, e = float(loose[i].volume), loose[i].bounds[1] - loose[i].bounds[0]
        wv, we = want[n]
        # a snipped part loses its gate stubs and takes a nipper's bite, so it comes back a little
        # smaller and a little shorter than the part as modelled
        if abs(v - wv) / max(wv, 1e-6) <= vol_tol_for(wv) and float(np.max(np.abs(e - we))) <= BBOX_TOL:
            matched[n] = (round(v, 1), [round(float(x), 1) for x in e])
            taken.add(n)
        else:
            wrong.append((n, round(v, 1), round(float(np.max(np.abs(e - we))), 2)))
    missing = [n for n in names if n not in taken]
    rep = {"recovered": len(loose), "matched": len(matched), "missing": missing,
           "wrong": wrong, "ok": not missing and not wrong}
    if verbose:
        print(f"  snipped {len(got['gate_solids'])} gates -> {len(loose)} parts came off")
        print(f"  matched {len(matched)}/{len(want)}"
              f"{', missing ' + ', '.join(missing) if missing else ''}"
              f"{', wrong ' + str(wrong) if wrong else ''}")
        print(f"  ROUND TRIP {'HOLDS' if rep['ok'] else 'DOES NOT HOLD'}")
    return rep


def best_card(verbose=True, **kw):
    """Build the card with each layout option and return the first that passes its own checks.

    Orienting parts so their posts print lying down makes the joints stronger and the card
    flatter, but on some geometry it has left parts attached to the frame after snipping. Rather
    than choose in advance, each combination is built and the checks decide. If the oriented card
    passes, it is used.

    Returns (build result, round trip report).
    """
    # Seating replaces orienting, so trying both values of `orient` under it would build the same
    # card twice and report a choice that was never made.
    seat = kw.pop("seat", True)
    combos = (((False, True), (False, False)) if seat else
              ((True, True), (False, True), (True, False), (False, False)))
    tried = []
    for orient, pack in combos:
        got = build(verbose=False, orient=orient, pack=pack, seat=seat, **kw)
        rep = round_trip(got, verbose=False)
        # The round trip alone is not an acceptance test. A card whose parts were never attached
        # to the frame passes it, because nothing was holding them. A card must be one piece
        # before snipping and come apart into all its parts after.
        # It also has to sit on the plate. A card can pass the round trip and be one body and
        # still fail to print if layer one puts down almost nothing.
        ok = rep["ok"] and got["bodies"] == 1 and got["first_layer_mm2"] >= 2000.0
        tried.append((orient, got, rep))
        if ok:
            if verbose:
                # Report what was used, not what was asked for. `pack` is the request, and the
                # dense layout is not always the one built.
                print(f"  seated on the plate: {seat}, oriented for printing: {orient}, "
                      f"tightly packed: {got['packed']}  "
                      f"({rep['matched']}/{len(got['parts'])} parts off the frame)")
                if len(tried) > 1 and tried[0][2]["ok"] is False:
                    print(f"  ! the first layout was built and REJECTED: "
                          f"{', '.join(tried[0][2]['missing']) or 'not one body'}")
            return got, rep
    got, rep = tried[-1][1], tried[-1][2]
    if verbose:
        print("  ! no layout gave one solid card that comes apart into all its parts")
    return got, rep


def export(out=OUT, name="card.stl", **kw):
    out = pathlib.Path(out)
    out.mkdir(exist_ok=True)
    got = build(**kw)
    f = out / name
    got["card"].export(f)
    return got, f



# ------------------------------------------------------------------------------ a real packer
# Shelves waste space. `sprue.shelf_nest` puts parts in rows, and each row is as tall as its
# tallest part, so small parts beside a tall one leave the rest of the row empty. On one card this
# left 84% of the area empty, which at volume is print time paid on every unit.
#
# Rows are still useful because a kit card is read as much as it is cut, and tidy rows look like a
# model kit. So MaxRects is an alternative, not a replacement.
def maxrects(sizes, width, height, allow_rot=True):
    """Best-short-side-fit MaxRects. Returns the placement, or None if the parts do not fit.

    Every free area is kept as an explicit rectangle. Placing a part splits the ones it overlaps
    and the contained ones are pruned. It is the standard answer to this problem and beats rows by
    a wide margin on a set of very unequal parts.
    """
    free = [(0.0, 0.0, width, height)]
    place, order = {}, sorted(sizes, key=lambda k: -max(sizes[k]))
    for k in order:
        w, h = sizes[k]
        best = None
        for (fx, fy, fw, fh) in free:
            for ww, hh, rot in ((w, h, False),) + (((h, w, True),) if allow_rot else ()):
                if ww > fw or hh > fh:
                    continue
                short = min(fw - ww, fh - hh)
                long_ = max(fw - ww, fh - hh)
                if best is None or (short, long_) < (best[0], best[1]):
                    best = (short, long_, fx, fy, ww, hh, rot)
        if best is None:
            return None
        _s, _l, x, y, ww, hh, rot = best
        place[k] = (x, y, rot)
        used = (x, y, ww, hh)
        nxt = []
        for r in free:
            nxt.extend(_split(r, used))
        free = _prune(nxt)
    return place


def _split(free, used):
    fx, fy, fw, fh = free
    ux, uy, uw, uh = used
    if ux >= fx + fw or ux + uw <= fx or uy >= fy + fh or uy + uh <= fy:
        return [free]
    out = []
    if uy > fy:
        out.append((fx, fy, fw, uy - fy))
    if uy + uh < fy + fh:
        out.append((fx, uy + uh, fw, fy + fh - (uy + uh)))
    if ux > fx:
        out.append((fx, fy, ux - fx, fh))
    if ux + uw < fx + fw:
        out.append((ux + uw, fy, fx + fw - (ux + uw), fh))
    return [r for r in out if r[2] > 1e-6 and r[3] > 1e-6]


def _prune(rects):
    out = []
    for i, a in enumerate(rects):
        if any(i != j and _inside(a, b) for j, b in enumerate(rects)):
            continue
        out.append(a)
    return out


def _inside(a, b):
    return (a[0] >= b[0] and a[1] >= b[1]
            and a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3])



# ------------------------------------------------------------------------- a branching runner
# A dense pack leaves parts at every height and no full-width band for a bar, so the runner has to
# reach in between the parts instead of crossing the card. That is the shape of an injection
# sprue: a tree, not a ladder.
#
# Every branch is checked against every part before it is accepted. A branch that clips a part
# fuses it to the frame, and snipping its gates does not free it.
RUNNER_W = 3.4           # the branch bar, wide enough to hold a part and to carry heat
RUNNER_CLEAR = 1.2       # how far a branch must stay off any part it is not serving
RUNNER_STOP = 3.0        # how far short of its part a branch stops, leaving room for the gate


def _near(a, b, n=1500):
    """Closest point between two meshes, and the distance."""
    pts = _surface_points(a, n)
    close, dist, _t = trimesh.proximity.closest_point(b, pts)
    i = int(np.argmin(dist))
    return np.asarray(pts[i], float), np.asarray(close[i], float), float(dist[i])


def _branch(p0, p1, z0, z1, grow=RUNNER_W):
    """One runner bar between two points, lying in the frame's own plane.

    Segments that meet at a corner only touch. Two boxes sharing an endpoint are tangent and union
    into two bodies, not one, so the elbow of an L-shaped route comes apart. Each segment is grown
    by a bar's width so consecutive ones overlap, and so the first one bites into the runner it
    leaves.
    """
    a = np.array([p0[0], p0[1], (z0 + z1) / 2])
    b = np.array([p1[0], p1[1], (z0 + z1) / 2])
    d = b - a
    L = float(np.linalg.norm(d))
    if L < 1e-6:
        return None
    bar = trimesh.creation.box(extents=[RUNNER_W, L + grow, z1 - z0])
    ang = np.arctan2(d[1], d[0]) - np.pi / 2
    bar.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
    bar.apply_translation((a + b) / 2)
    return bar


def runner_tree(placed, frame_mesh, verbose=False):
    """Branches grown outward from the frame until every part has one beside it.

    A tree built between parts does not connect to itself. Joining each part to its nearest
    neighbour at their closest 3D points places bars wherever the surfaces happen to be nearest,
    often well above the frame, so a bar drawn at frame level meets neither part. Growing outward
    from the frame means every new branch starts on the runner that already exists, so the whole
    runner is one piece by construction.

    Each branch stops short of the part it serves. The gate bridges that last gap, which is what
    makes the part snippable. A branch that runs into a part is a weld, not a gate.
    """
    runner = frame_mesh
    todo = set(placed)
    bars, missed = [], []
    while todo:
        best = None
        for n in todo:
            m = placed[n]
            c = np.asarray(m.bounds.mean(axis=0), float)
            probe = trimesh.creation.icosphere(subdivisions=1, radius=0.4)
            probe.apply_translation([c[0], c[1], FRAME_T / 2])
            pa, pb, d = _near(probe, runner)
            if best is None or d < best[0]:
                best = (d, n, np.asarray(pb, float), np.asarray(pa, float))
        d, n, on_runner, toward = best
        m = placed[n]
        v = toward[:2] - on_runner[:2]
        L = float(np.linalg.norm(v))
        if L < 1e-6:
            todo.discard(n)
            continue
        u = v / L
        stop = max(L - RUNNER_STOP, RUNNER_W)          # stop short, the gate covers the rest
        a0 = np.array([on_runner[0], on_runner[1], FRAME_T / 2])
        a1 = np.array([on_runner[0] + u[0] * stop, on_runner[1] + u[1] * stop, FRAME_T / 2])

        # Route around a clash rather than give up on the part. A straight branch is tried first.
        # When it would clip a third part, the two L-shaped routes to the same end are tried next.
        # Skipping instead would leave the part with nothing to gate to.
        routes = [[a0, a1]]
        corner_a = np.array([a1[0], a0[1], FRAME_T / 2])
        corner_b = np.array([a0[0], a1[1], FRAME_T / 2])
        routes.append([a0, corner_a, a1])
        routes.append([a0, corner_b, a1])

        chosen = None
        for route in routes:
            segs = [_branch(route[i], route[i + 1], 0.0, FRAME_T) for i in range(len(route) - 1)]
            segs = [s for s in segs if s is not None]
            if not segs:
                continue
            if all(not _clips(s, placed, n) for s in segs):
                chosen = segs
                break
        if chosen:
            bars.extend(chosen)
            runner = trimesh.util.concatenate([runner] + chosen)
        else:
            missed.append(n)
        todo.discard(n)
    if verbose:
        print(f"  runner: {len(bars)} branches for {len(placed)} parts, "
              f"unreached {missed or 'none'}")
    return bars, missed


def _clips(bar, placed, serving):
    """Does this branch run into a part it is not there to serve?"""
    for other, om in placed.items():
        if other == serving:
            continue
        lo = np.maximum(bar.bounds[0], om.bounds[0] - RUNNER_CLEAR)
        hi = np.minimum(bar.bounds[1], om.bounds[1] + RUNNER_CLEAR)
        if not np.all(hi > lo):
            continue
        try:
            if bar.intersection(om).volume > 0.2:
                return True
        except Exception:
            return True
    return False



# ----------------------------------------------------------------- routing the runner properly
# Getting a runner from the frame to every part through a dense packing is a path planning
# problem. A straight line can be blocked, an L can be blocked, and adding special cases does not
# end. An occupancy grid answers it directly: mark where the parts are, search the free space
# breadth first, and the path found is clear and connected to where it started.
#
# There is one grid, and each routed branch is painted into it as runner cells, so the next branch
# can start from it rather than from the frame. That makes the runner a tree instead of a fan, and
# the branches get shorter as routing proceeds.
GRID_MM = 1.5            # routing resolution, finer finds more paths and costs time


def _grid(placed, W, H, clear=None, cell=GRID_MM):
    """Where a branch may not go, and which part owns each blocked cell.

    The part is blocked, not its bounding box. A box around a round part also blocks its corners,
    so a branch routed to the edge of the box can stop up to 20 mm from the surface it serves, too
    far for a gate. The footprint is rasterised instead, so the free cells beside a part really
    are beside it.
    """
    clear = RUNNER_CLEAR if clear is None else clear
    nx, ny = int(np.ceil(W / cell)), int(np.ceil(H / cell))
    blocked = np.zeros((ny, nx), bool)
    owner = {}
    pad = clear + RUNNER_W / 2
    for n, m in placed.items():
        try:
            # Block what the part occupies at frame level, not its whole shadow. A branch is only
            # FRAME_T tall, so it can run under an overhang. A rounded part's shadow is widest
            # half way up, while at frame level it touches over a small patch, so routing to the
            # shadow's edge stops a branch 8 to 16 mm from any material a gate can reach. A section
            # at the gate's own height asks the question the gate asks.
            sec = m.section(plane_origin=[0, 0, min(FRAME_T, m.bounds[1][2] * 0.9)],
                            plane_normal=[0, 0, 1])
            flat, _T2 = sec.to_2D()
            g = max(flat.polygons_full, key=lambda q: q.area).buffer(pad)
            if g is None or g.is_empty:
                raise ValueError
            if g.geom_type == "MultiPolygon":
                g = max(g.geoms, key=lambda q: q.area)
        except Exception:
            b = m.bounds
            g = shapely_box(b[0][0] - pad, b[0][1] - pad, b[1][0] + pad, b[1][1] + pad)
        mine = np.zeros((ny, nx), bool)
        bx0, by0, bx1, by1 = g.bounds
        for r in range(max(int(by0 / cell), 0), min(int(np.ceil(by1 / cell)), ny)):
            for c in range(max(int(bx0 / cell), 0), min(int(np.ceil(bx1 / cell)), nx)):
                if g.contains(Point((c + 0.5) * cell, (r + 0.5) * cell)):
                    mine[r, c] = True
        owner[n] = mine
        blocked |= mine
    return blocked, cell, owner


def _route(blocked, sources, targets):
    """Breadth-first from every runner cell at once to the nearest target. Returns the path."""
    ny, nx = blocked.shape
    prev = -np.ones((ny, nx, 2), int)
    seen = np.zeros((ny, nx), bool)
    from collections import deque
    q = deque()
    for (r, c) in sources:
        if 0 <= r < ny and 0 <= c < nx and not seen[r, c]:
            seen[r, c] = True
            q.append((r, c))
    tset = {(r, c) for (r, c) in targets if 0 <= r < ny and 0 <= c < nx}
    while q:
        r, c = q.popleft()
        if (r, c) in tset:
            path, cur = [], (r, c)
            while cur[0] >= 0:
                path.append(cur)
                p = prev[cur[0], cur[1]]
                if p[0] < 0:
                    break
                cur = (p[0], p[1])
            return path[::-1]
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            r2, c2 = r + dr, c + dc
            if 0 <= r2 < ny and 0 <= c2 < nx and not seen[r2, c2] and not blocked[r2, c2]:
                seen[r2, c2] = True
                prev[r2, c2] = (r, c)
                q.append((r2, c2))
    return None


def _simplify(path):
    """Collapse a grid path to its corners, so a run of cells becomes one bar."""
    if not path or len(path) < 2:
        return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            out.append(b)
    out.append(path[-1])
    return out


def routed_runner(placed, frame_mesh, W, H, verbose=False):
    """Branches routed through the free space, reaching every part. Returns bars and any misses."""
    blocked, cell, owner = _grid(placed, W, H)
    ny, nx = blocked.shape

    runner_cells = set()
    fb = frame_mesh.bounds
    for r in range(ny):
        for c in range(nx):
            x, y = (c + 0.5) * cell, (r + 0.5) * cell
            if (x < FRAME_W or x > W - FRAME_W or y < FRAME_W or y > H - FRAME_W):
                runner_cells.add((r, c))

    bars, missed = [], []
    # Smallest parts first. Routing large parts first means routing them while the runner is still
    # only the frame, so their branches cross the whole card and stop wherever they first find
    # space. Small parts thread into the tight gaps early, and the runner they leave is then near
    # the large parts, whose long perimeters are easy to reach.
    order = sorted(placed, key=lambda n: float(np.prod(
        placed[n].bounds[1][:2] - placed[n].bounds[0][:2])))
    for n in order:
        # a branch should end in a free cell touching this part's own clearance ring, which is
        # 2.9 mm from its surface and well within what a gate can bridge
        mine = owner[n]
        ring = np.zeros_like(mine)
        ring[1:, :] |= mine[:-1, :]
        ring[:-1, :] |= mine[1:, :]
        ring[:, 1:] |= mine[:, :-1]
        ring[:, :-1] |= mine[:, 1:]
        targets = [(int(r), int(c)) for r, c in zip(*np.nonzero(ring & ~blocked))]
        if not targets:
            missed.append(n)
            continue
        path = _route(blocked, runner_cells, targets)
        if not path:
            missed.append(n)
            continue
        pts = _simplify(path)
        for i in range(len(pts) - 1):
            a = np.array([(pts[i][1] + 0.5) * cell, (pts[i][0] + 0.5) * cell, FRAME_T / 2])
            z = np.array([(pts[i + 1][1] + 0.5) * cell, (pts[i + 1][0] + 0.5) * cell, FRAME_T / 2])
            bar = _branch(a, z, 0.0, FRAME_T)
            if bar is not None:
                bars.append(bar)
        for (r, c) in path:
            runner_cells.add((r, c))
    if verbose:
        print(f"  routed runner: {len(bars)} bars, unreached {missed or 'none'}")
    return bars, missed


def why_stuck(got, names=None, verbose=True):
    """For each part that will not come off the card, say what is holding it.

    A round trip count such as "14 of 19" is a symptom, not a diagnosis. Four things can hold a
    part to a card, and they need different fixes:
      - it touches the frame directly, so no gate needs cutting for it to stay
      - it touches another part, and the two come off as one lump
      - one of its own gates was not fully severed by the nipper
      - a gate belonging to a different part lands on it
    """
    # The exact version of this check is too slow to be useful. Sampling many points and querying
    # `closest_point` against every other part costs O(points x faces), and on parts with tens of
    # thousands of faces it can run for many minutes. So this uses few points, one reusable query
    # per part, and bounding boxes to reject pairs that cannot touch before doing any real work.
    card, parts, frame = got["card"], got["parts"], got["frame"]
    names = names or sorted(parts)
    TOUCH = 0.05
    q_frame = trimesh.proximity.ProximityQuery(frame)
    queries = {}
    out = {}
    for n in names:
        m = parts[n]
        why = []
        pts = _surface_points(m, 220)
        d = float(np.min(np.abs(q_frame.signed_distance(pts))))
        if d < TOUCH:
            why.append(f"touches the frame directly ({d:.3f} mm)")
        for other, om in parts.items():
            if other == n:
                continue
            lo = np.maximum(m.bounds[0], om.bounds[0])
            hi = np.minimum(m.bounds[1], om.bounds[1])
            if not np.all(hi > lo):
                continue
            if other not in queries:
                queries[other] = trimesh.proximity.ProximityQuery(om)
            dd = float(np.min(np.abs(queries[other].signed_distance(pts))))
            if dd < TOUCH:
                why.append(f"touches {other} ({dd:.3f} mm)")
        mine = [i for i, g in enumerate(got["gates"]) if g[0] == n]
        why.append(f"{len(mine)} own gate(s)")
        # a foreign gate landing on a part is a bounding-box question first, and only the survivors
        # are worth a real test: one point per gate centre against this part's own surface
        foreign = []
        for i, g in enumerate(got["gate_solids"]):
            if got["gates"][i][0] == n:
                continue
            lo = np.maximum(m.bounds[0], g.bounds[0])
            hi = np.minimum(m.bounds[1], g.bounds[1])
            if not np.all(hi > lo):
                continue
            inside = m.contains(np.atleast_2d(g.bounds.mean(axis=0)))
            if bool(inside[0]):
                foreign.append(got["gates"][i][0])
        if foreign:
            why.append(f"gates belonging to {', '.join(sorted(set(foreign)))} land on it")
        out[n] = why
        if verbose:
            print(f"  {n:20s} {'; '.join(why)}")
    return out


