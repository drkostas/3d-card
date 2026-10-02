"""Builds docs/example.png: a small made-up kit (a block, a rod on a peg, two wheels) as one card."""
from pathlib import Path

import numpy as np
import trimesh

from base3d import frame_on, render, save_png, tile
from base3d.show import SHEET_BG
from card3d import joints as J
from card3d import tosprue as T


def kit():
    block = trimesh.creation.box(extents=(24, 16, 12))
    block.apply_translation((0, 0, 6))
    at = (12.0, 0.0, 6.0)
    block = block.difference(J.female("peg", 3.0, (1, 0, 0), at))
    rod = trimesh.creation.cylinder(radius=3, height=28, sections=48)
    rod.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    rod.apply_translation((12 + J._default_length("peg", 3.0) + 14, 0, 6))
    rod = rod.union(J.male("peg", 3.0, (1, 0, 0), at))
    parts = {"block": block, "rod": rod}
    for i in range(2):
        w = trimesh.creation.cylinder(radius=7, height=4, sections=64)
        w.apply_translation((60, 20 * i, 2))
        parts[f"wheel_{i}"] = w
    made = [{"type": "peg", "size": 3.0, "axis": (1, 0, 0), "at": at, "child": "rod", "parent": "block"}]
    return parts, made, []


got, rep = T.best_card(verbose=True, source=kit, rows=[["block", "rod"], ["wheel_0", "wheel_1"]])
card = got["card"]
colors = np.tile((0.78, 0.80, 0.84), (len(card.faces), 1))
imgs = []
for azim, elev in [(-90, 55), (-55, 30)]:
    eye, target = frame_on(card, azim, elev, pad=1.0)
    imgs.append(render(card, eye, target, size=(640, 440), face_colors=colors, bg=SHEET_BG))
out = Path(__file__).resolve().parent.parent / "docs" / "example.png"
save_png(tile(imgs, cols=2, bg=tuple(int(255 * c) for c in SHEET_BG)), out)
print(out, "round trip", rep["ok"], f"{rep['matched']}/{len(got['parts'])}")
