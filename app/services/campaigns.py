"""Создание кампании: кампания + поток по гео на safe-URL + поток с оффером."""

import logging
import re
import secrets
import string

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro.client import KeitaroError
from app.logs import log
from app.models import CreatedCampaign


class ValidationError(Exception):
    pass


class StorageError(Exception):
    """Не удалось записать в базу сервиса."""


GEO_RE = re.compile(r"^[A-Z]{2}$")


def parse_geo(raw: str) -> list[str]:
    """'mx, au;RO' -> ['MX', 'AU', 'RO'] (ISO 3166-1 alpha-2, без дублей)."""
    codes: list[str] = []
    for part in re.split(r"[\s,;]+", raw.strip().upper()):
        if not part:
            continue
        if not GEO_RE.match(part):
            raise ValidationError(f"Неверный код страны: {part!r}. Нужны двухбуквенные коды, например MX,AU")
        if part not in codes:
            codes.append(part)
    if not codes:
        raise ValidationError("Укажите хотя бы одну страну")
    return codes


def _alias() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _find_or_create(items: list[dict], name: str, create) -> int:
    for item in items:
        if item.get("name", "").strip().lower() == name.strip().lower():
            return item["id"]
    return create(name)["id"]


def _find_by_alias(client, alias: str) -> dict | None:
    """Исход POST /campaigns неизвестен: смотрим, появилась ли кампания с нашим случайным alias."""
    try:
        for campaign in client.list_campaigns():
            if campaign.get("alias") == alias:
                return campaign
    except KeitaroError as error:
        log(logging.ERROR, "campaign_lookup_failed", alias=alias, error=error.message)
    return None


def _remove_campaign(client, campaign_id: int, alias: str, reason: str) -> bool:
    """Компенация: убрать кампанию из Keitaro. Сбой удаления не теряем молча — пишем в лог."""
    try:
        client.delete_campaign(campaign_id)
    except KeitaroError as error:
        log(logging.ERROR, "campaign_orphaned", campaign_id=campaign_id, alias=alias, reason=reason,
            error=error.message)
        return False
    log(logging.WARNING, "campaign_rolled_back", campaign_id=campaign_id, alias=alias, reason=reason)
    return True


def resolve_domain(client, settings: Settings, domain_id: int | None) -> dict:
    domains = client.list_domains()
    if domain_id is not None:
        for domain in domains:
            if domain["id"] == domain_id:
                return domain
        raise ValidationError(f"Домен {domain_id} не найден в Keitaro")
    if settings.default_domain:
        for domain in domains:
            if domain["name"].strip("/").lower() == settings.default_domain.strip("/").lower():
                return domain
    if not domains:
        raise ValidationError("В Keitaro нет ни одного домена")
    return domains[0]


def campaign_url(domain_name: str, alias: str) -> str:
    host = domain_name.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return f"{host}/{alias}"


def create_campaign(client, db: Session, settings: Settings, *, name: str, geo: str,
                    offer_id: int, domain_id: int | None = None,
                    group_id: int | None = None, source_id: int | None = None) -> CreatedCampaign:
    name = name.strip()
    if not name:
        raise ValidationError("Название кампании не может быть пустым")
    countries = parse_geo(geo)

    if offer_id not in {o["id"] for o in client.list_offers()}:
        raise ValidationError(f"Оффер {offer_id} не найден в Keitaro")

    domain = resolve_domain(client, settings, domain_id)
    if group_id is None:
        group_id = _find_or_create(client.list_groups(), settings.default_group_name, client.create_group)
    if source_id is None:
        source_id = _find_or_create(client.list_traffic_sources(), settings.default_source_name,
                                    client.create_traffic_source)

    alias = _alias()
    try:
        campaign = client.create_campaign({
            "name": name,
            "alias": alias,
            "type": "position",          # ротация потоков по позиции
            "state": "active",
            "domain_id": domain["id"],
            "group_id": group_id,
            "traffic_source_id": source_id,
            "cost_type": "CPC",
            "cost_auto": True,
        })
    except KeitaroError as error:
        if not error.unknown:
            raise
        # Ответа нет: кампания могла создаться. Повторять POST нельзя (будет дубль),
        # поэтому ищем по alias: если нашлась, продолжаем с ней.
        campaign = _find_by_alias(client, alias)
        if campaign is None:
            log(logging.ERROR, "campaign_create_failed", alias=alias, error=error.message)
            raise
        log(logging.WARNING, "campaign_recovered", campaign_id=campaign["id"], alias=alias)
    campaign_id = campaign["id"]
    alias = campaign.get("alias") or alias

    try:
        geo_stream = client.create_stream({
            "campaign_id": campaign_id,
            "name": f"Geo {','.join(countries)} -> safe",
            "type": "regular",
            "position": 1,
            "weight": 100,
            "state": "active",
            "schema": "redirect",
            "action_type": "http",
            "action_payload": settings.safe_redirect_url,
            "filters": [{"name": "country", "mode": "accept", "payload": countries}],
        })
        offers_stream = client.create_stream({
            "campaign_id": campaign_id,
            "name": "Offers",
            "type": "regular",
            "position": 2,
            "weight": 100,
            "state": "active",
            "schema": "landings",
            "action_type": "http",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        })
    except KeitaroError:
        # Без потоков кампания бесполезна: убираем её, чтобы не оставлять мусор в трекере.
        _remove_campaign(client, campaign_id, alias, "stream_failed")
        raise

    record = CreatedCampaign(
        keitaro_id=campaign_id, name=name, alias=alias, geo=countries, offer_id=offer_id,
        domain_id=domain["id"], group_id=group_id, source_id=source_id,
        geo_stream_id=geo_stream["id"], offers_stream_id=offers_stream["id"],
        url=campaign_url(domain["name"], alias),
    )
    try:
        db.add(record)
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        log(logging.ERROR, "campaign_record_failed", campaign_id=campaign_id, alias=alias,
            error=type(error).__name__)
        # Кампания уже живёт в Keitaro, а о ней нет записи: убираем, чтобы состояния не разошлись.
        if _remove_campaign(client, campaign_id, alias, "db_failure"):
            if isinstance(error, IntegrityError):
                hint = (f"В базе уже есть кампания с ID {campaign_id} (остаток от прошлого запуска "
                        "эмулятора?). Очистите таблицы или используйте чистую базу")
            else:
                hint = "Повторите позже"
            raise StorageError(f"Не удалось записать кампанию в базу ({type(error).__name__}). "
                               f"В Keitaro ничего не осталось. {hint}") from error
        raise StorageError(f"Не удалось записать кампанию в базу ({type(error).__name__}), "
                           f"и удалить её из Keitaro не удалось. Удалите кампанию {campaign_id} вручную") from error
    log(logging.INFO, "campaign_created", campaign_id=campaign_id, alias=alias, offer_id=offer_id,
        geo=countries)
    return record
