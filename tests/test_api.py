from tests.conftest import PASSWORD, event_payload, make_event, make_user


def test_user_crud(client):
    alice = make_user(client)
    assert "password" not in alice.data and "password_hash" not in alice.data
    assert alice["role"] == "user"

    assert alice.get(f"/users/{alice.id}").json()["email"] == "alice@example.com"

    r = alice.patch(f"/users/{alice.id}", json={"bio": "Hello"})
    assert r.status_code == 200 and r.json()["bio"] == "Hello"

    assert len(alice.get("/users", params={"q": "mart"}).json()) == 1
    assert alice.delete(f"/users/{alice.id}").status_code == 204
    assert client.get("/auth/me", headers=alice.headers).status_code == 401


def test_email_unique(client):
    make_user(client)
    r = client.post("/users", json={"first_name": "B", "last_name": "B",
                                     "email": "ALICE@example.com", "password": PASSWORD})
    assert r.status_code == 409

    bob = make_user(client, email="bob@example.com")
    assert bob.patch(f"/users/{bob.id}", json={"email": "alice@example.com"}).status_code == 409


def test_invalid_email(client):
    r = client.post("/users", json={"first_name": "A", "last_name": "B",
                                     "email": "pas-un-email", "password": PASSWORD})
    assert r.status_code == 422


def test_event_crud(client):
    alice = make_user(client)
    bob = make_user(client, email="bob@example.com")

    r = alice.post("/events", json=event_payload(participant_ids=[bob.id]))
    assert r.status_code == 201, r.text
    ev = r.json()
    assert [o["id"] for o in ev["organizers"]] == [alice.id]
    assert [p["id"] for p in ev["participants"]] == [bob.id]
    assert ev["visibility"] == "private"

    assert bob.patch(f"/events/{ev['id']}", json={"location": "Paris"}).status_code == 403
    r = alice.patch(f"/events/{ev['id']}", json={"location": "Paris", "organizer_ids": [alice.id, bob.id]})
    assert r.status_code == 200
    assert r.json()["location"] == "Paris" and len(r.json()["organizers"]) == 2

    assert len(bob.get("/events", params={"organizer_id": bob.id}).json()) == 1
    assert len(bob.get("/events", params={"visibility": "public"}).json()) == 0

    assert alice.delete(f"/events/{ev['id']}").status_code == 204
    assert alice.get(f"/events/{ev['id']}").status_code == 404


def test_event_dates(client):
    alice = make_user(client)
    bad = event_payload(end_date="2026-11-30T10:00:00")
    assert alice.post("/events", json=bad).status_code == 422

    ev = make_event(alice)
    r = alice.patch(f"/events/{ev['id']}", json={"end_date": "2026-11-01T10:00:00"})
    assert r.status_code == 422


def test_cannot_remove_last_organizer(client):
    alice = make_user(client)
    bob = make_user(client, email="bob@example.com")
    ev = make_event(alice)

    assert alice.delete(f"/events/{ev['id']}/organizers/{alice.id}").status_code == 409
    assert alice.delete(f"/users/{alice.id}").status_code == 409

    alice.post(f"/events/{ev['id']}/organizers/{bob.id}")
    assert alice.delete(f"/events/{ev['id']}/organizers/{alice.id}").status_code == 200


def test_participants_endpoints(client):
    alice = make_user(client)
    bob = make_user(client, email="bob@example.com")
    carol = make_user(client, email="carol@example.com")
    ev = make_event(alice)

    r = alice.post(f"/events/{ev['id']}/participants/{bob.id}")
    assert [p["id"] for p in r.json()["participants"]] == [bob.id]
    assert bob.post(f"/events/{ev['id']}/participants/{carol.id}").status_code == 403
    r = bob.delete(f"/events/{ev['id']}/participants/{bob.id}")
    assert r.json()["participants"] == []

    public = make_event(alice, visibility="public")
    assert carol.post(f"/events/{public['id']}/participants/{carol.id}").status_code == 200
