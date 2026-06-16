import pytest

from core.persona_ref_service import PersonaRefService


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 8
DATA_URL = "data:image/png;base64,iVBORw0KGgoAAAAAAAAAAA=="


def test_detect_ref_image_uses_magic_bytes():
    assert PersonaRefService.detect_ref_image(PNG_BYTES) == ("image/png", "png")
    assert PersonaRefService.detect_ref_image(JPEG_BYTES) == ("image/jpeg", "jpg")
    assert PersonaRefService.detect_ref_image(b"not image") is None


def test_build_ref_filename_sanitizes_name_and_uses_detected_extension():
    name = PersonaRefService.build_ref_filename("../bad name?.txt", "png", now_ns=123)

    assert name == "123_bad_name.png"
    assert "/" not in name
    assert "\\" not in name


@pytest.mark.asyncio
async def test_save_data_url_refs_converts_images_to_local_files(tmp_path):
    service = PersonaRefService(tmp_path, now_ns=lambda: 456)

    refs = await service.save_base64_refs([DATA_URL, "https://example.com/ref.png", ""])

    assert len(refs) == 2
    assert refs[1] == "https://example.com/ref.png"
    saved = tmp_path / "persona_refs" / "456_reference.png"
    assert refs[0] == str(saved)
    assert saved.read_bytes() == PNG_BYTES


@pytest.mark.asyncio
async def test_preview_data_url_rejects_unsafe_paths(tmp_path):
    service = PersonaRefService(tmp_path)
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(PNG_BYTES)

    with pytest.raises(ValueError, match="forbidden"):
        await service.preview_data_url(str(outside))
