"""The installed Studio manifest is portable across Git LF/CRLF checkouts."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is needed for Studio integrity checks")
def test_studio_hashes_ignore_text_line_endings_but_preserve_binary(tmp_path):
    for folder, newline in (("lf", "\n"), ("crlf", "\r\n")):
        root = tmp_path / folder
        files = [
            "web/src/app.tsx", "web/package.json", "web/package-lock.json", "web/pnpm-lock.yaml",
            "web/tsconfig.json", "web/vite.studio.config.ts", "scripts/build_studio.mjs",
            "pages/Settings/index.html", "pages/Settings/assets/studio.js",
        ]
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("one" + newline + "two" + newline).encode())
        (root / "pages/Settings/logo.png").write_bytes(b"binary\r\nimage")
    script = f"""
        import {{ sourceDigest, artifactDigests }} from {json.dumps((ROOT / 'scripts/studio_integrity.mjs').as_uri())};
        import {{ writeFile }} from 'node:fs/promises';
        const lf = {json.dumps(str(tmp_path / 'lf'))};
        const crlf = {json.dumps(str(tmp_path / 'crlf'))};
        const sources = [await sourceDigest(lf), await sourceDigest(crlf)];
        const before = await artifactDigests(lf + '/pages/Settings');
        const other = await artifactDigests(crlf + '/pages/Settings');
        await writeFile(crlf + '/pages/Settings/logo.png', Buffer.from('binary\\nimage'));
        const changed = await artifactDigests(crlf + '/pages/Settings');
        console.log(JSON.stringify({{ sources, before, other, changed }}));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
    values = json.loads(result.stdout)
    assert values["sources"][0] == values["sources"][1]
    assert values["before"] == values["other"]
    assert values["before"]["logo.png"] != values["changed"]["logo.png"]
