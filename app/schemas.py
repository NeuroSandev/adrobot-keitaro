from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(min_length=2, description="Коды стран через запятую: MX,AU,RO")
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None


class CampaignCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    keitaro_id: int
    name: str
    alias: str
    geo: list[str]
    offer_id: int
    domain_id: int
    group_id: int
    source_id: int
    geo_stream_id: int
    offers_stream_id: int
    url: str
    created_at: datetime


class OfferAdd(BaseModel):
    offer_id: int
    mode: Literal["even", "proportional"] = "even"


class ShareItem(BaseModel):
    offer_id: int
    share: int


class SharesSet(BaseModel):
    offers: list[ShareItem] = Field(min_length=1)


class OfferChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    action: str
    offer_id: int | None
    before: list[dict]
    after: list[dict]
    created_at: datetime
