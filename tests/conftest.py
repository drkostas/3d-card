import numpy as np
import pytest
import trimesh

from card3d import joints as J


def peg_kit():
    """A small made-up kit: a block with a socket, a rod with a peg that fits it, and a wheel."""
    block = trimesh.creation.box(extents=(20, 14, 10))
    block.apply_translation((0, 0, 5))
    at = (10.0, 0.0, 5.0)
    block = block.difference(J.female("peg", 3.0, (1, 0, 0), at))
    rod = trimesh.creation.cylinder(radius=3, height=24, sections=48)
    rod.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    rod.apply_translation((10 + J._default_length("peg", 3.0) + 12, 0, 5))
    rod = rod.union(J.male("peg", 3.0, (1, 0, 0), at))
    wheel = trimesh.creation.cylinder(radius=6, height=4, sections=64)
    wheel.apply_translation((40, 20, 2))
    parts = {"block": block, "rod": rod, "wheel": wheel}
    made = [{"type": "peg", "size": 3.0, "axis": (1, 0, 0), "at": at, "child": "rod", "parent": "block"}]
    return parts, made, []


@pytest.fixture
def kit():
    parts, made, notes = peg_kit()
    return lambda: ({n: m.copy() for n, m in parts.items()}, list(made), list(notes))
