"""Эмулятор Keitaro в памяти: тот же интерфейс, что у KeitaroClient.

Нужен для демо без доступа к трекеру и для тестов.
"""

import copy
import threading

from app.keitaro.client import KeitaroError

SEED_OFFERS = [
    (3749, "Miaflow [BEAUTY-RO-BE_0009] [pl - 50%| - spin ro -] 2. Основной, Румыния"),
    (3717, "Miaflow [BEAUTY-RO-BE_0008] [pl - 50%| - prize ro -] 1. Основной, Румыния"),
    (3801, "Glucoflow [DIA-MX-0003] [pl - 100%] Основной, Мексика"),
    (3802, "Glucoflow [DIA-MX-0004] [pl - 100%] Резерв, Мексика"),
    (3910, "Artrolux [JOINT-AU-0001] Основной, Австралия"),
    (3911, "Artrolux [JOINT-AU-0002] Резерв, Австралия"),
    (4002, "Visiomax [EYE-RO-0011] Основной, Румыния"),
]


class FakeKeitaro:
    def __init__(self):
        self._lock = threading.Lock()
        self._ids = 100
        self.domains = [{"id": 1, "name": "in.posdk.xyz"}, {"id": 2, "name": "go.example.com"}]
        self.groups = [{"id": 1, "name": "FORTESTS", "type": "campaigns"}]
        self.sources = [{"id": 1, "name": "FORTESTS"}]
        self.offers = [{"id": i, "name": n, "state": "active"} for i, n in SEED_OFFERS]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def _offer_ids(self) -> set[int]:
        return {o["id"] for o in self.offers}

    def list_domains(self):
        return copy.deepcopy(self.domains)

    def list_groups(self):
        return copy.deepcopy(self.groups)

    def create_group(self, name):
        with self._lock:
            group = {"id": self._next_id(), "name": name, "type": "campaigns"}
            self.groups.append(group)
            return copy.deepcopy(group)

    def list_traffic_sources(self):
        return copy.deepcopy(self.sources)

    def create_traffic_source(self, name):
        with self._lock:
            source = {"id": self._next_id(), "name": name}
            self.sources.append(source)
            return copy.deepcopy(source)

    def list_offers(self):
        return copy.deepcopy(self.offers)

    def list_campaigns(self):
        return [copy.deepcopy(c) for c in self.campaigns.values()]

    def get_campaign(self, campaign_id):
        if campaign_id not in self.campaigns:
            raise KeitaroError(404, "Campaign not found")
        return copy.deepcopy(self.campaigns[campaign_id])

    def create_campaign(self, payload):
        with self._lock:
            if not payload.get("name"):
                raise KeitaroError(422, "name is required")
            campaign = {"id": self._next_id(), "state": "active", **payload}
            self.campaigns[campaign["id"]] = campaign
            return copy.deepcopy(campaign)

    def delete_campaign(self, campaign_id):
        with self._lock:
            self.campaigns.pop(campaign_id, None)
            for sid in [s for s, v in self.streams.items() if v["campaign_id"] == campaign_id]:
                del self.streams[sid]

    def list_streams(self, campaign_id):
        self.get_campaign(campaign_id)
        found = [s for s in self.streams.values() if s["campaign_id"] == campaign_id]
        return copy.deepcopy(sorted(found, key=lambda s: s.get("position", 0)))

    def get_stream(self, stream_id):
        if stream_id not in self.streams:
            raise KeitaroError(404, "Stream not found")
        return copy.deepcopy(self.streams[stream_id])

    def _normalize_offers(self, offers):
        known = self._offer_ids()
        result = []
        for item in offers or []:
            if item["offer_id"] not in known:
                raise KeitaroError(422, f"Offer {item['offer_id']} not found")
            result.append({
                "id": self._next_id(),
                "offer_id": item["offer_id"],
                "share": int(item.get("share", 100)),
                "state": item.get("state", "active"),
            })
        return result

    def create_stream(self, payload):
        with self._lock:
            if payload.get("campaign_id") not in self.campaigns:
                raise KeitaroError(422, "campaign_id is invalid")
            stream = {**payload, "id": self._next_id()}
            stream["offers"] = self._normalize_offers(payload.get("offers"))
            self.streams[stream["id"]] = stream
            return copy.deepcopy(stream)

    def update_stream(self, stream_id, payload):
        with self._lock:
            if stream_id not in self.streams:
                raise KeitaroError(404, "Stream not found")
            stream = self.streams[stream_id]
            for key, value in payload.items():
                if key == "offers":
                    stream["offers"] = self._normalize_offers(value)
                else:
                    stream[key] = value
            return copy.deepcopy(stream)
