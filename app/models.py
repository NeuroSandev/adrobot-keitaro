from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CreatedCampaign(Base):
    """Кампании, созданные через этот сервис (источник правды остаётся Keitaro)."""

    __tablename__ = "created_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(64))
    geo: Mapped[list[str]] = mapped_column(JSON)
    offer_id: Mapped[int] = mapped_column(Integer)
    domain_id: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(Integer)
    geo_stream_id: Mapped[int] = mapped_column(Integer)
    offers_stream_id: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OfferChange(Base):
    """Журнал правок офферов в потоках: что было и что стало."""

    __tablename__ = "offer_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # add | remove | set
    offer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before: Mapped[list[dict]] = mapped_column(JSON)
    after: Mapped[list[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
