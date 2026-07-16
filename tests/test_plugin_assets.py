from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_target_form_exposes_optional_platform_instance_id():
    html = (ROOT / "pages" / "watch" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "pages" / "watch" / "app.js").read_text(encoding="utf-8")
    assert 'id="target-platform-id"' in html
    assert 'platform_id: $("#target-platform-id").value.trim()' in script


def test_release_metadata_is_0_1_2():
    metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    assert "version: 0.1.2" in metadata
