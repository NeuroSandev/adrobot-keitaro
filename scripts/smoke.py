"""Сценарий против запущенного сервера: python scripts/smoke.py [base_url]."""

import sys

import httpx

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
http = httpx.Client(base_url=base, timeout=30)


def shares(stream):
    return [(o["offer_id"], o["share"]) for o in stream["offers"]], stream["total_share"]


offers = http.get("/api/offers", params={"limit": 3}).json()
print("offers:", [o["id"] for o in offers])

created = http.post("/api/campaigns", json={"name": "smoke test", "geo": "AU,MX",
                                            "offer_id": offers[0]["id"]})
created.raise_for_status()
campaign = created.json()
print("created:", campaign["keitaro_id"], campaign["url"], campaign["geo"])

view = http.get(f"/api/campaigns/{campaign['keitaro_id']}").json()
for s in view["streams"]:
    print(f"  stream #{s['position']} {s['name']}: ->", s["action_payload"] or shares(s)[0])
stream_id = next(s["id"] for s in view["streams"] if s["editable"])

for offer in offers[1:]:
    print("add", offer["id"], "->", shares(http.post(f"/api/streams/{stream_id}/offers",
                                                     json={"offer_id": offer["id"]}).json()))
print("remove", offers[0]["id"], "->",
      shares(http.delete(f"/api/streams/{stream_id}/offers/{offers[0]['id']}").json()))
guard = http.delete(f"/api/streams/{stream_id}/offers/{offers[1]['id']}")
guard = http.delete(f"/api/streams/{stream_id}/offers/{offers[2]['id']}")
print("remove last ->", guard.status_code, guard.json()["detail"])
print("history:", [h["action"] for h in http.get(f"/api/campaigns/{campaign['keitaro_id']}/history").json()])
