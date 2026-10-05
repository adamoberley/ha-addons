"""Shared test settings: keep the restore check's real-world wait out of tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod


@pytest.fixture(autouse=True)
def quick_restore_check(monkeypatch):
    monkeypatch.setattr(main_mod, "RESTORE_CHECK_S", 0.01)
