from functools import lru_cache

from app.config import get_settings
from app.keitaro.client import KeitaroClient, KeitaroError
from app.keitaro.fake import FakeKeitaro


@lru_cache
def get_keitaro():
    """Один клиент на процесс. В тестах подменяется через dependency_overrides."""
    settings = get_settings()
    if settings.keitaro_fake:
        return FakeKeitaro()
    if not settings.keitaro_url or not settings.keitaro_api_key:
        raise KeitaroError(500, "Не заданы KEITARO_URL и KEITARO_API_KEY (или включите KEITARO_FAKE=1)")
    return KeitaroClient(settings.keitaro_url, settings.keitaro_api_key,
                         timeout=settings.keitaro_timeout,
                         connect_timeout=settings.keitaro_connect_timeout,
                         retries=settings.keitaro_retries, backoff=settings.keitaro_backoff)
