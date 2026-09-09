"""Repo hygiene: every app's manifest, README row and changelog agree.

Run from the repo root: ``python -m pytest``

These exist because the README's version table silently drifted three releases
behind (LedFX read 1.1.2 while the app shipped 1.7.1), which is exactly the kind
of thing nobody notices by reading and nobody has to notice twice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APPS = sorted(p.name for p in ROOT.iterdir() if (p / "config.yaml").is_file())


def manifest(app: str) -> dict:
    return yaml.safe_load((ROOT / app / "config.yaml").read_text())


def test_every_app_directory_is_discovered():
    assert APPS == ["frame_gallery", "hue_ent", "ledfx", "local_faces"]


@pytest.mark.parametrize("app", APPS)
def test_manifest_has_the_fields_the_supervisor_needs(app):
    cfg = manifest(app)
    for key in ("name", "version", "slug", "description", "arch"):
        assert cfg.get(key), f"{app}/config.yaml is missing {key}"
    assert cfg["slug"] == app, f"{app}/config.yaml slug should match the directory"
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(cfg["version"])), cfg["version"]


@pytest.mark.parametrize("app", APPS)
def test_options_all_have_a_schema_entry(app):
    """An option with no schema key is silently dropped by the Supervisor."""
    cfg = manifest(app)
    options, schema = cfg.get("options") or {}, cfg.get("schema") or {}
    assert set(options) <= set(schema), (
        f"{app}: options without a schema entry: {sorted(set(options) - set(schema))}"
    )


@pytest.mark.parametrize("app", APPS)
def test_readme_table_lists_the_shipped_version(app):
    cfg = manifest(app)
    readme = (ROOT / "README.md").read_text()
    row = next((line for line in readme.splitlines()
                if line.startswith("| **[") and f"{app}/DOCS.md" in line), None)
    assert row, f"{app} has no row in the README version table"
    assert f"`{cfg['version']}`" in row, (
        f"README row for {app} doesn't show {cfg['version']}: {row.strip()}"
    )


@pytest.mark.parametrize("app", APPS)
def test_app_changelog_documents_the_shipped_version(app):
    """Home Assistant shows this file in the store; a release needs an entry."""
    path = ROOT / app / "CHANGELOG.md"
    assert path.is_file(), f"{app} has no CHANGELOG.md"
    version = str(manifest(app)["version"])
    headings = re.findall(r"^## ([0-9]+\.[0-9]+\.[0-9]+)", path.read_text(), re.M)
    assert headings, f"{app}/CHANGELOG.md has no version headings"
    assert headings[0] == version, (
        f"{app}/CHANGELOG.md starts at {headings[0]}, but the app ships {version}"
    )


@pytest.mark.parametrize("app", APPS)
def test_root_changelog_mentions_the_shipped_version(app):
    cfg, root = manifest(app), (ROOT / "CHANGELOG.md").read_text()
    assert f"## {cfg['name']} {cfg['version']}" in root, (
        f"root CHANGELOG.md has no '## {cfg['name']} {cfg['version']}' entry"
    )


@pytest.mark.parametrize("app", APPS)
def test_docs_and_translations_exist(app):
    assert (ROOT / app / "DOCS.md").is_file(), f"{app} has no DOCS.md"
    translations = ROOT / app / "translations" / "en.yaml"
    assert translations.is_file(), f"{app} has no translations/en.yaml"
    yaml.safe_load(translations.read_text())   # must parse


@pytest.mark.parametrize("app", APPS)
def test_every_option_has_a_translated_label(app):
    """The Supervisor's config UI shows the bare key for anything unlabelled,
    and keeps showing a label whose option is gone. Both ways must match."""
    schema = set(manifest(app).get("schema") or {})
    data = yaml.safe_load((ROOT / app / "translations" / "en.yaml").read_text()) or {}
    labelled = set((data.get("configuration") or {}).keys())
    assert not schema - labelled, (
        f"{app}: options with no label in translations/en.yaml: {sorted(schema - labelled)}"
    )
    assert not labelled - schema, (
        f"{app}: labels for options that no longer exist: {sorted(labelled - schema)}"
    )


def test_repository_manifest_parses():
    repo = yaml.safe_load((ROOT / "repository.yaml").read_text())
    assert repo.get("name") and repo.get("url")


@pytest.mark.parametrize("app", APPS)
def test_build_manifest_matches_the_declared_arches(app):
    """A build.yaml base image for an arch the manifest doesn't list can't build."""
    build = ROOT / app / "build.yaml"
    if build.is_file():
        data = yaml.safe_load(build.read_text())
        assert data.get("build_from"), f"{app}/build.yaml has no build_from"
        assert set(data["build_from"]) <= set(manifest(app)["arch"]), (
            f"{app}/build.yaml builds for an arch the manifest doesn't list"
        )
    assert (ROOT / app / "Dockerfile").is_file(), f"{app} has no Dockerfile"
