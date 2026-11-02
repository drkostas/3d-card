"""Write a 3MF in which each part of one object prints with its own filament.

This is how a kit card prints in two colours on a printer with two nozzles or a filament changer: a
white card, and black details inlaid flush in it as separate bodies.

    from card3d import threemf
    threemf.write("card.3mf", [(white, 1, "card"), (black, 2, "details")], nozzles=[1, 2])

- Each part's filament is its 1-based FILAMENT slot, the position in the slicer's list of filament
  presets. It is not the nozzle.
- `nozzles` gives the nozzle for each filament slot (1 left, 2 right on a two-nozzle printer), written
  as the plate's manual filament map. Slicers read it from the file when nothing on their command
  line overrides it, so check what you got in the G-code (`slicecheck.nozzles_used`).
- The file carries no `Application` metadata and no `project_settings.config`. A file that names
  Bambu Studio or OrcaSlicer as its author is read as that slicer's own project, which needs a full
  settings file whose per-filament lists match the filament count; without one some versions crash.
- The parts keep their positions relative to each other. The object is dropped to z = 0 with its
  XY centre at `at`.
- `thumbnail` adds a plain plate thumbnail, so a tool that would otherwise draw one from the model
  (slow for a large model) does not need to.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def _mesh_xml(mesh) -> str:
    v = "\n".join(f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in mesh.vertices)
    t = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
    return f"   <mesh>\n    <vertices>\n{v}\n    </vertices>\n    <triangles>\n{t}\n    </triangles>\n   </mesh>\n"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _png(size, colour=(235, 235, 230)) -> bytes:
    """A plain PNG of one colour, written with the standard library."""
    import struct
    import zlib
    w, h = size
    row = b"\x00" + bytes(colour) * w
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h, 9)) + chunk(b"IEND", b""))


def write(path, parts, nozzles=None, name="object", at=(128.0, 128.0), thumbnail=True):
    """Write `parts`, a list of (mesh, filament slot from 1, part name), as one object in a 3MF.

    `nozzles` is the nozzle (1 or 2) for each filament slot 1..N, or None to leave the choice to the
    slicer. Returns `path`.
    """
    if not parts:
        raise ValueError("no parts to write")
    slots = sorted({int(p[1]) for p in parts})
    if slots[0] < 1:
        raise ValueError("filament slots start at 1")
    if nozzles is not None:
        if any(int(n) not in (1, 2) for n in nozzles):
            raise ValueError("a nozzle is 1 (left) or 2 (right)")
        if len(nozzles) < slots[-1]:
            raise ValueError(f"{len(nozzles)} nozzle(s) given for filament slots up to {slots[-1]}")
    lo = np.min([np.asarray(p[0].bounds[0], float) for p in parts], axis=0)
    hi = np.max([np.asarray(p[0].bounds[1], float) for p in parts], axis=0)
    shift = np.array([-(lo[0] + hi[0]) / 2.0, -(lo[1] + hi[1]) / 2.0, -lo[2]])
    wrapper = len(parts) + 1
    objs = []
    for i, (mesh, _slot, _pname) in enumerate(parts, start=1):
        m = mesh.copy()
        m.apply_translation(shift)
        objs.append(f'  <object id="{i}" type="model">\n{_mesh_xml(m)}  </object>\n')
    comps = "".join(f'    <component objectid="{i}"/>\n' for i in range(1, len(parts) + 1))
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
             ' <resources>\n' + "".join(objs) +
             f'  <object id="{wrapper}" type="model">\n   <components>\n{comps}   </components>\n  </object>\n'
             ' </resources>\n <build>\n'
             f'  <item objectid="{wrapper}" transform="1 0 0 0 1 0 0 0 1 {at[0]:.4f} {at[1]:.4f} 0"/>\n'
             ' </build>\n</model>\n')
    part_xml = "".join(
        f'    <part id="{i}" subtype="normal_part">\n'
        f'      <metadata key="name" value="{_esc(pname)}"/>\n'
        f'      <metadata key="extruder" value="{int(slot)}"/>\n'
        f'    </part>\n' for i, (_m, slot, pname) in enumerate(parts, start=1))
    plate_map = ""
    if nozzles is not None:
        plate_map = ('    <metadata key="filament_map_mode" value="Manual"/>\n'
                     f'    <metadata key="filament_maps" value="{" ".join(str(int(n)) for n in nozzles)}"/>\n')
    settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
                f'  <object id="{wrapper}">\n'
                f'    <metadata key="name" value="{_esc(name)}"/>\n'
                f'    <metadata key="extruder" value="{int(parts[0][1])}"/>\n'
                f'{part_xml}  </object>\n'
                '  <plate>\n    <metadata key="plater_id" value="1"/>\n'
                f'{plate_map}'
                f'    <model_instance>\n      <metadata key="object_id" value="{wrapper}"/>\n'
                '      <metadata key="instance_id" value="0"/>\n    </model_instance>\n'
                '  </plate>\n</config>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", settings)
        if thumbnail:
            z.writestr("Metadata/plate_1.png", _png((512, 512)))
            z.writestr("Metadata/plate_1_small.png", _png((128, 128)))
    return path


def filaments(path) -> dict:
    """{part name: filament slot} and the plate's filament map, read back from a 3MF `write` made."""
    import re
    with zipfile.ZipFile(path) as z:
        s = z.read("Metadata/model_settings.config").decode()
    out = {}
    for part in re.findall(r"<part .*?</part>", s, re.S):
        nm = re.search(r'key="name" value="([^"]*)"', part)
        ex = re.search(r'key="extruder" value="(\d+)"', part)
        if nm and ex:
            out[nm.group(1)] = int(ex.group(1))
    m = re.search(r'key="filament_maps" value="([^"]*)"', s)
    return {"parts": out, "nozzles": [int(x) for x in m.group(1).split()] if m else None}
