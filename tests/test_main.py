import re
import shutil
import subprocess
from pathlib import Path

import pytest
from app import main
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"

client = TestClient(main.app)


@pytest.fixture(scope="module", autouse=True)
def built_frontend() -> None:
    """Build the front end before the server tests read its output."""
    npm = shutil.which("npm")
    assert npm is not None, "npm is required to build the front end"
    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        installed = subprocess.run(
            [npm, "install", "--no-audit", "--no-fund"],
            cwd=FRONTEND,
            text=True,
            capture_output=True,
            timeout=300,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
    built = subprocess.run(
        [npm, "run", "build"],
        cwd=FRONTEND,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stdout + built.stderr


def asset_urls(index: str) -> list[str]:
    """The built asset URLs the index page loads."""
    return re.findall(r'(?:src|href)="(/assets/[^"]+)"', index)


def test_case_1_building_writes_the_entry_and_bundled_assets() -> None:
    """Case 1: the build exits 0 and writes dist/index.html plus its assets."""
    index_path = DIST / "index.html"
    assert index_path.is_file(), "the build should write dist/index.html"
    index = index_path.read_text()
    urls = asset_urls(index)
    assert urls, "the built index should load at least one bundled asset"
    for url in urls:
        assert (DIST / url.removeprefix("/")).is_file(), f"{url} should be in dist"


def test_case_2_get_root_serves_the_built_index_and_assets() -> None:
    """Case 2: GET / is the built index, and every asset it names answers 200."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    index = (DIST / "index.html").read_text()
    assert response.text == index
    for url in asset_urls(index):
        asset = client.get(url)
        assert asset.status_code == 200, f"{url} should be served from the build"
        assert asset.content, f"{url} should not be empty"


def test_case_3_the_old_form_routes_are_gone() -> None:
    """Case 3: every old server-rendered form route answers 404 or 405."""
    # makase: inventory
    old_form_routes = (
        "/todos",
        "/todos/1/done",
        "/todos/1/undo",
        "/todos/1/edit",
        "/todos/1/delete",
    )
    for path in old_form_routes:
        response = client.post(path, data={"title": "Still here?"})

        assert response.status_code in {404, 405}, (
            f"{path} should no longer accept a form post, got {response.status_code}"
        )
