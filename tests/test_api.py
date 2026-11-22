from app.keitaro.client import KeitaroError


def create(client, **overrides):
    body = {"name": "campaign 2", "geo": "au", "offer_id": 3749, **overrides}
    return client.post("/api/campaigns", json=body)


def test_create_campaign_builds_two_streams(client, fake):
    response = create(client, geo="mx, AU;mx")
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["geo"] == ["MX", "AU"]
    assert data["url"] == f"https://in.posdk.xyz/{data['alias']}"

    campaign = fake.get_campaign(data["keitaro_id"])
    assert campaign["type"] == "position"
    assert campaign["domain_id"] == 1
    assert campaign["group_id"] == 1 and campaign["traffic_source_id"] == 1  # FORTESTS

    geo_stream, offers_stream = fake.list_streams(data["keitaro_id"])
    assert geo_stream["position"] == 1
    assert geo_stream["action_payload"] == "https://google.com"
    assert geo_stream["filters"] == [{"name": "country", "mode": "accept", "payload": ["MX", "AU"]}]
    assert offers_stream["position"] == 2
    assert [(o["offer_id"], o["share"]) for o in offers_stream["offers"]] == [(3749, 100)]


def test_create_creates_missing_group_and_source(client, fake):
    fake.groups.clear()
    fake.sources.clear()
    data = create(client).json()
    assert [g["name"] for g in fake.groups] == ["FORTESTS"]
    assert fake.get_campaign(data["keitaro_id"])["group_id"] == fake.groups[0]["id"]


def test_create_validation(client):
    assert create(client, geo="Australia").status_code == 400
    assert create(client, geo=" , ").status_code == 400
    assert create(client, offer_id=999999).status_code == 400
    assert create(client, name="   ").status_code == 400


def test_create_rolls_back_campaign_if_stream_fails(client, fake, monkeypatch):
    def broken(payload):
        raise KeitaroError(500, "boom")
    monkeypatch.setattr(fake, "create_stream", broken)
    response = create(client)
    assert response.status_code == 502
    assert fake.campaigns == {}


def offers_of(client, campaign_id):
    streams = client.get(f"/api/campaigns/{campaign_id}").json()["streams"]
    stream = next(s for s in streams if s["editable"])
    return stream["id"], [(o["offer_id"], o["share"]) for o in stream["offers"]]


def test_editor_add_remove_set(client):
    campaign_id = create(client).json()["keitaro_id"]
    stream_id, offers = offers_of(client, campaign_id)
    assert offers == [(3749, 100)]

    r = client.post(f"/api/streams/{stream_id}/offers", json={"offer_id": 3717})
    assert r.status_code == 200, r.text
    assert offers_of(client, campaign_id)[1] == [(3749, 50), (3717, 50)]

    client.post(f"/api/streams/{stream_id}/offers", json={"offer_id": 3801})
    assert offers_of(client, campaign_id)[1] == [(3749, 34), (3717, 33), (3801, 33)]

    assert client.post(f"/api/streams/{stream_id}/offers", json={"offer_id": 3801}).status_code == 400

    client.delete(f"/api/streams/{stream_id}/offers/3717")
    assert offers_of(client, campaign_id)[1] == [(3749, 50), (3801, 50)]

    r = client.put(f"/api/streams/{stream_id}/offers",
                   json={"offers": [{"offer_id": 3749, "share": 70}, {"offer_id": 3801, "share": 30}]})
    assert r.status_code == 200 and r.json()["total_share"] == 100

    client.post(f"/api/streams/{stream_id}/offers", json={"offer_id": 3910, "mode": "proportional"})
    assert offers_of(client, campaign_id)[1] == [(3749, 47), (3801, 20), (3910, 33)]

    history = client.get(f"/api/campaigns/{campaign_id}/history").json()
    assert [h["action"] for h in history] == ["add", "set", "remove", "add", "add"]
    assert history[2]["before"][1]["offer_id"] == 3717


def test_editor_guards(client):
    campaign_id = create(client).json()["keitaro_id"]
    stream_id, _ = offers_of(client, campaign_id)
    geo_stream_id = client.get(f"/api/campaigns/{campaign_id}").json()["streams"][0]["id"]

    assert client.delete(f"/api/streams/{stream_id}/offers/3749").status_code == 400  # последний
    assert client.delete(f"/api/streams/{stream_id}/offers/3717").status_code == 404
    assert client.post(f"/api/streams/{geo_stream_id}/offers", json={"offer_id": 3717}).status_code == 400
    bad_sum = {"offers": [{"offer_id": 3749, "share": 90}]}
    assert client.put(f"/api/streams/{stream_id}/offers", json=bad_sum).status_code == 400
    wrong_set = {"offers": [{"offer_id": 3717, "share": 100}]}
    assert client.put(f"/api/streams/{stream_id}/offers", json=wrong_set).status_code == 400


def test_offer_search_and_pages(client):
    assert [o["id"] for o in client.get("/api/offers?q=glucoflow").json()] == [3801, 3802]
    assert [o["id"] for o in client.get("/api/offers?q=3910").json()] == [3910]
    assert client.get("/").status_code == 200
    assert client.get("/campaigns/1").status_code == 200
