"""Надёжность клиента: что повторяем, что нет, и когда исход считается неизвестным."""

import logging

import httpx
import pytest

from app.keitaro.client import KeitaroClient, KeitaroError


def make(handler, retries=3):
    pauses = []
    client = KeitaroClient("https://tracker.example.com", "secret", retries=retries, backoff=0.5,
                           transport=httpx.MockTransport(handler), sleep=pauses.append)
    return client, pauses


def flaky(failures, error, ok=None):
    """Первые `failures` вызовов падают, дальше отвечают 200."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= failures:
            if isinstance(error, int):
                return httpx.Response(error, json={"error": "busy"})
            raise error
        return httpx.Response(200, json=ok if ok is not None else [])
    return handler, calls


def test_get_is_retried_with_backoff_and_succeeds():
    handler, calls = flaky(2, httpx.ConnectError("refused"))
    client, pauses = make(handler)
    assert client.list_offers() == []
    assert calls["n"] == 3
    assert pauses == [0.5, 1.0]


def test_get_gives_up_after_all_retries():
    handler, calls = flaky(99, 503)
    client, pauses = make(handler)
    with pytest.raises(KeitaroError) as info:
        client.list_offers()
    assert calls["n"] == 4 and pauses == [0.5, 1.0, 2.0]
    assert info.value.status == 503 and info.value.unknown is False


def test_client_errors_are_not_retried():
    handler, calls = flaky(99, 422)
    client, pauses = make(handler)
    with pytest.raises(KeitaroError):
        client.list_offers()
    assert calls["n"] == 1 and pauses == []


def test_put_is_retried_after_read_timeout():
    """PUT задаёт состояние целиком, повтор безопасен."""
    handler, calls = flaky(1, httpx.ReadTimeout("slow"), ok={"id": 7, "offers": []})
    client, _ = make(handler)
    assert client.update_stream(7, {"offers": []})["id"] == 7
    assert calls["n"] == 2


def test_post_is_not_retried_after_read_timeout_and_outcome_is_unknown():
    """Ответа нет — запрос мог выполниться. Повтор создал бы дубль."""
    handler, calls = flaky(99, httpx.ReadTimeout("slow"))
    client, pauses = make(handler)
    with pytest.raises(KeitaroError) as info:
        client.create_campaign({"name": "x"})
    assert calls["n"] == 1 and pauses == []
    assert info.value.unknown is True


def test_post_is_retried_when_request_never_reached_server():
    handler, calls = flaky(2, httpx.ConnectError("refused"), ok={"id": 1})
    client, _ = make(handler)
    assert client.create_campaign({"name": "x"}) == {"id": 1}
    assert calls["n"] == 3


def test_post_connect_failure_is_a_clear_error_not_unknown():
    handler, _ = flaky(99, httpx.ConnectError("refused"))
    client, _ = make(handler)
    with pytest.raises(KeitaroError) as info:
        client.create_campaign({"name": "x"})
    assert info.value.status == 502 and info.value.unknown is False


def test_post_5xx_is_unknown_and_not_retried():
    handler, calls = flaky(99, 502)
    client, _ = make(handler)
    with pytest.raises(KeitaroError) as info:
        client.create_campaign({"name": "x"})
    assert calls["n"] == 1 and info.value.unknown is True


def test_post_429_is_retried_and_respects_retry_after():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "slow down"})
        return httpx.Response(200, json={"id": 5})
    client, pauses = make(handler)
    assert client.create_campaign({"name": "x"}) == {"id": 5}
    assert pauses == [3.0]


def test_delete_404_after_retry_counts_as_done():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")      # ответ потерялся, но удаление дошло
        return httpx.Response(404, json={"error": "not found"})
    client, _ = make(handler)
    assert client.delete_campaign(5) is None


def test_delete_404_on_first_try_is_an_error():
    client, _ = make(lambda r: httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(KeitaroError) as info:
        client.delete_campaign(5)
    assert info.value.status == 404


def test_retries_can_be_disabled():
    handler, calls = flaky(99, httpx.ConnectError("refused"))
    client, _ = make(handler, retries=0)
    with pytest.raises(KeitaroError):
        client.list_offers()
    assert calls["n"] == 1


def test_retry_is_logged_without_secrets(caplog):
    handler, _ = flaky(1, 503)
    client, _ = make(handler)
    with caplog.at_level(logging.INFO, logger="adrobot"):
        client.list_offers()
    retry = next(r for r in caplog.records if r.getMessage() == "keitaro_retry")
    assert retry.fields["reason"] == "http_503" and retry.fields["attempt"] == 1
    assert "secret" not in " ".join(str(r.fields) for r in caplog.records)
