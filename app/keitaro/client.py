"""Тонкий клиент Keitaro Admin API v1 (заголовок Api-Key)."""

import logging
import time
from typing import Any, Callable

import httpx

from app.logs import log

# PUT задаёт состояние целиком, GET и DELETE ничего не добавляют: повтор безопасен.
# POST создаёт сущность: повтор после неясного исхода дал бы дубль.
IDEMPOTENT = {"GET", "PUT", "DELETE"}
RETRY_STATUSES = {429, 502, 503, 504}
# Запрос до сервера не дошёл: ничего создано быть не могло, повторять можно любой метод.
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class KeitaroError(Exception):
    """Ошибка обращения к Keitaro.

    `unknown=True`: ответа нет или он ненадёжен, поэтому неизвестно, выполнил ли
    Keitaro запрос. Это не то же самое, что явный отказ.
    """

    def __init__(self, status: int, message: str, unknown: bool = False):
        super().__init__(message)
        self.status = status
        self.message = message
        self.unknown = unknown


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None, *, connect_timeout: float = 5.0,
                 retries: int = 3, backoff: float = 0.5,
                 sleep: Callable[[float], None] = time.sleep):
        root = base_url.rstrip("/")
        if root.endswith("/admin_api/v1"):
            root = root[: -len("/admin_api/v1")]
        self._http = httpx.Client(
            base_url=f"{root}/admin_api/v1",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )
        self._retries = max(0, retries)
        self._backoff = backoff
        self._sleep = sleep

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None and response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), 10.0)
        return self._backoff * 2 ** (attempt - 1)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        attempts = 1 + self._retries
        started = time.perf_counter()
        for attempt in range(1, attempts + 1):
            last = attempt == attempts
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as error:
                retryable = not isinstance(error, httpx.UnsupportedProtocol) and (
                    isinstance(error, NOT_SENT) or method in IDEMPOTENT)
                reason = type(error).__name__
                if retryable and not last:
                    delay = self._delay(attempt)
                    log(logging.WARNING, "keitaro_retry", method=method, path=path, attempt=attempt,
                        of=attempts, reason=reason, delay_s=delay)
                    self._sleep(delay)
                    continue
                unknown = not isinstance(error, NOT_SENT)
                log(logging.ERROR, "keitaro_failed", method=method, path=path, attempts=attempt,
                    reason=reason, unknown=unknown,
                    latency_ms=round((time.perf_counter() - started) * 1000))
                text = ("Ответа нет, результат неизвестен" if unknown else "Keitaro недоступен")
                raise KeitaroError(502, f"{text}: {reason} {error}".strip(), unknown=unknown) from error

            status = response.status_code
            if status in RETRY_STATUSES and not last and (method in IDEMPOTENT or status == 429):
                delay = self._delay(attempt, response)
                log(logging.WARNING, "keitaro_retry", method=method, path=path, attempt=attempt,
                    of=attempts, reason=f"http_{status}", delay_s=delay)
                self._sleep(delay)
                continue
            if method == "DELETE" and status == 404 and attempt > 1:
                # Прошлая попытка могла дойти до сервера, хотя ответ потерялся.
                log(logging.INFO, "keitaro_delete_already_done", path=path, attempt=attempt)
                return None
            latency = round((time.perf_counter() - started) * 1000)
            if status >= 400:
                unknown = method == "POST" and status >= 500
                log(logging.ERROR if status >= 500 else logging.WARNING, "keitaro_failed",
                    method=method, path=path, status=status, attempts=attempt, unknown=unknown,
                    latency_ms=latency)
                raise KeitaroError(status, self._error_text(response), unknown=unknown)
            log(logging.INFO, "keitaro_request", method=method, path=path, status=status,
                attempts=attempt, latency_ms=latency)
            if not response.content:
                return None
            return response.json()

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return f"Keitaro HTTP {response.status_code}: {response.text[:300]}"
        if isinstance(data, dict):
            return str(data.get("error") or data.get("message") or data)
        return str(data)

    # Справочники
    def list_domains(self) -> list[dict]:
        return self._request("GET", "/domains")

    def list_groups(self) -> list[dict]:
        return self._request("GET", "/groups", params={"type": "campaigns"})

    def create_group(self, name: str) -> dict:
        return self._request("POST", "/groups", json={"name": name, "type": "campaigns"})

    def list_traffic_sources(self) -> list[dict]:
        return self._request("GET", "/traffic_sources")

    def create_traffic_source(self, name: str) -> dict:
        return self._request("POST", "/traffic_sources", json={"name": name})

    def list_offers(self) -> list[dict]:
        return self._request("GET", "/offers")

    # Кампании
    def list_campaigns(self) -> list[dict]:
        return self._request("GET", "/campaigns")

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    # Потоки
    def list_streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def get_stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}")

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)
