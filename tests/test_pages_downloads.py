"""Exercise the real Pages API responses with Quart, not a mocked send_file."""
import importlib
import io
import json
import logging
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image
from quart import Quart

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_pages_download_test_plugin"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger(__name__)
with patch.dict(sys.modules, {"astrbot": types.ModuleType("astrbot"), "astrbot.api": api}):
    PagesAPIMixin = importlib.import_module(f"{PACKAGE}.handlers.pages_api").PagesAPIMixin
AssetStore = importlib.import_module(f"{PACKAGE}.core.studio.asset_store").StudioAssetStore
ProjectStore = importlib.import_module(f"{PACKAGE}.core.studio.project_store").StudioProjectStore
JobStore = importlib.import_module(f"{PACKAGE}.core.studio.job_store").StudioJobStore
History = importlib.import_module(f"{PACKAGE}.core.image_history").ImageHistory


async def setup(tmp_path):
    plugin = PagesAPIMixin()
    plugin.data_dir = str(tmp_path)
    plugin.studio_assets = AssetStore(tmp_path)
    plugin.studio_projects = ProjectStore(tmp_path)
    plugin.studio_jobs = JobStore(tmp_path)
    plugin.image_history = History(tmp_path)
    plugin.tasks = types.SimpleNamespace(list=lambda: [])
    plugin.session_personas = types.SimpleNamespace(list=AsyncMock(return_value={}))
    scope = json.dumps(["group", "bot", "user", "session"])
    data = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(data, format="PNG")
    raw = data.getvalue()
    asset = await plugin.studio_assets.create_from_bytes(scope, "测试图片.png", raw)
    app = Quart(__name__)
    app.add_url_rule("/asset", view_func=plugin._pages_get_asset_content)
    app.add_url_rule("/media", view_func=plugin._pages_export_media_project)
    app.add_url_rule("/web", view_func=plugin._pages_export_web_project)
    app.add_url_rule("/video", view_func=plugin._pages_download_job_media)
    return plugin, app.test_client(), scope, asset, raw


@pytest.mark.asyncio
async def test_asset_download_and_inline_content(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    for download in ("0", "1"):
        response = await client.get("/asset", query_string={"id": asset["asset_id"], "scope": scope, "download": download})
        assert response.status_code == 200
        assert await response.get_data() == raw
        assert response.mimetype == "image/png"
        assert ("attachment" in response.headers.get("Content-Disposition", "")) == (download == "1")
    denied = await client.get("/asset", query_string={"id": asset["asset_id"], "scope": json.dumps(["fake"] * 4)})
    assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["canvas", "gif", "design", "web_replica"])
async def test_project_zip_download(tmp_path, kind):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    aid = asset["asset_id"]
    documents = {
        "canvas": {"version": 1, "nodes": [{"id": "node-1", "asset_id": aid, "type": "asset", "x": 0, "y": 0, "scale": 1, "rotation": 0}], "edges": []},
        "gif": {"version": 1, "frames": [aid], "frame_durations_ms": [500], "duration_ms": 500, "width": 64, "height": 64, "loop": 0},
        "design": {"version": 1, "asset_id": aid},
        "web_replica": {"version": 1, "files": [{"path": "index.html", "content": "<!doctype html><html><body>Test</body></html>"}, {"path": "style.css", "content": "body { margin: 0; }"}]},
    }
    project = await plugin.studio_projects.save(project_id=None, revision=None, scope=scope, kind=kind, name="测试项目", document=documents[kind])
    route = "/web" if kind == "web_replica" else "/media"
    response = await client.get(route, query_string={"id": project["id"], "scope": scope})
    assert response.status_code == 200, await response.get_data()
    assert response.mimetype == "application/zip"
    assert "attachment" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(await response.get_data())) as archive:
        assert archive.testzip() is None
        assert ("index.html" if kind == "web_replica" else "project.json") in archive.namelist()
        if kind != "web_replica":
            assert raw in [archive.read(name) for name in archive.namelist() if name.startswith("assets/")]


@pytest.mark.asyncio
async def test_job_video_download_and_path_protection(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    videos = tmp_path / "videos"
    videos.mkdir()
    video = videos / "test.mp4"
    video.write_bytes(b"test-video-bytes")
    job = {"id": "job-1", "scope": scope, "result": {"video_path": str(video)}}
    plugin.studio_generation = types.SimpleNamespace(get=AsyncMock(return_value=job))
    response = await client.get("/video", query_string={"id": "job-1", "scope": scope})
    assert response.status_code == 200
    assert await response.get_data() == b"test-video-bytes"
    assert "aiimg-studio-job-1.mp4" in response.headers["Content-Disposition"]
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not allowed")
    job["result"]["video_path"] = str(outside)
    response = await client.get("/video", query_string={"id": "job-1", "scope": scope})
    assert response.status_code == 404
