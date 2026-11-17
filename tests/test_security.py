from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from app.main import app
from tests.conftest import PASSWORD, make_event, make_user


def test_routes_require_token(client):
    r = client.get("/users")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/events", headers={"Authorization": "Bearer abc.def.ghi"}).json()["detail"] == "Jeton invalide"
    assert client.get("/events", headers={"Authorization": "Basic dXNlcjpwYXNz"}).status_code == 401


def test_expired_and_forged_tokens(client):
    alice = make_user(client)
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = jwt.encode({"sub": str(alice.id), "iat": past, "exp": past + timedelta(minutes=1)},
                         get_settings().jwt_secret, algorithm="HS256")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["detail"] == "Jeton expiré"

    now = datetime.now(timezone.utc)
    forged = jwt.encode({"sub": str(alice.id), "iat": now, "exp": now + timedelta(hours=1)},
                        "mauvais-secret-" + "y" * 40, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401

    unsigned = jwt.encode({"sub": str(alice.id), "iat": now, "exp": now + timedelta(hours=1)}, None, algorithm="none")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_login(client):
    alice = make_user(client)
    me = client.get("/auth/me", headers=alice.headers).json()
    assert me["id"] == alice.id and "password_hash" not in me

    wrong = client.post("/auth/login", json={"email": "alice@example.com", "password": "Mauvais123"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "Mauvais123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_password_policy(client):
    base = {"first_name": "A", "last_name": "B", "email": "a@example.com"}
    for weak in ("court1A", "toutminuscule1", "TOUTMAJUSCULE1", "SansChiffre"):
        assert client.post("/users", json={**base, "password": weak}).status_code == 422
    r = client.post("/users", json={**base, "password": PASSWORD, "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "user"


def test_login_rate_limit(client):
    make_user(client)
    bad = {"email": "alice@example.com", "password": "Mauvais123"}
    for _ in range(get_settings().login_rate_limit):
        assert client.post("/auth/login", json=bad).status_code == 401
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_global_rate_limit(client):
    limiter = app.state.rate_limiter
    previous = limiter.global_limit
    limiter.global_limit = 3
    try:
        codes = [client.get("/").status_code for _ in range(4)]
    finally:
        limiter.global_limit = previous
    assert codes == [200, 200, 200, 429]


def test_body_size_limit(client):
    alice = make_user(client)
    huge = "x" * (get_settings().max_body_bytes + 1)
    r = alice.post("/events", json={"name": "x", "description": huge})
    assert r.status_code == 413


def test_security_headers_and_cors(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" in r.headers
    assert "server" not in r.headers

    allowed = client.options("/users", headers={
        "Origin": "https://front.example.com", "Access-Control-Request-Method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "https://front.example.com"
    denied = client.get("/", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in denied.headers


def test_self_or_admin(client, make_admin):
    alice = make_user(client)
    bob = make_user(client, email="bob@example.com")
    assert bob.patch(f"/users/{alice.id}", json={"bio": "piraté"}).status_code == 403
    assert bob.delete(f"/users/{alice.id}").status_code == 403

    make_admin(bob)
    assert bob.patch(f"/users/{alice.id}", json={"bio": "modéré"}).status_code == 200
    private = make_event(alice)
    assert bob.get(f"/events/{private['id']}").status_code == 200
    assert bob.delete(f"/users/{alice.id}").status_code == 409


def test_like_wildcards_are_escaped(client):
    alice = make_user(client)
    make_user(client, email="bob@example.com", first_name="Bob")
    assert len(alice.get("/users", params={"q": "%"}).json()) == 0
    assert len(alice.get("/users", params={"q": "_"}).json()) == 0
    assert len(alice.get("/users", params={"q": "bob"}).json()) == 1


def test_secret_and_private_content_hidden(client):
    alice = make_user(client)
    eve = make_user(client, email="eve@example.com")
    group = alice.post("/groups", json={"name": "Secret", "type": "secret"}).json()
    thread = alice.get("/threads", params={"group_id": group["id"]}).json()[0]
    assert eve.get(f"/groups/{group['id']}").status_code == 404
    assert eve.get(f"/threads/{thread['id']}").status_code == 404

    event = make_event(alice)
    album = alice.post(f"/events/{event['id']}/albums", json={"name": "Privé"}).json()
    assert eve.get(f"/events/{event['id']}/albums").status_code == 404
    assert eve.get(f"/albums/{album['id']}").status_code == 404
