"""Handler methods moved back to main.py for AstrBot star_map compatibility.

AstrBot uses star_map[handler.handler_module_path] to find the Star instance.
Methods defined in sub-modules have a different module path and are skipped.
"""
from __future__ import annotations


class DrawCommandsMixin:
    """Empty mixin — all handler methods live in main.py."""
