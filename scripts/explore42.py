"""Explora la API de 42 (campus Madrid) y resume qué datos devuelve cada endpoint.

Uso:
    set FT_UID=u-s4t2ud-...        (PowerShell: $env:FT_UID="...")
    set FT_SECRET=s-s4t2ud-...
    set FT_LOGIN=tu_login          (opcional; si no, usa un usuario del campus)
    python explore42.py

Salida: carpeta ./samples con una muestra JSON por endpoint + REPORT.md
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.intra.42.fr"
CAMPUS_ID = 22  # 42 Madrid
CURSUS_ID = 21  # 42cursus
OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)

UID = os.environ.get("FT_UID")
SECRET = os.environ.get("FT_SECRET")
if not UID or not SECRET:
    sys.exit("Faltan FT_UID y/o FT_SECRET en el entorno.")

HEADERS = {"User-Agent": "42stats-explorer/0.1 (+python)", "Accept": "application/json"}
report = []  # líneas de REPORT.md
rate_info = {}


def get_token():
    data = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": UID, "client_secret": SECRET}
    ).encode()
    req = urllib.request.Request(f"{BASE}/oauth/token", data=data, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Token HTTP {e.code}: {e.read().decode()[:400]}")
    report.append(f"- Token OK. scope={tok.get('scope')!r}, expira en {tok.get('expires_in')}s\n")
    return tok["access_token"]


TOKEN = get_token()


def api(path, params=None):
    """GET con reintento ante 429. Devuelve (json, headers)."""
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for _ in range(5):
        req = urllib.request.Request(url, headers={**HEADERS, "Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(req) as r:
                for h in ("X-Hourly-RateLimit-Limit", "X-Hourly-RateLimit-Remaining",
                          "X-Secondly-RateLimit-Limit"):
                    if r.headers.get(h):
                        rate_info[h] = r.headers.get(h)
                time.sleep(0.55)  # límite ~2 req/s
                return json.load(r), r.headers
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", 1)) + 0.5)
                continue
            return {"_error": e.code, "_body": e.read().decode()[:300]}, e.headers
    return {"_error": 429}, {}


def shape(obj, depth=0, max_depth=2):
    """Resumen compacto de claves/tipos de un JSON."""
    if isinstance(obj, dict):
        if depth >= max_depth:
            return "{...}"
        return {k: shape(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shape(obj[0], depth + 1, max_depth)] if obj else []
    return type(obj).__name__


def probe(name, path, params=None):
    data, headers = api(path, params)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    total = headers.get("X-Total") if headers else None
    if isinstance(data, dict) and "_error" in data:
        report.append(f"## {name}\n`GET {path}` -> ERROR {data['_error']} {data.get('_body','')}\n")
        print(f"[ERR {data['_error']}] {name}")
        return None
    sample = data[0] if isinstance(data, list) and data else data
    report.append(
        f"## {name}\n`GET {path}` {params or ''}\n- registros en página: "
        f"{len(data) if isinstance(data, list) else 1}, X-Total: {total}\n"
        f"- campos:\n```json\n{json.dumps(shape(sample), indent=1)}\n```\n"
    )
    print(f"[OK] {name}  (total={total})")
    return data


# 1) Campus y usuarios
probe("campus", f"/v2/campus/{CAMPUS_ID}")
users = probe("campus_users", f"/v2/campus/{CAMPUS_ID}/users", {"page[size]": 5, "sort": "-created_at"})
cursus_users = probe(
    "cursus_users_campus",
    f"/v2/cursus_users",
    {"filter[campus_id]": CAMPUS_ID, "filter[cursus_id]": CURSUS_ID, "page[size]": 5, "sort": "-level"},
)

# 2) Usuario concreto
login = os.environ.get("FT_LOGIN") or (users[0]["login"] if users else None)
if login:
    user = probe("user_detail", f"/v2/users/{login}")
    uid = user["id"] if user else None
    if uid:
        probe("user_projects_users", f"/v2/users/{uid}/projects_users", {"page[size]": 10})
        probe("user_cursus_users", f"/v2/users/{uid}/cursus_users")
        probe("user_locations", f"/v2/users/{uid}/locations", {"page[size]": 10})
        probe("user_locations_stats", f"/v2/users/{uid}/locations_stats")
        probe("user_achievements", f"/v2/users/{uid}/achievements_users", {"page[size]": 10})
        probe("user_quests", f"/v2/users/{uid}/quests_users")
        probe("user_coalitions", f"/v2/users/{uid}/coalitions_users")
        probe("user_scale_teams_as_corrector", f"/v2/users/{uid}/scale_teams/as_corrector", {"page[size]": 5})
        probe("user_scale_teams_as_corrected", f"/v2/users/{uid}/scale_teams/as_corrected", {"page[size]": 5})
        probe("user_teams", f"/v2/users/{uid}/teams", {"page[size]": 5})
        probe("user_exams", f"/v2/users/{uid}/exams_users", {"page[size]": 5})
        probe("user_correction_point_history", f"/v2/users/{uid}/correction_point_historics", {"page[size]": 5})
        probe("user_titles", f"/v2/users/{uid}/titles_users")
        probe("user_events", f"/v2/users/{uid}/events_users", {"page[size]": 5})
        probe("user_experiences", f"/v2/users/{uid}/experiences", {"page[size]": 5})

# 3) Datos globales del campus
probe("campus_locations_active", f"/v2/campus/{CAMPUS_ID}/locations", {"filter[active]": "true", "page[size]": 10})
probe("campus_events", f"/v2/campus/{CAMPUS_ID}/events", {"page[size]": 5, "sort": "-begin_at"})
probe("campus_exams", f"/v2/campus/{CAMPUS_ID}/exams", {"page[size]": 5, "sort": "-begin_at"})
probe("campus_projects_users_recent",
      "/v2/projects_users", {"filter[campus]": CAMPUS_ID, "page[size]": 5, "sort": "-updated_at"})
probe("campus_coalitions", f"/v2/campus/{CAMPUS_ID}/coalitions")
probe("cursus_projects", f"/v2/cursus/{CURSUS_ID}/projects", {"page[size]": 5})
probe("achievements", "/v2/achievements", {"filter[campus_id]": CAMPUS_ID, "page[size]": 5})
probe("campus_scale_teams", "/v2/scale_teams", {"filter[campus_id]": CAMPUS_ID, "page[size]": 5, "sort": "-created_at"})
probe("campus_users_pooled", f"/v2/campus/{CAMPUS_ID}/users",
      {"filter[pool_year]": "2024", "page[size]": 5})

hdr = "# Informe exploración API 42 (Madrid, campus 22)\n\n"
hdr += f"- Rate limit observado: `{json.dumps(rate_info)}`\n"
(Path(__file__).parent / "REPORT.md").write_text(hdr + "\n".join(report), encoding="utf-8")
print("\nListo -> REPORT.md y carpeta samples/")
