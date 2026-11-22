"""Проверяем, что настоящий клиент шлёт правильные запросы в Keitaro Admin API."""

import json

import httpx
import pytest

from app.keitaro.client import KeitaroClient, KeitaroError


def make(handler):
    return KeitaroClient("https://tracker.example.com/admin_api/v1/", "secret",
                         transport=httpx.MockTransport(handler))


def test_auth_header_base_url_and_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["key"] = request.headers["Api-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 7, "offers": []})

    make(handler).update_stream(7, {"offers": [{"offer_id": 1, "share": 100, "state": "active"}]})
    assert seen == {
        "method": "PUT",
        "url": "https://tracker.example.com/admin_api/v1/streams/7",
        "key": "secret",
        "body": {"offers": [{"offer_id": 1, "share": 100, "state": "active"}]},
    }


def test_groups_are_filtered_by_campaign_type():
    def handler(request):
        assert request.url.path == "/admin_api/v1/groups"
        assert request.url.params["type"] == "campaigns"
        return httpx.Response(200, json=[])
    assert make(handler).list_groups() == []


def test_errors_are_wrapped():
    client = make(lambda r: httpx.Response(422, json={"error": "Name is empty"}))
    with pytest.raises(KeitaroError) as info:
        client.create_campaign({})
    assert info.value.status == 422 and info.value.message == "Name is empty"


def test_network_error_is_502():
    def handler(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(KeitaroError) as info:
        make(handler).list_offers()
    assert info.value.status == 502


def test_empty_body_on_delete():
    assert make(lambda r: httpx.Response(204)).delete_campaign(5) is None
