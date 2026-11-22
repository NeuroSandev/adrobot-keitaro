"""Создание кампании: кампания + поток по гео на safe-URL + поток с оффером."""

import re
import secrets
import string

from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro.client import KeitaroError
from app.models import CreatedCampaign


class ValidationError(Exception):
    pass


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
        try:
            client.delete_campaign(campaign_id)
        except KeitaroError:
            pass
        raise

    record = CreatedCampaign(
        keitaro_id=campaign_id, name=name, alias=alias, geo=countries, offer_id=offer_id,
        domain_id=domain["id"], group_id=group_id, source_id=source_id,
        geo_stream_id=geo_stream["id"], offers_stream_id=offers_stream["id"],
        url=campaign_url(domain["name"], alias),
    )
    db.add(record)
    db.commit()
    return record
