"""Cliente de la API de 42: token, límite de peticiones, reintentos y paginación."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
MAX_RETRY_AFTER = 3700  # el límite horario puede pedir esperar casi una hora


class ApiError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} en {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


class FortyTwoClient:
    """Respeta ~2 req/s; ante 429 espera Retry-After; renueva el token si caduca."""

    def __init__(
        self,
        uid: str,
        secret: str,
        *,
        base_url: str = "https://api.intra.42.fr",
        user_agent: str = "stats42/0.1",
        min_interval: float = 0.55,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._uid, self._secret = uid, secret
        self._http = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )
        self._min_interval = min_interval
        self._sleep, self._clock = sleep, clock
        self._last_request = float("-inf")
        self._token: str | None = None
        self._token_expires = 0.0
        self.requests = 0

    # --- token ---
    def _get_token(self, force: bool = False) -> str:
        if not force and self._token and self._clock() < self._token_expires:
            return self._token
        r = self._http.post(
            "/oauth/token",
            data={"grant_type": "client_credentials", "client_id": self._uid, "client_secret": self._secret},
        )
        if not r.is_success:
            raise ApiError(r.status_code, r.text, "/oauth/token")
        data = r.json()
        self._token = data["access_token"]
        self._token_expires = self._clock() + max(int(data.get("expires_in", 7200)) - 60, 0)
        return self._token

    # --- peticiones ---
    def _throttle(self) -> None:
        wait = self._min_interval - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        refreshed = False
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            r = self._http.get(
                path, params=params, headers={"Authorization": f"Bearer {self._get_token()}"}
            )
            self.requests += 1
            if r.is_success:
                return r
            if r.status_code == 401 and not refreshed:
                refreshed = True
                self._get_token(force=True)
                continue
            if r.status_code == 429:
                wait = _retry_after(r)
                log.warning("429 en %s: esperando %.0f s", path, wait)
                self._sleep(wait)
                continue
            if r.status_code >= 500:
                self._sleep(2**attempt)
                continue
            raise ApiError(r.status_code, r.text, str(r.url))
        raise ApiError(r.status_code, r.text, str(r.url))

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        page_size: int = 100,
        start_page: int = 1,
    ) -> Iterator[tuple[int, list[dict]]]:
        """Rinde (nº de página, registros). `start_page` permite reanudar."""
        page = start_page
        while True:
            q = {**(params or {}), "page[size]": page_size, "page[number]": page}
            items = self.get(path, q).json()
            if not items:
                return
            yield page, items
            if len(items) < page_size:
                return
            page += 1

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FortyTwoClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _retry_after(r: httpx.Response) -> float:
    try:
        wait = float(r.headers.get("Retry-After", 2))
    except ValueError:
        wait = 2.0
    return min(wait + 0.5, MAX_RETRY_AFTER)
