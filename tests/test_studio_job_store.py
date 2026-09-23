import pytest

from core.studio.job_store import StudioJobStore


@pytest.mark.asyncio
async def test_job_store_idempotency_and_state_round_trip(tmp_path):
    store = StudioJobStore(tmp_path)
    scope = '["origin","bot","sender","conversation"]'
    first, created = await store.create(
        idempotency_key="same-request",
        scope=scope,
        kind="image",
        mode="draw",
        prompt="a white bird",
        request={"scope": scope},
    )
    second, duplicate = await store.create(
        idempotency_key="same-request",
        scope=scope,
        kind="image",
        mode="draw",
        prompt="a white bird",
        request={"scope": scope},
    )

    assert created is True
    assert duplicate is False
    assert first["id"] == second["id"]

    updated = await store.update(first["id"], state="completed", result={"image_id": 7})
    assert updated["state"] == "completed"
    assert updated["result"] == {"image_id": 7}
