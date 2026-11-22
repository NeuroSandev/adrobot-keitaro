"""Тонкий клиент Keitaro Admin API v1 (заголовок Api-Key)."""

from typing import Any

import httpx


class KeitaroError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None):
        root = base_url.rstrip("/")
        if root.endswith("/admin_api/v1"):
            root = root[: -len("/admin_api/v1")]
        self._http = httpx.Client(
            base_url=f"{root}/admin_api/v1",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise KeitaroError(502, f"Keitaro недоступен: {error}") from error
        if response.status_code >= 400:
            raise KeitaroError(response.status_code, self._error_text(response))
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
