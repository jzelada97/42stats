"""Calcula, SIN modelo, el resumen semanal de un alumno a partir de samples/.

El LLM nunca hace cuentas: recibe este digest ya calculado y solo lo redacta.
Salida: spike/digest.json y spike/feedbacks.json
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
OUT = Path(__file__).resolve().parent
TODAY = date.today()

# Totales (X-Total) vistos en la exploración; los samples solo traen la 1a página.
TOTALS = {"eval_as_corrector": 45, "eval_as_corrected": 66, "projects": 36}


def load(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def hours(s):
    h, m, sec = s.split(":")
    return int(h) + int(m) / 60 + float(sec) / 3600


# --- asistencia ---
stats = {date.fromisoformat(k): hours(v) for k, v in load("user_locations_stats").items()}
def window(days, offset=0):
    return round(sum(h for d, h in stats.items() if offset <= (TODAY - d).days < offset + days), 1)

last_day = max(stats) if stats else None
attendance = {
    "horas_ultimos_7_dias": window(7),
    "horas_7_dias_anteriores": window(7, 7),
    "horas_ultimos_30_dias": window(30),
    "dias_con_asistencia_30d": sum(1 for d in stats if (TODAY - d).days < 30),
    "ultima_conexion": last_day.isoformat() if last_day else None,
    "dias_desde_ultima_conexion": (TODAY - last_day).days if last_day else None,
}

# --- nivel / blackhole ---
cursus = next(c for c in load("user_cursus_users") if c["cursus"]["slug"] == "42cursus")
bh = parse_dt(cursus["blackholed_at"])
level = {
    "nivel": cursus["level"],
    "dias_en_el_cursus": (datetime.now(timezone.utc) - parse_dt(cursus["begin_at"])).days,
    "blackhole": bh.date().isoformat() if bh else None,
    "dias_hasta_blackhole": (bh.date() - TODAY).days if bh else None,
}

# --- proyectos ---
pus = load("user_projects_users")
done = [p for p in pus if p["status"] == "finished"]
durations = [
    (parse_dt(p["marked_at"]) - parse_dt(p["created_at"])).days
    for p in done if p["marked_at"] and p["created_at"]
]
projects = {
    "proyectos_totales_historico": TOTALS["projects"],
    "validados_en_muestra": sum(1 for p in done if p["validated?"]),
    "en_curso": [
        {"nombre": p["project"]["name"], "nota_actual": p["final_mark"], "desde": p["created_at"][:10]}
        for p in pus if p["status"] == "in_progress"
    ],
    "ultimos_validados": [
        {"nombre": p["project"]["name"], "nota": p["final_mark"], "fecha": p["marked_at"][:10]}
        for p in done[:3]
    ],
    "dias_medios_por_proyecto_reciente": round(sum(durations) / len(durations), 1) if durations else None,
}

# --- evaluaciones, puntos, coalición ---
user = load("user_detail")
coal = max(load("user_coalitions"), key=lambda c: c["updated_at"])
social = {
    "evaluaciones_hechas": TOTALS["eval_as_corrector"],
    "evaluaciones_recibidas": TOTALS["eval_as_corrected"],
    "puntos_de_correccion": user["correction_point"],
    "coalicion_rank": coal["rank"],
    "coalicion_score": coal["score"],
}

digest = {
    "fecha_hoy": TODAY.isoformat(),
    "alumno": user["usual_first_name"] or user["first_name"],
    "campus": "42 Madrid",
    "asistencia": attendance,
    "nivel": level,
    "proyectos": projects,
    "social": social,
}
(OUT / "digest.json").write_text(json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")

# Feedback de texto recibido (lo que el LLM sí aporta frente a un dashboard)
fb = []
for s in load("user_scale_teams_as_corrected"):
    fb.append({"nota": s["final_mark"], "flag": s["flag"]["name"],
               "comentario_corrector": (s["comment"] or "").strip(),
               "feedback_sobre_ti": (s["feedback"] or "").strip()})
(OUT / "feedbacks.json").write_text(json.dumps(fb, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(digest, indent=2, ensure_ascii=False))
print(f"\n{len(fb)} feedbacks guardados")
