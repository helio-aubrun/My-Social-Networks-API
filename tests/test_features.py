import pytest

from tests.conftest import make_event, make_user


@pytest.fixture()
def people(client):
    return {
        name: make_user(client, email=f"{name}@example.com", first_name=name.capitalize())
        for name in ("alice", "bob", "carol", "dave")
    }


def group_payload(admins=(), members=(), **kw):
    payload = {"name": "Club rando", "description": "Sorties le week-end", "type": "public",
               "admin_ids": list(admins), "member_ids": list(members)}
    payload.update(kw)
    return payload


def test_private_events_hidden_from_non_invited(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    private = make_event(a, participant_ids=[b.id])
    make_event(a, name="Concert", visibility="public")

    assert [e["name"] for e in c.get("/events").json()] == ["Concert"]
    assert len(b.get("/events").json()) == 2
    assert c.get(f"/events/{private['id']}").status_code == 404


def test_user_events_and_groups(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    make_event(a, participant_ids=[b.id])
    a.post("/groups", json=group_payload(members=[b.id]))
    a.post("/groups", json=group_payload(members=[b.id], name="Secret", type="secret"))

    assert len(b.get(f"/users/{b.id}/events").json()) == 1
    assert c.get(f"/users/{b.id}/events").json() == []
    assert b.get(f"/users/{b.id}/events", params={"role": "organizer"}).json() == []
    assert len(b.get(f"/users/{b.id}/groups").json()) == 2
    assert [g["name"] for g in c.get(f"/users/{b.id}/groups").json()] == ["Club rando"]


def test_group_crud_and_admin_rules(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    r = a.post("/groups", json=group_payload(members=[b.id], icon="https://x.io/i.png"))
    assert r.status_code == 201, r.text
    g = r.json()
    assert [u["id"] for u in g["admins"]] == [a.id]
    assert {m["id"] for m in g["members"]} == {a.id, b.id}
    assert a.get("/threads", params={"group_id": g["id"]}).json()[0]["group_id"] == g["id"]

    assert b.patch(f"/groups/{g['id']}", json={"name": "Piraté"}).status_code == 403
    assert a.delete(f"/groups/{g['id']}/admins/{a.id}").status_code == 409
    assert a.delete(f"/groups/{g['id']}/members/{a.id}").status_code == 409
    assert a.delete(f"/users/{a.id}").status_code == 409

    g = a.post(f"/groups/{g['id']}/admins/{c.id}").json()
    assert c.id in {m["id"] for m in g["members"]}
    g = a.patch(f"/groups/{g['id']}", json={"type": "secret", "allow_member_posts": False}).json()
    assert g["type"] == "secret" and g["allow_member_posts"] is False

    dave = people["dave"]
    assert dave.get("/groups").json() == []
    assert dave.get(f"/groups/{g['id']}").status_code == 404
    assert len(b.get("/groups").json()) == 1
    assert a.delete(f"/groups/{g['id']}").status_code == 204
    assert a.get("/threads").json() == []


def test_join_group(client, people):
    a, d = people["alice"], people["dave"]
    public = a.post("/groups", json=group_payload()).json()
    private = a.post("/groups", json=group_payload(type="private")).json()
    assert d.post(f"/groups/{public['id']}/members/{d.id}").status_code == 200
    assert d.post(f"/groups/{private['id']}/members/{d.id}").status_code == 403
    assert d.get(f"/groups/{private['id']}/events").status_code == 403


def test_group_event_invites_all_members(client, people):
    a, b, c, d = (people[n] for n in ("alice", "bob", "carol", "dave"))
    g = a.post("/groups", json=group_payload(members=[b.id, c.id])).json()

    ev = make_event(a, group_id=g["id"])
    assert {p["id"] for p in ev["participants"]} == {b.id, c.id}

    r = d.post("/events", json={**ev, "organizer_ids": [], "group_id": g["id"]})
    assert r.status_code == 403

    a.patch(f"/groups/{g['id']}", json={"allow_member_events": False})
    r = b.post("/events", json={**ev, "organizer_ids": [], "group_id": g["id"]})
    assert r.status_code == 403

    a.post(f"/groups/{g['id']}/members/{d.id}")
    ev = a.post(f"/events/{ev['id']}/invite-group-members").json()
    assert d.id in {p["id"] for p in ev["participants"]}
    assert len(a.get(f"/groups/{g['id']}/events").json()) == 1


def test_share_only_public_events_of_public_groups(client, people):
    a = people["alice"]
    pub = make_event(a, visibility="public")
    r = a.get(f"/events/{pub['id']}/share")
    assert r.status_code == 200 and "facebook" in r.json()["links"]

    priv = make_event(a)
    assert a.get(f"/events/{priv['id']}/share").status_code == 403

    g = a.post("/groups", json=group_payload(type="private")).json()
    ev = make_event(a, visibility="public", group_id=g["id"])
    assert a.get(f"/events/{ev['id']}/share").status_code == 403


def test_thread_linked_to_group_xor_event(client, people):
    a, b = people["alice"], people["bob"]
    g = a.post("/groups", json=group_payload()).json()
    ev = make_event(a, participant_ids=[b.id])

    assert a.post("/threads", json={"group_id": g["id"], "event_id": ev["id"]}).status_code == 422
    assert a.post("/threads", json={}).status_code == 422
    assert a.post("/threads", json={"group_id": g["id"]}).status_code == 409
    assert b.post("/threads", json={"event_id": ev["id"]}).status_code == 403
    r = a.post("/threads", json={"event_id": ev["id"], "title": "Organisation"})
    assert r.status_code == 201
    assert a.post("/threads", json={"event_id": ev["id"]}).status_code == 409


def test_messages_and_comments_permissions(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    g = a.post("/groups", json=group_payload(members=[b.id])).json()
    thread = a.get("/threads", params={"group_id": g["id"]}).json()[0]

    r = b.post(f"/threads/{thread['id']}/messages", json={"content": "Salut !", "author_id": a.id})
    assert r.status_code == 201
    msg = r.json()
    assert msg["author"]["id"] == b.id
    assert c.post(f"/threads/{thread['id']}/messages", json={"content": "Intrus"}).status_code == 403

    a.patch(f"/groups/{g['id']}", json={"allow_member_posts": False})
    assert b.post(f"/threads/{thread['id']}/messages", json={"content": "Encore"}).status_code == 403
    assert a.post(f"/threads/{thread['id']}/messages", json={"content": "Admin"}).status_code == 201

    r = b.post(f"/messages/{msg['id']}/comments", json={"content": "+1"})
    assert r.status_code == 201
    comment = r.json()
    assert c.post(f"/messages/{msg['id']}/comments", json={"content": "x"}).status_code == 403

    assert a.patch(f"/message-comments/{comment['id']}", json={"content": "hack"}).status_code == 403
    assert b.patch(f"/message-comments/{comment['id']}", json={"content": "+2"}).json()["content"] == "+2"
    assert a.patch(f"/messages/{msg['id']}", json={"content": "hack"}).status_code == 403
    msgs = b.get(f"/threads/{thread['id']}/messages").json()
    assert len(msgs) == 2 and msgs[0]["comments"][0]["content"] == "+2"
    assert a.delete(f"/messages/{msg['id']}").status_code == 204


def test_event_thread_requires_participant(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    ev = make_event(a, participant_ids=[b.id])
    t = a.post("/threads", json={"event_id": ev["id"]}).json()
    assert b.post(f"/threads/{t['id']}/messages", json={"content": "ok"}).status_code == 201
    assert c.post(f"/threads/{t['id']}/messages", json={"content": "ko"}).status_code == 404
    assert c.get(f"/threads/{t['id']}/messages").status_code == 404


def test_albums_photos_comments(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    ev = make_event(a, participant_ids=[b.id], visibility="public")

    assert b.post(f"/events/{ev['id']}/albums", json={"name": "x"}).status_code == 403
    album = a.post(f"/events/{ev['id']}/albums", json={"name": "Souvenirs"}).json()
    r = b.post(f"/albums/{album['id']}/photos", json={"url": "https://x.io/1.jpg"})
    assert r.status_code == 201
    photo = r.json()
    assert c.post(f"/albums/{album['id']}/photos", json={"url": "https://x.io/2.jpg"}).status_code == 403
    assert b.post(f"/albums/{album['id']}/photos", json={"url": "javascript:alert(1)"}).status_code == 422

    assert a.post(f"/photos/{photo['id']}/comments", json={"content": "Top"}).status_code == 201
    assert c.post(f"/photos/{photo['id']}/comments", json={"content": "?"}).status_code == 403

    assert c.get(f"/albums/{album['id']}").json()["photo_count"] == 1
    assert len(b.get(f"/photos/{photo['id']}").json()["comments"]) == 1
    assert a.patch(f"/photos/{photo['id']}", json={"caption": "x"}).status_code == 403
    assert b.patch(f"/photos/{photo['id']}", json={"caption": "Coucher de soleil"}).status_code == 200
    assert a.delete(f"/albums/{album['id']}").status_code == 204
    assert a.get(f"/photos/{photo['id']}").status_code == 404


def make_poll(actor, event_id):
    return actor.post(f"/events/{event_id}/polls", json={
        "title": "Préférences",
        "questions": [
            {"text": "Quel plat ?", "options": ["Pizza", "Sushi", "Raclette"]},
            {"text": "Quelle musique ?", "options": ["Rock", "Jazz"]},
        ],
    })


def test_poll_only_by_organizer(client, people):
    a, b = people["alice"], people["bob"]
    ev = make_event(a, participant_ids=[b.id])
    assert make_poll(b, ev["id"]).status_code == 403
    r = make_poll(a, ev["id"])
    assert r.status_code == 201 and r.json()["creator"]["id"] == a.id
    bad = {"title": "x", "questions": [{"text": "?", "options": ["Seule"]}]}
    assert a.post(f"/events/{ev['id']}/polls", json=bad).status_code == 422


def test_poll_responses_and_results(client, people):
    a, b, c, d = (people[n] for n in ("alice", "bob", "carol", "dave"))
    ev = make_event(a, participant_ids=[b.id, c.id], visibility="public")
    poll = make_poll(a, ev["id"]).json()
    (q1, q2) = poll["questions"]
    pizza, sushi = q1["options"][0]["id"], q1["options"][1]["id"]
    rock = q2["options"][0]["id"]

    def answer(user, *pairs):
        return user.put(f"/polls/{poll['id']}/responses", json={
            "answers": [{"question_id": q, "option_id": o} for q, o in pairs]})

    assert answer(b, (q1["id"], pizza), (q2["id"], rock)).status_code == 200
    assert answer(c, (q1["id"], sushi), (q2["id"], rock)).status_code == 200
    assert answer(b, (q1["id"], sushi), (q2["id"], rock)).status_code == 200
    assert answer(d, (q1["id"], pizza), (q2["id"], rock)).status_code == 403
    assert answer(b, (q1["id"], pizza)).status_code == 422
    assert answer(b, (q1["id"], pizza), (q1["id"], sushi)).status_code == 422
    assert answer(b, (q1["id"], rock), (q2["id"], rock)).status_code == 422

    res = d.get(f"/polls/{poll['id']}/results").json()
    assert res["respondents"] == 2
    votes = {o["text"]: o["votes"] for o in res["questions"][0]["options"]}
    assert votes == {"Pizza": 0, "Sushi": 2, "Raclette": 0}
    assert res["questions"][1]["options"][0]["percentage"] == 100.0

    assert len(a.get(f"/polls/{poll['id']}/responses").json()) == 2
    assert [r["user_id"] for r in b.get(f"/polls/{poll['id']}/responses").json()] == [b.id]
    r = a.patch(f"/polls/{poll['id']}", json={"questions": [{"text": "?", "options": ["a", "b"]}]})
    assert r.status_code == 409
    assert a.patch(f"/polls/{poll['id']}", json={"title": "Nouveau"}).json()["title"] == "Nouveau"

    assert c.delete(f"/polls/{poll['id']}/responses/{b.id}").status_code == 403
    assert b.delete(f"/polls/{poll['id']}/responses/{b.id}").status_code == 204
    assert a.get(f"/polls/{poll['id']}/results").json()["respondents"] == 1
    assert a.delete(f"/polls/{poll['id']}").status_code == 204


BUYER = {"first_name": "Jean", "last_name": "Dupont", "email": "jean@ext.com",
         "street": "1 rue Victor Hugo", "postal_code": "75001", "city": "Paris", "country": "France"}


def test_ticketing_rules(client, people):
    a, b = people["alice"], people["bob"]
    r = a.post("/events", json={**make_event(a), "organizer_ids": [], "ticketing_enabled": True})
    assert r.status_code == 422

    no_ticketing = make_event(a, visibility="public")
    assert a.post(f"/events/{no_ticketing['id']}/ticket-types",
                  json={"name": "Std", "price": 10, "quantity": 5}).status_code == 409

    ev = make_event(a, visibility="public", ticketing_enabled=True)
    assert b.post(f"/events/{ev['id']}/ticket-types", json={"name": "x", "price": 1, "quantity": 1}).status_code == 403
    vip = a.post(f"/events/{ev['id']}/ticket-types", json={"name": "VIP", "price": 49.9, "quantity": 1}).json()
    std = a.post(f"/events/{ev['id']}/ticket-types", json={"name": "Std", "price": 15, "quantity": 100}).json()

    r = client.post(f"/ticket-types/{vip['id']}/tickets", json=BUYER)
    assert r.status_code == 201 and r.json()["purchased_at"]
    ticket = r.json()

    assert client.post(f"/ticket-types/{std['id']}/tickets", json={**BUYER, "email": "JEAN@ext.com"}).status_code == 409
    assert client.post(f"/ticket-types/{vip['id']}/tickets", json={**BUYER, "email": "z@ext.com"}).status_code == 409

    tt = b.get(f"/ticket-types/{vip['id']}").json()
    assert (tt["sold"], tt["remaining"]) == (1, 0)
    assert a.patch(f"/ticket-types/{vip['id']}", json={"quantity": 0}).status_code == 422
    assert a.delete(f"/ticket-types/{vip['id']}").status_code == 409
    assert a.patch(f"/events/{ev['id']}", json={"visibility": "private"}).status_code == 422

    stats = a.get(f"/events/{ev['id']}/stats").json()
    assert stats["tickets_sold"] == 1 and stats["ticket_revenue"] == 49.9
    assert b.get(f"/events/{ev['id']}/stats").status_code == 403

    assert b.get(f"/events/{ev['id']}/tickets").status_code == 403
    assert b.get(f"/tickets/{ticket['id']}").status_code == 403
    assert len(a.get(f"/events/{ev['id']}/tickets", params={"email": "jean@ext.com"}).json()) == 1
    assert a.patch(f"/tickets/{ticket['id']}", json={"city": "Lyon"}).json()["city"] == "Lyon"
    assert a.delete(f"/tickets/{ticket['id']}").status_code == 204
    assert a.get(f"/ticket-types/{vip['id']}").json()["remaining"] == 1


def test_shopping_list(client, people):
    a, b, c = people["alice"], people["bob"], people["carol"]
    off = make_event(a, participant_ids=[b.id])
    item = {"name": "Chips", "quantity": 3, "arrival_time": "2026-12-01T19:30:00"}
    assert b.post(f"/events/{off['id']}/shopping-items", json=item).status_code == 409

    ev = make_event(a, participant_ids=[b.id], shopping_list_enabled=True, visibility="public")
    r = b.post(f"/events/{ev['id']}/shopping-items", json=item)
    assert r.status_code == 201 and r.json()["user"]["id"] == b.id
    created = r.json()
    assert a.post(f"/events/{ev['id']}/shopping-items", json={**item, "name": "  chips "}).status_code == 409
    assert c.post(f"/events/{ev['id']}/shopping-items", json={**item, "name": "Coca"}).status_code == 403
    assert b.post(f"/events/{ev['id']}/shopping-items", json={**item, "name": "Coca"}).status_code == 201

    assert c.patch(f"/shopping-items/{created['id']}", json={"quantity": 9}).status_code == 403
    assert b.patch(f"/shopping-items/{created['id']}", json={"name": "coca"}).status_code == 409
    assert b.patch(f"/shopping-items/{created['id']}", json={"quantity": 5}).json()["quantity"] == 5
    assert len(c.get(f"/events/{ev['id']}/shopping-items").json()) == 2
    assert a.delete(f"/shopping-items/{created['id']}").status_code == 204


def test_carpool(client, people):
    a, b, c, d = (people[n] for n in ("alice", "bob", "carol", "dave"))
    ev = make_event(a, participant_ids=[b.id, c.id], carpool_enabled=True, visibility="public")
    offer = {"departure_location": "Gare de Lyon", "departure_time": "2026-12-01T16:30:00",
             "price": 12.5, "seats": 1, "max_detour_minutes": 30}
    r = a.post(f"/events/{ev['id']}/carpools", json=offer)
    assert r.status_code == 201 and r.json()["driver"]["id"] == a.id
    o = r.json()
    assert d.post(f"/events/{ev['id']}/carpools", json=offer).status_code == 403

    assert a.post(f"/carpools/{o['id']}/bookings").status_code == 409
    r = b.post(f"/carpools/{o['id']}/bookings")
    assert r.status_code == 201 and r.json()["remaining_seats"] == 0
    assert c.post(f"/carpools/{o['id']}/bookings").status_code == 409
    assert a.get(f"/events/{ev['id']}/carpools", params={"available_only": True}).json() == []

    assert c.delete(f"/carpools/{o['id']}/bookings/{b.id}").status_code == 403
    r = b.delete(f"/carpools/{o['id']}/bookings/{b.id}")
    assert r.json()["remaining_seats"] == 1
    assert b.patch(f"/carpools/{o['id']}", json={"seats": 3}).status_code == 403
    assert a.patch(f"/carpools/{o['id']}", json={"seats": 3}).json()["seats"] == 3
    assert a.delete(f"/carpools/{o['id']}").status_code == 204


def test_delete_event_cascades(client, people):
    a, b = people["alice"], people["bob"]
    ev = make_event(a, participant_ids=[b.id], shopping_list_enabled=True)
    t = a.post("/threads", json={"event_id": ev["id"]}).json()
    b.post(f"/threads/{t['id']}/messages", json={"content": "hello"})
    album = a.post(f"/events/{ev['id']}/albums", json={"name": "A"}).json()
    poll = make_poll(a, ev["id"]).json()

    assert a.delete(f"/events/{ev['id']}").status_code == 204
    assert a.get(f"/threads/{t['id']}").status_code == 404
    assert a.get(f"/albums/{album['id']}").status_code == 404
    assert a.get(f"/polls/{poll['id']}").status_code == 404
