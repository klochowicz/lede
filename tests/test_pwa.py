import json
from pathlib import Path

STATIC = Path(__file__).parent.parent / "briefing" / "static"


def test_manifest_is_valid_and_installable():
    manifest = json.loads((STATIC / "manifest.json").read_text())
    assert manifest["name"]
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"], "installable PWA needs at least one icon"


def test_service_worker_registers_lifecycle_events():
    sw = (STATIC / "sw.js").read_text()
    assert "install" in sw
    assert "fetch" in sw
