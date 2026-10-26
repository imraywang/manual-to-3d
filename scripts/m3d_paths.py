"""Paths shared by the scripts.

SKILL     = this repository (scripts/, references/, assets/)
WORKSPACE = where generated guides live: guide.html, index.html, scenes/, manuals/, thumbs/, cases.json.
            Defaults to ~/manual-to-3d; override with the MANUAL_TO_3D_HOME environment variable.
"""
import os
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SITE = Path(os.environ.get("MANUAL_TO_3D_HOME") or "~/manual-to-3d").expanduser().resolve()
SCHEMA = SKILL / "references" / "scene-schema.md"
EXAMPLE = SKILL / "references" / "example-scene.json"
EXAMPLE_EN = SKILL / "references" / "example-scene.en.json"
