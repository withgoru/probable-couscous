from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(client_dist=tmp_path / "missing")))


def test_health_returns_ok(tmp_path):
    res = make_client(tmp_path).get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_unknown_api_path_is_json_404_not_index_html(tmp_path):
    (tmp_path / "index.html").write_text("<html>spa</html>")
    client = TestClient(create_app(Settings(client_dist=tmp_path)))
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")
