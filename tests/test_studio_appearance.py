import asyncio
import base64
import io

import pytest
from PIL import Image

from core.studio.appearance_store import StudioAppearanceStore


def test_appearance_round_trip_and_remove(tmp_path):
    store = StudioAppearanceStore(tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    data = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()

    saved = asyncio.run(store.save(mask_opacity=0.35, image_data=data))
    assert saved == {"mask_opacity": 0.35, "image_data": data}
    assert asyncio.run(StudioAppearanceStore(tmp_path).get()) == saved
    assert asyncio.run(store.save(mask_opacity=0.7, remove_image=True)) == {
        "mask_opacity": 0.7, "image_data": "",
    }


def test_appearance_rejects_invalid_image_and_opacity(tmp_path):
    store = StudioAppearanceStore(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(store.save(mask_opacity=0.5, image_data="data:image/png;base64,Zm9v"))
    with pytest.raises(ValueError):
        asyncio.run(store.save(mask_opacity=float("nan")))
