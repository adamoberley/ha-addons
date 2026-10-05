"""Shared test settings: keep real-world waits out of the tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod


@pytest.fixture(autouse=True)
def quick_state_fetch(monkeypatch):
    monkeypatch.setattr(main_mod, "STATE_FETCH_S", 0.05)
