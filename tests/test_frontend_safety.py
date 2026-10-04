"""Red de seguridad contra XSS: todo texto que viene de 42 o del usuario debe escaparse antes de ir a innerHTML.

La defensa principal es la CSP (sin scripts inline) y esc(); esta prueba vigila que nadie se olvide de esc().
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "src" / "stats42" / "web"
JS_FILES = sorted(WEB.glob("*.js"))

# Propiedades que contienen texto libre procedente de 42 (nombres de proyectos, eventos...) o del servidor.
RISKY = re.compile(r"\.(name|names|kind|location|detail|message|login|year|cursus|label|value|text|title|date|reason)\b")
SAFE_WRAPPERS = ("esc(", ".map(esc)", "fmt(", "fmt1(", "nf.format", "pct(", "monthLabel(", "dayLabel(", "weekLabel(",
                 "duration(", "STATE_ICON", "STATE_TEXT", "STATUS_ICON", "Math.", ".length", "dateFmt", "timeFmt",
                 "y(", "heat(")     # y() y heat() devuelven números/colores calculados, no texto


def interpolations(src: str):
    """Rinde (línea, expresión) de cada ${...} simple de las plantillas."""
    for n, line in enumerate(src.splitlines(), 1):
        for m in re.finditer(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", line):
            yield n, m.group(1)


def test_every_risky_interpolation_is_escaped_or_numeric():
    offenders = []
    for f in JS_FILES:
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        for n, expr in interpolations(src):
            if "textContent" in lines[n - 1]:      # asignar a textContent es seguro: el navegador no interpreta HTML
                continue
            if RISKY.search(expr) and not any(w in expr for w in SAFE_WRAPPERS):
                offenders.append(f"{f.name}:{n}: ${{{expr}}}")
    assert offenders == [], "Interpolaciones con texto externo sin escapar:\n" + "\n".join(offenders)


def test_esc_neutralises_html_and_quotes():
    src = (WEB / "charts.js").read_text(encoding="utf-8")
    m = re.search(r"const esc = \(s\) => (.*);", src)
    assert m, "no se encontró esc()"
    body = m.group(1)
    for ch in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert ch in body, f"esc() no produce {ch}"


def test_no_inline_event_handlers_or_javascript_urls_in_pages():
    for page in WEB.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", html, re.I), f"{page.name}: manejador de eventos inline"
        assert "javascript:" not in html.lower(), f"{page.name}: URL javascript:"


def test_js_never_uses_dangerous_sinks():
    for f in JS_FILES:
        src = f.read_text(encoding="utf-8")
        for bad in ("eval(", "new Function", "document.write", "setTimeout(\"", "setInterval(\""):
            assert bad not in src, f"{f.name}: usa {bad}"
