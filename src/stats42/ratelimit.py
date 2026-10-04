"""Límite de ritmo en memoria (ventana deslizante)."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Como mucho `limit` eventos por `window` segundos y clave. No vale con varias instancias: vive en memoria."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits.setdefault(key, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 10_000:       # evita que el diccionario crezca sin límite: se podan las claves ya caducadas
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] <= self.window}
        return True
