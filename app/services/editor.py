"""Редактор офферов в потоках кампании.

Правка — «прочитал поток, посчитал, записал целиком». Две параллельные правки одного потока без
координации прочитали бы одно и то же состояние, и вторая запись стёрла бы первую (оффер
потерян). Поэтому чтение и запись идут под блокировкой потока. Блокировка узкая: только
на один поток, и проверки, не требующие состояния потока, делаются до неё.
"""

import logging
import threading
from contextlib import contextmanager

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.keitaro.client import KeitaroError
from app.logs import log
from app.models import OfferChange
from app.services import shares
from app.services.campaigns import ValidationError

_STRIPES = [threading.Lock() for _ in range(64)]
ADVISORY_NAMESPACE = 7001


class NotFound(Exception):
    pass


@contextmanager
def stream_lock(db: Session, stream_id: int):
    """Одна правка потока за раз.

    Внутри процесса — мьютекс, между процессами — advisory-блокировка PostgreSQL. Она
    транзакционная: снимается сама на commit/rollback, забыть освободить её нельзя.
    """
    with _STRIPES[stream_id % len(_STRIPES)]:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                       {"ns": ADVISORY_NAMESPACE, "key": stream_id})
        try:
            yield
        finally:
            db.rollback()


def offer_names(client) -> dict[int, str]:
    return {o["id"]: o["name"] for o in client.list_offers()}


def _plain(offers: list[dict]) -> list[dict]:
    """Только то, что отправляем в Keitaro (без внутренних id записей)."""
    return [{"offer_id": o["offer_id"], "share": int(o["share"]), "state": o.get("state", "active")}
            for o in offers]


def is_offer_stream(stream: dict) -> bool:
    return stream.get("schema") == "landings" or bool(stream.get("offers"))


def describe_stream(stream: dict, names: dict[int, str]) -> dict:
    offers = [
        {"offer_id": o["offer_id"], "name": names.get(o["offer_id"], f"#{o['offer_id']}"),
         "share": int(o["share"]), "state": o.get("state", "active")}
        for o in stream.get("offers") or []
    ]
    return {
        "id": stream["id"],
        "name": stream.get("name") or f"Поток {stream['id']}",
        "position": stream.get("position"),
        "schema": stream.get("schema"),
        "action_payload": stream.get("action_payload"),
        "filters": stream.get("filters") or [],
        "editable": is_offer_stream(stream),
        "offers": offers,
        "total_share": sum(o["share"] for o in offers),
    }


def campaign_view(client, campaign_id: int) -> dict:
    campaign = client.get_campaign(campaign_id)
    names = offer_names(client)
    streams = sorted(client.list_streams(campaign_id), key=lambda s: s.get("position") or 0)
    return {
        "id": campaign["id"],
        "name": campaign.get("name"),
        "alias": campaign.get("alias"),
        "state": campaign.get("state"),
        "streams": [describe_stream(s, names) for s in streams],
    }


def _load_offer_stream(client, stream_id: int) -> dict:
    stream = client.get_stream(stream_id)
    if not is_offer_stream(stream):
        raise ValidationError("В этом потоке нет офферов: он редиректит на URL")
    return stream


def _signature(offers: list[dict]) -> list[tuple[int, int]]:
    return sorted((int(o["offer_id"]), int(o["share"])) for o in offers)


def _confirmed_offers(client, stream_id: int, updated: dict) -> list[dict]:
    """Что Keitaro реально сохранил: из ответа PUT, а если в нём нет офферов — повторным чтением."""
    if updated and "offers" in updated:
        return updated["offers"] or []
    return client.get_stream(stream_id).get("offers") or []


def _save(client, db: Session, stream: dict, new_offers: list[dict], action: str,
          offer_id: int | None) -> dict:
    stream_id = stream["id"]
    before = _plain(stream.get("offers") or [])
    sent = _plain(new_offers)
    # PUT задаёт набор целиком, поэтому клиент безопасно повторяет его при сетевом сбое.
    updated = client.update_stream(stream_id, {"offers": sent})
    saved = _confirmed_offers(client, stream_id, updated)
    if _signature(saved) != _signature(sent):
        log(logging.ERROR, "offers_mismatch", stream_id=stream_id, action=action,
            sent=_signature(sent), saved=_signature(saved))
        raise KeitaroError(502, "Keitaro сохранил не тот набор офферов, проверьте поток в трекере",
                           unknown=True)
    after = _plain(saved)
    log(logging.INFO, "offers_changed", stream_id=stream_id, campaign_id=stream["campaign_id"],
        action=action, offer_id=offer_id, before=before, after=after)
    # Изменение уже в Keitaro. Сбой журнала не должен выдаваться за неудачу правки:
    # данные остаются в логе (offers_changed выше + history_write_failed).
    try:
        db.add(OfferChange(campaign_id=stream["campaign_id"], stream_id=stream_id, action=action,
                           offer_id=offer_id, before=before, after=after))
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        log(logging.ERROR, "history_write_failed", stream_id=stream_id, action=action,
            error=type(error).__name__)
    return updated


def add_offer(client, db: Session, stream_id: int, offer_id: int,
              mode: shares.Mode = "even") -> dict:
    if offer_id not in offer_names(client):
        raise ValidationError(f"Оффер {offer_id} не найден в Keitaro")
    with stream_lock(db, stream_id):
        stream = _load_offer_stream(client, stream_id)
        current = _plain(stream.get("offers") or [])
        if any(o["offer_id"] == offer_id for o in current):
            raise ValidationError("Этот оффер уже есть в потоке")
        new_shares = shares.after_add([o["share"] for o in current], mode)
        current.append({"offer_id": offer_id, "share": 0, "state": "active"})
        for offer, share in zip(current, new_shares):
            offer["share"] = share
        return _save(client, db, stream, current, "add", offer_id)


def remove_offer(client, db: Session, stream_id: int, offer_id: int,
                 mode: shares.Mode = "even") -> dict:
    with stream_lock(db, stream_id):
        stream = _load_offer_stream(client, stream_id)
        current = _plain(stream.get("offers") or [])
        remaining = [o for o in current if o["offer_id"] != offer_id]
        if len(remaining) == len(current):
            raise NotFound("Оффера нет в этом потоке")
        if not remaining:
            raise ValidationError("Нельзя удалить последний оффер: поток останется пустым")
        for offer, share in zip(remaining, shares.after_remove([o["share"] for o in remaining], mode)):
            offer["share"] = share
        return _save(client, db, stream, remaining, "remove", offer_id)


def set_shares(client, db: Session, stream_id: int, items: list[dict]) -> dict:
    """Ручные доли: тот же набор офферов, целые числа 0..100, сумма ровно 100."""
    requested = {item["offer_id"]: int(item["share"]) for item in items}
    if len(requested) != len(items):
        raise ValidationError("Оффер указан несколько раз")
    if any(s < 0 or s > 100 for s in requested.values()):
        raise ValidationError("Доля должна быть от 0 до 100")
    if sum(requested.values()) != shares.TOTAL:
        raise ValidationError(f"Сумма долей должна быть 100, сейчас {sum(requested.values())}")
    with stream_lock(db, stream_id):
        stream = _load_offer_stream(client, stream_id)
        current = {o["offer_id"]: o for o in _plain(stream.get("offers") or [])}
        if set(requested) != set(current):
            raise ValidationError("Набор офферов не совпадает с потоком; добавляйте и удаляйте отдельно")
        new_offers = [{**current[oid], "share": requested[oid]} for oid in current]
        return _save(client, db, stream, new_offers, "set", None)


def history(db: Session, campaign_id: int, limit: int = 50) -> list[OfferChange]:
    query = (select(OfferChange).where(OfferChange.campaign_id == campaign_id)
             .order_by(OfferChange.id.desc()).limit(limit))
    return list(db.scalars(query))
