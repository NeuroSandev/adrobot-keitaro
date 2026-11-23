"""Проверка «оффер не теряется»: параллельные добавления в один поток.

    python scripts/race.py http://127.0.0.1:8077 [--repeat 5]

Для каждого прогона создаётся кампания, затем все офферы, кроме стартового, добавляются
одновременно. В конце набор в потоке должен содержать все офферы, сумма долей — 100,
а в истории должна быть запись на каждое добавление.
Работает против эмулятора (KEITARO_FAKE=1, один процесс сервера).
"""

import argparse
import sys
import threading

import httpx


def run_once(base: str, number: int) -> list[str]:
    problems: list[str] = []
    with httpx.Client(base_url=base, timeout=30) as http:
        offer_ids = [o["id"] for o in http.get("/api/offers", params={"limit": 50}).json()]
        start, rest = offer_ids[0], offer_ids[1:]
        created = http.post("/api/campaigns", json={"name": f"race {number}", "geo": "AU", "offer_id": start})
        created.raise_for_status()
        campaign_id = created.json()["keitaro_id"]
        streams = http.get(f"/api/campaigns/{campaign_id}").json()["streams"]
        stream_id = next(s["id"] for s in streams if s["editable"])

        statuses: list[int] = []

        def add(offer_id: int) -> None:
            with httpx.Client(base_url=base, timeout=30) as own:
                statuses.append(own.post(f"/api/streams/{stream_id}/offers", json={"offer_id": offer_id}).status_code)

        threads = [threading.Thread(target=add, args=(o,)) for o in rest]
        [t.start() for t in threads]
        [t.join() for t in threads]

        streams = http.get(f"/api/campaigns/{campaign_id}").json()["streams"]
        offers = next(s for s in streams if s["editable"])["offers"]
        history = http.get(f"/api/campaigns/{campaign_id}/history").json()

    if sorted(statuses) != [200] * len(rest):
        problems.append(f"статусы ответов: {sorted(statuses)}")
    if sorted(o["offer_id"] for o in offers) != sorted(offer_ids):
        problems.append(f"потеряны офферы: есть {sorted(o['offer_id'] for o in offers)}, ждали {sorted(offer_ids)}")
    if sum(o["share"] for o in offers) != 100:
        problems.append(f"сумма долей {sum(o['share'] for o in offers)}, ждали 100")
    if len(history) != len(rest):
        problems.append(f"в истории {len(history)} записей, ждали {len(rest)}")
    print(f"прогон {number}: кампания {campaign_id}, офферов {len(offers)}, "
          f"доли {[o['share'] for o in offers]}, история {len(history)} -> {'OK' if not problems else 'FAIL'}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8077")
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    failed = False
    for number in range(1, args.repeat + 1):
        for problem in run_once(args.base, number):
            failed = True
            print("   ", problem)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
