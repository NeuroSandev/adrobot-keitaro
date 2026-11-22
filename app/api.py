from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.keitaro.deps import get_keitaro
from app.models import CreatedCampaign
from app.schemas import (CampaignCreate, CampaignCreated, OfferAdd, OfferChangeOut,
                         SharesSet)
from app.services import campaigns, editor

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta(client=Depends(get_keitaro), settings: Settings = Depends(get_settings)):
    """Справочники для формы создания и значения по умолчанию."""
    return {
        "domains": client.list_domains(),
        "groups": client.list_groups(),
        "sources": client.list_traffic_sources(),
        "defaults": {
            "domain": settings.default_domain,
            "group": settings.default_group_name,
            "source": settings.default_source_name,
            "safe_url": settings.safe_redirect_url,
        },
        "fake": settings.keitaro_fake,
    }


@router.get("/offers")
def offers(q: str = "", limit: int = Query(20, ge=1, le=200), client=Depends(get_keitaro)):
    """Поиск офферов для автокомплита: по ID или подстроке названия."""
    needle = q.strip().lower()
    result = []
    for offer in client.list_offers():
        if not needle or needle in offer["name"].lower() or needle == str(offer["id"]):
            result.append({"id": offer["id"], "name": offer["name"]})
        if len(result) >= limit:
            break
    return result


@router.post("/campaigns", response_model=CampaignCreated, status_code=201)
def create_campaign(body: CampaignCreate, client=Depends(get_keitaro),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return campaigns.create_campaign(client, db, settings, **body.model_dump())


@router.get("/campaigns")
def list_campaigns(client=Depends(get_keitaro), db: Session = Depends(get_db)):
    ours = set(db.scalars(select(CreatedCampaign.keitaro_id)))
    items = [{"id": c["id"], "name": c.get("name"), "alias": c.get("alias"),
              "state": c.get("state"), "created_here": c["id"] in ours}
             for c in client.list_campaigns()]
    return sorted(items, key=lambda c: c["id"], reverse=True)


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, client=Depends(get_keitaro)):
    return editor.campaign_view(client, campaign_id)


@router.get("/campaigns/{campaign_id}/history", response_model=list[OfferChangeOut])
def campaign_history(campaign_id: int, db: Session = Depends(get_db)):
    return editor.history(db, campaign_id)


def _stream_out(client, stream: dict) -> dict:
    return editor.describe_stream(stream, editor.offer_names(client))


@router.post("/streams/{stream_id}/offers")
def add_offer(stream_id: int, body: OfferAdd, client=Depends(get_keitaro),
              db: Session = Depends(get_db)):
    return _stream_out(client, editor.add_offer(client, db, stream_id, body.offer_id, body.mode))


@router.delete("/streams/{stream_id}/offers/{offer_id}")
def remove_offer(stream_id: int, offer_id: int,
                 mode: Literal["even", "proportional"] = "even",
                 client=Depends(get_keitaro), db: Session = Depends(get_db)):
    return _stream_out(client, editor.remove_offer(client, db, stream_id, offer_id, mode))


@router.put("/streams/{stream_id}/offers")
def set_shares(stream_id: int, body: SharesSet, client=Depends(get_keitaro),
               db: Session = Depends(get_db)):
    items = [item.model_dump() for item in body.offers]
    return _stream_out(client, editor.set_shares(client, db, stream_id, items))
