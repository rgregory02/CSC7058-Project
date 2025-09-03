import os
import pytest
from general import app as flask_app

@pytest.fixture(scope="session")
def app():
    # ensure no live LLM calls during tests
    os.environ.pop("OPENAI_API_KEY", None)
    flask_app.config.update(TESTING=True)
    return flask_app

@pytest.fixture()
def client(app):
    return app.test_client()

def test_homepage(client):
    rv = client.get("/")
    assert rv.status_code == 200
    assert b"Biography Builder" in rv.data  
    
def test_type_person_page(client):
    rv = client.get("/type/person")
    assert rv.status_code == 200
    assert b"Person" in rv.data

def test_labels_json_for_person(client):
    rv = client.get("/api/type/person/labels.json")
    assert rv.status_code == 200
    j = rv.get_json()
    assert isinstance(j, dict) and j.get("ok") is True
    assert isinstance(j.get("labels"), list) and len(j["labels"]) > 0

def test_labels_children_endpoint(client):
    payload = {"type_name": "person", "group_key": "eye_colour", "selected_id": "green"}
    rv = client.post("/api/labels/children", json=payload)
    assert rv.status_code == 200
    j = rv.get_json()
    assert isinstance(j, dict) and "ok" in j

def test_most_like_endpoint(client):
    bio_id = "joseph_lister"  # one of your seed bios
    rv = client.get(f"/most_like/person/{bio_id}")
    assert rv.status_code == 200
    # page should contain similarity language
    txt = rv.data.lower()
    assert b"most" in txt or b"similar" in txt