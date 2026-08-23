import tempfile
import shutil
import pytest
from app import create_app
from config import Config


@pytest.fixture()
def app():
    tmp_dir = tempfile.mkdtemp(prefix="cng_test_")

    class TestConfig(Config):
        DATA_DIR = tmp_dir
        TESTING = True

    app = create_app(TestConfig)
    yield app
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def demo_project_id(client):
    r = client.post("/api/projects/demo")
    assert r.status_code == 201
    return r.get_json()["id"]
