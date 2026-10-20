"""Locate this checkout independently of each suite's nesting depth."""

from pathlib import Path

EXTENSION = Path(__file__).resolve().parents[1]
ROOT = EXTENSION.parents[1]
