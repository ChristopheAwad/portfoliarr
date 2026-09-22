"""Contracts for the shared Flask and Android release version."""

import re
from pathlib import Path

import pytest

import app as app_module


ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
GRADLE_BUILD = ROOT / "android" / "app" / "build.gradle.kts"
GRADLE_PROPERTIES = ROOT / "android" / "gradle.properties"


def test_shared_version_file_contains_current_release():
    assert VERSION_FILE.exists()
    version = VERSION_FILE.read_text().strip()
    assert version == "1.1"
    assert re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)


def test_version_loader_trims_valid_release(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("  2.3.4\n")

    assert app_module._load_app_version(version_file) == "2.3.4"


@pytest.mark.parametrize(
    "value",
    ["", "   \n", "v1.1", "1", "1.", ".1", "1.x", "1.2.3.4", "1.2-beta"],
)
def test_version_loader_rejects_malformed_release(tmp_path, value):
    version_file = tmp_path / "VERSION"
    version_file.write_text(value)

    with pytest.raises(ValueError, match="Invalid app version"):
        app_module._load_app_version(version_file)


def test_version_loader_does_not_hide_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        app_module._load_app_version(tmp_path / "missing")


def test_flask_version_matches_shared_file():
    assert app_module.APP_VERSION == VERSION_FILE.read_text().strip()


def test_preferences_renders_static_about_version(client):
    html = client.get("/preferences").get_data(as_text=True)
    ledger_at = html.index("<h3>Ledger</h3>")
    about_at = html.index("<h3>About</h3>")
    version_at = html.index('class="app-version"', about_at)

    assert ledger_at < about_at < version_at
    assert "Version" in html[about_at:version_at]
    assert f">{app_module.APP_VERSION}<" in html[version_at:]

    about_card = html[about_at:html.index("</div>", version_at) + len("</div>")]
    assert not re.search(r"<(?:input|select|button|a)\b", about_card)


def test_android_uses_shared_version_and_keeps_version_code_separate():
    build = GRADLE_BUILD.read_text()
    properties = GRADLE_PROPERTIES.read_text()

    assert 'resolve("VERSION")' in build
    assert ".readText().trim()" in build
    assert "sharedVersion.matches" in build
    assert "versionName = sharedVersion" in build
    assert "VERSION_NAME" not in build

    assert re.search(r"^VERSION_CODE=2$", properties, re.MULTILINE)
    assert not re.search(r"^VERSION_NAME=", properties, re.MULTILINE)
    assert "root VERSION" in properties
