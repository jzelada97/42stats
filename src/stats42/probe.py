"""Sondeo para el administrador: ¿el token de un alumno devuelve más datos que el de la aplicación?

Se ejecuta una vez, en el callback del login de un admin, y escribe un fichero con el resultado. Sirve para decidir
si merece la pena mostrar freeze o deadline a quien inicia sesión. No se ejecuta para otros alumnos.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from .client import ApiError, FortyTwoClient

DEFAULT_PAUSE = 0.7     # 42 solo admite 2 peticiones por segundo en toda la aplicación
API = "https://api.intra.42.fr"
INTRAPY = "https://intrapy.intra.42.fr/api/v1"
INTEREST = re.compile(r"deadline|milestone|freez|froze|hold|blackhole|ultimate|expire|extension|pause|close|agu", re.I)

CANDIDATES = [
    "/v2/me",
    "/v2/users/{id}",
    "/v2/users/{id}/cursus_users",
    "/v2/users/{id}/quests_users",
    "/v2/users/{id}/anti_grav_units_users",
    "/v2/users/{id}/closes",
    "/v2/users/{id}/events_users",
    "/v2/users/{id}/locations_stats",
    "/v2/users/{id}/projects_users",
]
INTRAPY_CANDIDATES = ["/users/me", "/users/me/cursus", "/users/me/summary", "/users/me/projects/ongoing?cursus_id=21"]


def flat_keys(obj, prefix: str = "") -> set[str]:
    """Rutas de claves de un JSON; las listas se aplanan con []."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            out.add(p)
            out |= flat_keys(v, p)
    elif isinstance(obj, list):
        for v in obj[:30]:
            out |= flat_keys(v, prefix + "[]")
    return out


def _get(http: httpx.Client, url: str, token: str):
    try:
        r = http.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        try:
            body = r.json()
        except ValueError:
            body = None
        return r.status_code, body, r.text[:300]
    except httpx.HTTPError as e:
        return 0, None, f"{type(e).__name__}: {e}"


def run_probe(token: str, user_id: int, http: httpx.Client, app: FortyTwoClient, pause: float | None = None) -> list[dict]:
    pause = DEFAULT_PAUSE if pause is None else pause
    results = []
    for tpl in CANDIDATES:
        ep = tpl.format(id=user_id)
        time.sleep(pause)    # espaciado: 42 solo admite 2 peticiones por segundo
        u_status, u_body, u_text = _get(http, API + ep, token)
        try:
            a_resp = app.get(ep, {"page[size]": 100} if "{id}/" in tpl else None)
            a_status, a_body = a_resp.status_code, a_resp.json()
        except ApiError as e:
            a_status, a_body = e.status, None
        uk, ak = flat_keys(u_body), flat_keys(a_body)
        results.append({
            "endpoint": tpl, "user_token_status": u_status, "app_token_status": a_status,
            "extra_keys_with_user_token": sorted(uk - ak)[:60],
            "keys_of_interest": sorted(k for k in uk if INTEREST.search(k))[:40],
            "error": None if u_status == 200 else u_text,
        })
    for ep in INTRAPY_CANDIDATES:
        time.sleep(pause)
        status, body, text = _get(http, INTRAPY + ep, token)
        results.append({
            "endpoint": "intrapy " + ep, "user_token_status": status, "app_token_status": None,
            "keys_of_interest": sorted(k for k in flat_keys(body) if INTEREST.search(k))[:40],
            "keys": sorted(flat_keys(body))[:60], "error": None if status == 200 else text,
        })
    return results


def save_probe(directory: str, login: str, results: list[dict]) -> Path:
    path = Path(directory) / f"probe-{re.sub(r'[^A-Za-z0-9_.-]', '_', login)}.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    return path
