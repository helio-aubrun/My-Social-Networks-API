import os

os.environ.update({
    "JWT_SECRET": "test-secret-" + "x" * 40,
    "DATABASE_URL": "sqlite://",
    "BCRYPT_ROUNDS": "4",
    "RATE_LIMIT_PER_HOUR": "100000",
    "CORS_ORIGINS": "https://front.example.com",
})

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app

PASSWORD = "MotDePasse1"


class Actor:
    def __init__(self, client, data: dict, token: str):
        self.client = client
        self.data = data
        self.id = data["id"]
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def __getitem__(self, key):
        return self.data[key]

    def request(self, method: str, url: str, **kwargs):
        return self.client.request(method, url, headers=self.headers, **kwargs)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.rate_limiter.reset()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.rate_limiter.reset()


@pytest.fixture()
def make_admin(session_factory):
    def promote(actor: Actor) -> Actor:
        with session_factory() as db:
            db.get(models.User, actor.id).role = models.Role.admin
            db.commit()
        return actor
    return promote


def make_user(client, email="alice@example.com", **kw) -> Actor:
    payload = {"first_name": "Alice", "last_name": "Martin", "email": email, "password": PASSWORD}
    payload.update(kw)
    r = client.post("/users", json=payload)
    assert r.status_code == 201, r.text
    login = client.post("/auth/login", json={"email": email, "password": payload["password"]})
    assert login.status_code == 200, login.text
    return Actor(client, r.json(), login.json()["access_token"])


def event_payload(**kw):
    payload = {
        "name": "Soirée jeux",
        "description": "Jeux de société et pizzas",
        "start_date": "2026-12-01T19:00:00",
        "end_date": "2026-12-01T23:00:00",
        "location": "12 rue de Paris, Lyon",
        "cover_photo": "https://example.com/cover.jpg",
        "visibility": "private",
    }
    payload.update(kw)
    return payload


def make_event(actor: Actor, **kw):
    r = actor.post("/events", json=event_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()
