"""Login con 42 (OAuth authorization code) y sesión en una cookie firmada.

No se guarda el token del alumno: se usa una vez, en el callback, para saber quién es.
La sesión solo contiene id, login y nombre visible.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer

AUTHORIZE_URL = "https://api.intra.42.fr/oauth/authorize"
TOKEN_URL = "https://api.intra.42.fr/oauth/token"
ME_URL = "https://api.intra.42.fr/v2/me"

SESSION_COOKIE = "stats42_session"
STATE_COOKIE = "stats42_state"
SESSION_TTL = 7 * 24 * 3600
STATE_TTL = 600


@dataclass(frozen=True)
class AuthConfig:
    uid: str = ""
    secret: str = ""
    session_secret: str = ""
    base_url: str = ""            # p. ej. https://42madrid.zelada.es (sin barra final)
    admin_logins: frozenset = frozenset()
    probe_dir: str | None = None  # si existe, el sondeo de un admin escribe aquí su resultado

    @classmethod
    def from_env(cls) -> "AuthConfig":
        env = os.environ.get
        return cls(
            uid=env("FT_UID", ""),
            secret=env("FT_SECRET", ""),
            session_secret=env("FT_SESSION_SECRET", ""),
            base_url=env("FT_BASE_URL", "").rstrip("/"),
            admin_logins=frozenset(x.strip() for x in env("FT_ADMIN_LOGINS", "").split(",") if x.strip()),
            probe_dir=env("FT_PROBE_DIR") or None,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.uid and self.secret and self.session_secret and self.base_url)

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")


def _serializer(cfg: AuthConfig, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(cfg.session_secret, salt=salt)


def sign(cfg: AuthConfig, salt: str, data) -> str:
    return _serializer(cfg, salt).dumps(data)


def unsign(cfg: AuthConfig, salt: str, token: str | None, max_age: int):
    """Devuelve los datos o None si falta, está manipulado o ha caducado."""
    if not token:
        return None
    try:
        return _serializer(cfg, salt).loads(token, max_age=max_age)
    except BadSignature:  # incluye SignatureExpired
        return None


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(cfg: AuthConfig, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": cfg.uid, "redirect_uri": cfg.redirect_uri, "response_type": "code",
        "scope": "public", "state": state,
    })


def exchange_code(cfg: AuthConfig, code: str, http: httpx.Client) -> str:
    """Cambia el código por un token de acceso. Lanza httpx.HTTPError si 42 lo rechaza."""
    r = http.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "client_id": cfg.uid, "client_secret": cfg.secret,
        "code": code, "redirect_uri": cfg.redirect_uri,
    })
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_me(token: str, http: httpx.Client) -> dict:
    r = http.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()
