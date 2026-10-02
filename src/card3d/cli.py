"""3d-card command line."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="3d-card", description="Printable kit cards from 3D parts.")
    p.add_argument("--version", action="version", version=f"3d-card {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("skill", help="install the Claude Code skill for making kit cards")
    k.add_argument("--dir", default="~/.claude/skills")
    a = p.parse_args(argv)
    dest = Path(a.dir).expanduser() / "3d-card"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "skill" / "SKILL.md", dest / "SKILL.md")
    print(f"installed {dest / 'SKILL.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
