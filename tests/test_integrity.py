"""Целостность: что остаётся в Keitaro и в базе при сбоях. Оффер не должен теряться."""

import threading
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.keitaro.client import KeitaroError
from app.keitaro.fake import FakeKeitaro
from app.services import editor


def create(client, **overrides):
    body = {"name": "test_ivanov_1", "geo": "au", "offer_id": 3749, **overrides}
    return client.post("/api/campaigns", json=body)


def offers_stream(client, campaign_id):
    streams = client.get(f"/api/campaigns/{campaign_id}").json()["streams"]
    return next(s for s in streams if s["editable"])


# ---- создание кампании -----------------------------------------------------

def test_db_failure_rolls_back_campaign_in_keitaro(client, fake, monkeypatch):
    from sqlalchemy.orm import Session

    def broken_commit(self):
        raise OperationalError("INSERT", {}, Exception("db is down"))
    monkeypatch.setattr(Session, "commit", broken_commit)

    response = create(client)
    assert response.status_code == 503
    assert "ничего не осталось" in response.json()["detail"]
    assert fake.campaigns == {} and fake.streams == {}


def test_db_failure_and_failed_rollback_tells_which_campaign_to_delete(client, fake, monkeypatch):
    from sqlalchemy.orm import Session

    def broken_commit(self):
        raise OperationalError("INSERT", {}, Exception("db is down"))

    def broken_delete(campaign_id):
        raise KeitaroError(502, "down")
    monkeypatch.setattr(Session, "commit", broken_commit)
    monkeypatch.setattr(fake, "delete_campaign", broken_delete)

    response = create(client)
    assert response.status_code == 503
    assert "вручную" in response.json()["detail"]
    assert len(fake.campaigns) == 1


def test_unknown_outcome_with_created_campaign_is_adopted_not_duplicated(client, fake, monkeypatch):
    """Keitaro создал кампанию, но ответ потерялся: продолжаем с ней, дубля нет."""
    real = fake.create_campaign

    def lost_response(payload):
        real(payload)
        raise KeitaroError(502, "Ответа нет", unknown=True)
    monkeypatch.setattr(fake, "create_campaign", lost_response)

    response = create(client)
    assert response.status_code == 201, response.text
    assert len(fake.campaigns) == 1
    assert len(fake.list_streams(response.json()["keitaro_id"])) == 2


def test_unknown_outcome_without_campaign_is_an_error_and_leaves_nothing(client, fake, monkeypatch):
    def lost_request(payload):
        raise KeitaroError(502, "Ответа нет", unknown=True)
    monkeypatch.setattr(fake, "create_campaign", lost_request)

    response = create(client)
    assert response.status_code == 502
    assert fake.campaigns == {}


# ---- редактор --------------------------------------------------------------

def test_history_failure_does_not_fail_an_applied_change(client, fake, monkeypatch):
    campaign_id = create(client).json()["keitaro_id"]
    stream = offers_stream(client, campaign_id)

    from sqlalchemy.orm import Session
    real_commit = Session.commit

    def broken_commit(self):
        raise OperationalError("INSERT", {}, Exception("db is down"))
    monkeypatch.setattr(Session, "commit", broken_commit)
    response = client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 3717})
    monkeypatch.setattr(Session, "commit", real_commit)

    assert response.status_code == 200, response.text
    saved = [(o["offer_id"], o["share"]) for o in fake.get_stream(stream["id"])["offers"]]
    assert saved == [(3749, 50), (3717, 50)]


def test_keitaro_saving_a_different_set_is_reported(client, fake, monkeypatch):
    campaign_id = create(client).json()["keitaro_id"]
    stream = offers_stream(client, campaign_id)
    real = fake.update_stream

    def drops_offer(stream_id, payload):
        result = real(stream_id, payload)
        result["offers"] = result["offers"][:1]
        return result
    monkeypatch.setattr(fake, "update_stream", drops_offer)

    response = client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 3717})
    assert response.status_code == 502
    assert "не тот набор" in response.json()["detail"]


def test_failed_update_leaves_stream_untouched_and_history_empty(client, fake, monkeypatch):
    campaign_id = create(client).json()["keitaro_id"]
    stream = offers_stream(client, campaign_id)

    def broken(stream_id, payload):
        raise KeitaroError(502, "down", unknown=True)
    monkeypatch.setattr(fake, "update_stream", broken)

    assert client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 3717}).status_code == 502
    assert [(o["offer_id"], o["share"]) for o in fake.get_stream(stream["id"])["offers"]] == [(3749, 100)]
    assert client.get(f"/api/campaigns/{campaign_id}/history").json() == []


def test_repeating_an_applied_add_is_rejected_not_doubled(client):
    """Ответ на добавление потерялся, пользователь повторяет: оффер не задваивается."""
    campaign_id = create(client).json()["keitaro_id"]
    stream = offers_stream(client, campaign_id)
    assert client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 3717}).status_code == 200
    again = client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 3717})
    assert again.status_code == 400 and "уже есть" in again.json()["detail"]
    assert [o["offer_id"] for o in offers_stream(client, campaign_id)["offers"]] == [3749, 3717]


# ---- гонка: параллельные правки одного потока ------------------------------

def _race(tmp_path, use_lock=True, monkeypatch=None):
    fake = FakeKeitaro()
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    campaign = fake.create_campaign({"name": "race"})
    stream = fake.create_stream({"campaign_id": campaign["id"], "name": "Offers", "schema": "landings",
                                 "offers": [{"offer_id": 3749, "share": 100}]})
    # Чтение медленное: окно между «прочитал» и «записал» становится широким.
    real_get = fake.get_stream

    def slow_get(stream_id):
        result = real_get(stream_id)
        time.sleep(0.03)
        return result
    fake.get_stream = slow_get

    to_add = [3717, 3801, 3802, 3910, 3911, 4002]
    errors = []

    def worker(offer_id):
        session = Session()
        try:
            editor.add_offer(fake, session, stream["id"], offer_id)
        except Exception as error:      # noqa: BLE001
            errors.append(error)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(o,)) for o in to_add]
    [t.start() for t in threads]
    [t.join() for t in threads]
    final = real_get(stream["id"])["offers"]
    return errors, final


def test_parallel_adds_do_not_lose_offers(tmp_path):
    errors, final = _race(tmp_path)
    assert errors == []
    assert sorted(o["offer_id"] for o in final) == [3717, 3749, 3801, 3802, 3910, 3911, 4002]
    assert sum(o["share"] for o in final) == 100


def test_the_race_test_is_meaningful_without_the_lock(tmp_path, monkeypatch):
    """Без блокировки тот же сценарий теряет офферы: значит, тест что-то проверяет."""
    from contextlib import nullcontext
    monkeypatch.setattr(editor, "stream_lock", lambda db, stream_id: nullcontext())
    errors, final = _race(tmp_path)
    assert len(final) < 7 or errors
