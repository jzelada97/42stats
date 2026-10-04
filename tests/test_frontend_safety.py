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
            if any("textContent" in lines[i] for i in range(max(0, n - 3), n)):   # asignar a textContent es seguro (puede ocupar varias líneas)
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


def test_user_generated_pages_never_use_innerhtml_and_only_assign_validated_links():
    """La página de ayuda pinta texto de otros alumnos: solo con nodos de texto, y los enlaces solo tras validarlos."""
    src = (WEB / "ayuda.js").read_text(encoding="utf-8")
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src and "outerHTML" not in src
    for f in JS_FILES:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.href\s*=", line):
                assert any(ok in line for ok in ("safeUrl(", "profileUrl(", 'u)', '"/', "`/")), f"{f.name}:{n}: href sin validar: {line.strip()}"
    helpers = (WEB / "charts.js").read_text(encoding="utf-8")
    assert 'x.protocol !== "https:"' in helpers and "x.username" in helpers and 'host.includes(":")' in helpers   # safeUrl exige https, sin credenciales ni IPs
