"""LLM tool handlers — moved back to main.py for AstrBot handler binding compatibility.

AstrBot uses ft.handler.__module__ == metadata.module_path to bind self (the Star instance)
via functools.partial. Methods defined in sub-modules (handlers/) have a different __module__
and won't be bound, causing "missing 1 required positional argument: event" errors.
"""
from __future__ import annotations


class LLMToolsMixin:
    """Empty mixin — LLM tool methods live in main.py for correct __module__ binding."""
