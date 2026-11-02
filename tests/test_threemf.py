import zipfile

import numpy as np
import pytest
import trimesh

from card3d import threemf


def _plate_and_inlay():
    plate = trimesh.creation.box(extents=(20, 20, 2))
    plate.apply_translation((0, 0, 1))
    cutter = trimesh.creation.box(extents=(10, 10, 1.0))
    cutter.apply_translation((0, 0, 1.9))
    inlay = trimesh.creation.box(extents=(10, 10, 0.6))
    inlay.apply_translation((0, 0, 1.7))
    return plate.difference(cutter), inlay


def test_each_part_keeps_its_filament_and_the_plate_its_map(tmp_path):
    body, inlay = _plate_and_inlay()
    p = threemf.write(tmp_path / "two.3mf", [(body, 1, "white body"), (inlay, 2, "black inlay")], nozzles=[1, 2])
    got = threemf.filaments(p)
    assert got == {"parts": {"white body": 1, "black inlay": 2}, "nozzles": [1, 2]}
    names = zipfile.ZipFile(p).namelist()
    assert "Metadata/project_settings.config" not in names
    assert "Metadata/plate_1.png" in names


def _objects(path):
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    root = ET.fromstring(zipfile.ZipFile(path).read("3D/3dmodel.model"))
    item = root.find("m:build/m:item", ns)
    shift = np.array([float(x) for x in item.get("transform").split()[9:12]])
    out = []
    for ob in root.findall("m:resources/m:object", ns):
        mesh = ob.find("m:mesh", ns)
        if mesh is None:
            continue
        v = np.array([[float(e.get(k)) for k in "xyz"] for e in mesh.find("m:vertices", ns)])
        f = np.array([[int(e.get(k)) for k in ("v1", "v2", "v3")] for e in mesh.find("m:triangles", ns)])
        out.append(trimesh.Trimesh(v + shift, f, process=False))
    return out


def test_the_bodies_keep_their_places_and_sizes(tmp_path):
    body, inlay = _plate_and_inlay()
    p = threemf.write(tmp_path / "two.3mf", [(body, 1, "a"), (inlay, 2, "b")], at=(100.0, 50.0))
    got = _objects(p)
    assert sorted(round(float(g.volume), 3) for g in got) == sorted(
        [round(float(body.volume), 3), round(float(inlay.volume), 3)])
    allv = np.vstack([g.vertices for g in got])
    assert np.allclose(allv.min(axis=0), [90.0, 40.0, 0.0], atol=1e-4)
    # the inlay still sits flush in the top of the plate
    top = max(float(g.vertices[:, 2].max()) for g in got)
    assert all(abs(float(g.vertices[:, 2].max()) - top) < 1e-6 for g in got)


def test_a_wrong_nozzle_list_is_refused(tmp_path):
    body, inlay = _plate_and_inlay()
    with pytest.raises(ValueError):
        threemf.write(tmp_path / "x.3mf", [(body, 1, "a"), (inlay, 2, "b")], nozzles=[1, 3])
    with pytest.raises(ValueError):
        threemf.write(tmp_path / "x.3mf", [(body, 1, "a"), (inlay, 2, "b")], nozzles=[1])
