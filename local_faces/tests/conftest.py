"""Test setup for Local Faces: import the app modules and keep /data in tmp."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import facedb as facedb_mod
import reclog as reclog_mod
import statics as statics_mod


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A face database in a temp file (never the real /data/faces.json)."""
    monkeypatch.setattr(facedb_mod, "DB_PATH", str(tmp_path / "faces.json"))
    return facedb_mod.FaceDB(threshold=0.5, model_id="sface")


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(reclog_mod, "LOG_PATH", str(tmp_path / "recognition-log.json"))
    return reclog_mod.RecognitionLog()


@pytest.fixture
def dismissals(tmp_path, monkeypatch):
    """Keeps StaticWatcher's dismissal file out of /data too."""
    path = tmp_path / "static-dismissed.json"
    monkeypatch.setattr(statics_mod, "DISMISSED_PATH", str(path))
    return path
