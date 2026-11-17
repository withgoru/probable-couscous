from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_dist(tmp_path):
    dist = tmp_path / "build"
    (dist / "_app").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-shell</html>")
    (dist / "_app" / "app.js").write_text("console.log('hi')")
    (tmp_path / "secret.txt").write_text("do-not-leak")
    return dist


def client_for(dist) -> TestClient:
    return TestClient(create_app(Settings(client_dist=dist)))


def test_root_serves_client_index(tmp_path):
    res = client_for(build_dist(tmp_path)).get("/")
    assert res.status_code == 200
    assert "spa-shell" in res.text


def test_asset_is_served(tmp_path):
    res = client_for(build_dist(tmp_path)).get("/_app/app.js")
    assert res.status_code == 200
    assert "console.log" in res.text


def test_unknown_page_falls_back_to_index_for_spa_routing(tmp_path):
    res = client_for(build_dist(tmp_path)).get("/courses/42")
    assert res.status_code == 200
    assert "spa-shell" in res.text


def test_path_traversal_does_not_leak_files_outside_dist(tmp_path):
    client = client_for(build_dist(tmp_path))
    for path in ["/../secret.txt", "/%2e%2e/secret.txt", "/_app/../../secret.txt"]:
        res = client.get(path)
        assert "do-not-leak" not in res.text


def test_missing_build_gives_clear_message(tmp_path):
    res = client_for(tmp_path / "nothing").get("/")
    assert res.status_code == 503
    assert "npm run build" in res.json()["detail"]
