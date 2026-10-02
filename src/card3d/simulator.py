"""Printability and stability checks for printed, assembled parts.

The CAD model is not the object that comes off the printer. This module models four stages between
the two.

  1 Print      the part lies on the plate in some orientation. Faces steeper than the overhang
               limit need support, and a peg standing in Z is a stack of discs held together only
               by layer adhesion.
  2 Strip      supports come off and leave a scar. A surface printed over support comes out rough
               and proud of nominal, so a socket is effectively tighter than drawn. Modelled as an
               allowance on every down-facing surface.
  3 Insert     a joint is not proven by its final pose. The child part has to travel there. Sweeping
               it along its axis from clear to seated catches a collision on the way in, which a
               final-pose check misses.
  4 Stand      rigid-body physics (MuJoCo) on the assembled object. Gravity, friction and contact.
               Does it stay upright, and does it stay upright when nudged.

Stage 3 cannot be done with a single boolean. Two solids that do not overlap in their final
positions say nothing about whether a path exists between the start and the end. That is a
swept-volume question and needs a sweep.

Two inputs are not known from first principles: the friction coefficient of PLA on PLA at the
layer height used, and the real printed clearance. Both should be measured with test prints, and
results should be read with that uncertainty in mind.

`best_orientation` searches print orientations and scores bed contact first, then support, then
peg strength.
"""
import math
import pathlib

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).parent

OVERHANG_DEG = 45.0          # steeper than this off the plate needs support
SCAR = 0.15                  # mm a support-scarred surface comes out proud of nominal
BED_MIN_MM2 = 120.0          # below this a part is likely to come loose mid print
LAYER = 0.20


def overhang_report(mesh, name=""):
    """Which faces need support in this orientation, and how much of the part rests on the plate."""
    n = mesh.face_normals
    a = mesh.area_faces
    limit = -math.sin(math.radians(90 - OVERHANG_DEG))   # z component at the overhang limit
    zmin = mesh.bounds[0][2]

    down = n[:, 2] < limit
    # a face is only a support problem if it is not already lying on the plate
    centres = mesh.triangles_center
    on_bed = down & (centres[:, 2] < zmin + LAYER * 1.5)
    needs = down & ~on_bed

    bed_area = float(a[on_bed].sum())
    sup_area = float(a[needs].sum())
    # an estimate: support volume is the overhang area times its height off the plate
    sup_vol = float((a[needs] * (centres[needs, 2] - zmin)).sum()) if needs.any() else 0.0
    return {
        "name": name,
        "bed_area": bed_area,
        "support_area": sup_area,
        "support_frac": sup_area / float(a.sum()),
        "support_volume": sup_vol,
        "scarred_faces": needs,
    }


def strip_supports(mesh, scarred, scar=SCAR):
    """The part as it comes off the plate: scarred faces sit proud by `scar`.

    A socket whose bore was printed over support is rough and effectively tighter than drawn, so a
    peg that fits the CAD model can jam in the printed part. Pushing the scarred faces outward along
    their normals is a cheap model of that, and it shows whether a clearance survives printing.
    """
    m = mesh.copy()
    if not scarred.any():
        return m
    v = m.vertices.copy()
    moved = np.zeros(len(v), dtype=bool)
    for fi in np.nonzero(scarred)[0]:
        for vi in m.faces[fi]:
            if not moved[vi]:
                v[vi] += m.face_normals[fi] * scar
                moved[vi] = True
    m.vertices = v
    return m


def insertion_sweep(child, parent, axis, travel, steps=24):
    """Slide the child in along `axis` from `travel` mm clear to seated. Report the worst overlap.

    Returns (clear, worst_volume, worst_step). `clear` is True when nothing collides on the way in.
    """
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    worst, worst_at = 0.0, 0.0
    for i in range(steps, -1, -1):
        d = travel * (i / steps)
        c = child.copy()
        c.apply_translation(axis * d)
        lo = np.maximum(c.bounds[0], parent.bounds[0])
        hi = np.minimum(c.bounds[1], parent.bounds[1])
        if not np.all(hi > lo):
            continue
        v = float(c.intersection(parent).volume)
        if v > worst:
            worst, worst_at = v, d
    return worst <= 0.05, worst, worst_at


def peg_axis_vs_plate(peg_axis, print_rotation):
    """How far a peg's axis lies out of the print plane. 0 deg is ideal, 90 deg is a stack of discs.

    PLA is weak between layers. A peg standing in Z shears along the layer lines at a fraction of
    the bulk strength, so this angle affects strength directly.
    """
    a = np.asarray(peg_axis, dtype=float)
    a = a / np.linalg.norm(a)
    if print_rotation is not None:
        a = print_rotation[:3, :3] @ a
    return abs(math.degrees(math.asin(np.clip(abs(a[2]), 0, 1))))


# ---- stage 4: rigid-body physics --------------------------------------------------------------
PLA_DENSITY = 1240.0          # kg/m3
MM = 0.001                    # the model is in millimetres, MuJoCo is in metres


def convex_pieces(mesh, name, out_dir, threshold=0.05):
    """Break a part into convex hulls (with CoACD), because contact solvers only handle convex shapes.

    A single convex hull of the whole object would stand on almost anything. Gaps between supports,
    hollows underneath and overhangs are the features that decide whether it tips, and one hull
    removes all of them. Hence the decomposition.
    """
    import coacd
    out_dir.mkdir(exist_ok=True)
    cm = coacd.Mesh(mesh.vertices, mesh.faces)
    parts = coacd.run_coacd(cm, threshold=threshold)
    files = []
    for i, (v, f) in enumerate(parts):
        piece = trimesh.Trimesh(vertices=np.asarray(v) * MM, faces=np.asarray(f), process=True)
        if piece.volume <= 0:
            piece.invert()
        p = out_dir / f"{name}_{i:02d}.stl"
        piece.export(p)
        files.append(p)
    return files


def mjcf_for(pieces, out_dir, friction=0.6, tilt_deg=0.0):
    """MuJoCo XML for one free body made of every convex piece, dropped onto a plane."""
    assets = "\n".join(f'    <mesh name="m{i}" file="{p.name}"/>' for i, p in enumerate(pieces))
    geoms = "\n".join(
        f'      <geom type="mesh" mesh="m{i}" density="{PLA_DENSITY}" '
        f'friction="{friction} 0.01 0.001"/>' for i in range(len(pieces)))
    return f"""<mujoco model="kit">
  <compiler angle="degree" meshdir="."/>
  <option timestep="0.0005" integrator="implicitfast" cone="elliptic"/>
  <asset>
{assets}
    <material name="grid" rgba="0.8 0.8 0.85 1"/>
  </asset>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.01" material="grid"
          friction="{friction} 0.01 0.001" euler="0 {tilt_deg} 0"/>
    <body name="figure" pos="0 0 0.002">
      <freejoint/>
{geoms}
    </body>
  </worldbody>
</mujoco>"""


def stand_test(pieces, out_dir, seconds=2.5, friction=0.6, tilt_deg=0.0, nudge=None):
    """Drop the assembled object on a plane and report whether it is still standing.

    `nudge` is an optional velocity kick applied part way through. Standing means the object's up
    axis ends within 25 degrees of vertical.
    """
    import mujoco
    xml = mjcf_for(pieces, out_dir, friction=friction, tilt_deg=tilt_deg)
    (out_dir / "kit.xml").write_text(xml)
    model = mujoco.MjModel.from_xml_path(str(out_dir / "kit.xml"))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    start = data.qpos[:3].copy()

    n = int(seconds / model.opt.timestep)
    nudge_at = int(n * 0.45)
    for i in range(n):
        if nudge is not None and i == nudge_at:
            data.qvel[:3] += np.asarray(nudge, dtype=float)
        mujoco.mj_step(model, data)

    q = data.qpos[3:7]
    # angle between the body's own up axis and world up
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, q)
    up = R.reshape(3, 3)[:, 2]
    tilt = math.degrees(math.acos(float(np.clip(up[2], -1, 1))))
    drift = float(np.linalg.norm(data.qpos[:2] - start[:2])) / MM
    return {"tilt_deg": tilt, "drift_mm": drift, "z_mm": float(data.qpos[2]) / MM,
            "standing": tilt < 25.0}


def candidate_orientations(n=14):
    """A spread of print orientations to try: the six faces, plus tilted ones in between."""
    import itertools
    axes = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    out = [None]
    for ax in axes:
        for deg in (90, 180, 270):
            out.append(trimesh.transformations.rotation_matrix(math.radians(deg), ax))
    for ax, deg in itertools.product(axes, (45, 135)):
        out.append(trimesh.transformations.rotation_matrix(math.radians(deg), ax))
    return out[:n] if n else out


def best_orientation(mesh, peg_axes=(), bed_min=BED_MIN_MM2):
    """Search orientations and pick the one most likely to print.

    The score is not least support. A part with almost no overhang can still fail if it balances on
    a peg tip with 11 mm2 touching the plate. Bed contact is scored first, because a part that comes
    loose part way through the print fails however little support it needed. Support area comes
    second and keeping pegs in the strong plane third.

    Returns (score, rotation, overhang_report, worst_peg_angle, placed_mesh).
    """
    best = None
    for r in candidate_orientations():
        m = mesh.copy()
        if r is not None:
            m.apply_transform(r)
        m.apply_translation([0, 0, -m.bounds[0][2]])
        rep = overhang_report(m)
        pegs = max((peg_axis_vs_plate(a, r) for a in peg_axes), default=0.0)
        # bed adhesion dominates, then support, then keeping pegs in the strong plane
        score = (min(rep["bed_area"], 600.0) / 600.0) * 2.0 \
            - rep["support_frac"] * 1.5 \
            - (pegs / 90.0) * 0.6
        if best is None or score > best[0]:
            best = (score, r, rep, pegs, m)
    return best
