import httpx
import pytest

from stats42.client import ApiError, FortyTwoClient


def make_client(handler, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    c = FortyTwoClient(
        "uid", "secret", min_interval=0,
        transport=httpx.MockTransport(handler), sleep=sleeps.append,
    )
    return c, sleeps


def token_response():
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})


def test_paginate_collects_all_pages():
    pages = {1: list(range(100)), 2: list(range(100, 200)), 3: [200, 201]}

    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        return httpx.Response(200, json=pages[int(req.url.params["page[number]"])])

    c, _ = make_client(handler)
    got = [(p, len(items)) for p, items in c.paginate("/v2/x")]
    assert got == [(1, 100), (2, 100), (3, 2)]


def test_paginate_resumes_from_start_page():
    seen = []

    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        seen.append(int(req.url.params["page[number]"]))
        return httpx.Response(200, json=[1])

    c, _ = make_client(handler)
    assert [p for p, _ in c.paginate("/v2/x", start_page=7)] == [7]
    assert seen == [7]


def test_429_waits_retry_after_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json=[{"ok": 1}])

    c, sleeps = make_client(handler)
    assert c.get("/v2/x").json() == [{"ok": 1}]
    assert 3.5 in sleeps


def test_401_refreshes_token_once():
    tokens = {"n": 0}
    api = {"n": 0}

    def handler(req):
        if req.url.path == "/oauth/token":
            tokens["n"] += 1
            return token_response()
        api["n"] += 1
        return httpx.Response(401) if api["n"] == 1 else httpx.Response(200, json=[])

    c, _ = make_client(handler)
    c.get("/v2/x")
    assert tokens["n"] == 2


def test_client_error_raises_api_error_with_body():
    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        return httpx.Response(400, json={"error": "Filter Error"})

    c, _ = make_client(handler)
    with pytest.raises(ApiError) as e:
        c.get("/v2/x")
    assert e.value.status == 400 and "Filter Error" in e.value.body


def test_sends_custom_user_agent():
    agents = []

    def handler(req):
        agents.append(req.headers["user-agent"])
        return token_response() if req.url.path == "/oauth/token" else httpx.Response(200, json=[])

    c = FortyTwoClient("u", "s", min_interval=0, user_agent="stats42-test", transport=httpx.MockTransport(handler))
    c.get("/v2/x")
    assert set(agents) == {"stats42-test"}


def test_timeouts_are_retried_then_succeed():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ReadTimeout("lento", request=req)
        return httpx.Response(200, json=[{"ok": 1}])

    c, sleeps = make_client(handler)
    assert c.get("/v2/x").json() == [{"ok": 1}]
    assert calls["n"] == 3 and sleeps == [1, 2]


def test_persistent_timeouts_raise_api_error_not_raw_httpx_error():
    def handler(req):
        if req.url.path == "/oauth/token":
            return token_response()
        raise httpx.ReadTimeout("lento", request=req)

    c, _ = make_client(handler)
    with pytest.raises(ApiError) as e:
        c.get("/v2/x")
    assert e.value.status == 0 and "ReadTimeout" in e.value.body
