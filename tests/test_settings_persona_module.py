"""Current Studio persona transport and explicit new-record state regression guards."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web" / "src" / "app" / "StudioApp.tsx"
CLIENT = ROOT / "web" / "src" / "api" / "client.ts"


def test_persona_reference_transport_lives_in_api_module():
    client = CLIENT.read_text(encoding="utf-8")
    source = APP.read_text(encoding="utf-8")
    assert 'apiPost("upload_studio_persona_ref"' in client
    assert 'apiGet("get_image_b64"' in client
    assert "uploadStudioPersonaReference" in source
    assert "loadPersonaReferencePreview" in source


def test_new_persona_is_not_replaced_by_first_profile():
    source = APP.read_text(encoding="utf-8").split("function PersonasView", 1)[1].split("const providerSecretFields", 1)[0]
    create_guard = source.split("if (creating) {", 1)[1].split("if (!selectedId", 1)[0]
    assert "return;" in create_guard
    assert "setCreating(false)" in create_guard
    assert "[creating, selectedId, snapshot.personaProfiles]" in source
    create = source.split("function createNew()", 1)[1].split("function updateDraft", 1)[0]
    assert "setCreating(true)" in create
    assert 'setSelectedId("")' in create
    assert 'name: ""' in create
