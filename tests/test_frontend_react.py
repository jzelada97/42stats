"""Interfaz React: el servidor la sirve bien (rutas, redirecciones, caché, CSP) y su código no abre puertas a XSS."""
import re
from pathlib import Path

import pytest

from stats42.api import APP_DIR

from test_auth import CFG, login, make_client
from test_auth import engine  # noqa: F401

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def sources():
    return [f for f in SRC.rglob("*") if f.suffix in (".ts", ".tsx") and "__tests__" not in f.parts]


# ---------------------------------------------------------------- el código

def test_react_sources_never_inject_html_or_run_strings_as_code():
    assert sources(), "no se encontró el código de la interfaz"
    for f in sources():
        text = f.read_text(encoding="utf-8")
        for bad in ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function(", "javascript:"):
            assert bad not in text, f"{f.name}: {bad}"


def href_expressions(text: str):
    """Expresiones de cada `href={...}` (con las llaves de las plantillas bien emparejadas)."""
    for m in re.finditer(r"href=\{", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        yield text[m.end():i - 1].strip()


ALLOWED_HREFS = [
    r"href",                                          # variable calculada con safeUrl() o profileUrl() en el mismo fichero
    r"l\.href",                                       # menú de la cabecera (constantes del propio código)
    r"disabled \? undefined : \"/auth/login\"",
    r"`/ayuda\?project=\$\{Number\(x\.id\)\}#\w+`",
]


def test_no_css_class_is_defined_twice_at_top_level():
    """Dos reglas `.nombre { … }` con la misma clase se pisan: una barra de progreso llamada `.bar` encogió la cabecera (que ya usaba `.bar`)."""
    css = (SRC / "styles" / "app.css").read_text(encoding="utf-8")
    names = re.findall(r"^(\.[A-Za-z0-9_-]+) \{", css, re.M)
    assert sorted({n for n in names if names.count(n) > 1}) == []


def test_every_href_is_validated_or_a_constant_of_the_site():
    for f in sources():
        text = f.read_text(encoding="utf-8")
        for expr in href_expressions(text):
            assert any(re.fullmatch(p, expr) for p in ALLOWED_HREFS), f"{f.name}: href sin revisar: {expr}"
            if expr == "href":
                assert re.search(r"const href = (safeUrl|profileUrl)\(", text), f"{f.name}: `href` no sale de safeUrl/profileUrl"


def test_links_that_open_a_new_tab_never_leak_the_opener():
    for f in sources():
        for tag in re.findall(r"<a\b[^>]*target=\"_blank\"[^>]*>", f.read_text(encoding="utf-8")):
            assert 'rel="noopener noreferrer' in tag, f"{f.name}: {tag[:80]}"


def test_the_ui_only_talks_to_its_own_server():
    for f in sources():
        for url in re.findall(r"""fetch\(\s*["'`]([^"'`$]*)""", f.read_text(encoding="utf-8")):
            assert url.startswith("/"), f"{f.name}: fetch a {url}"


BUILT = APP_DIR / "index.html"


@pytest.mark.skipif(not BUILT.exists(), reason="la interfaz React no está compilada (npm run build en frontend/)")
def test_the_real_build_is_compatible_with_the_csp():
    html = BUILT.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S)
    assert scripts and all("src=" in attrs and not body.strip() for attrs, body in scripts)       # ningún script en línea
    assert not re.search(r"\son\w+\s*=", html) and "<style" not in html                          # ni manejadores ni estilos en línea
    assert not re.findall(r"(?:src|href)=\"https?://", html)                                     # ningún recurso de otro sitio


# ---------------------------------------------------------------- el servidor

@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div><script type="module" src="/static/assets/app-abc123.js"></script>', encoding="utf-8")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log('hola')", encoding="utf-8")
    (tmp_path / "theme-init.js").write_text("/* tema */", encoding="utf-8")
    return tmp_path


def react_client(engine, dist, **kw):
    return make_client(engine, app_kw={"frontend": "react", "app_dir": dist, **kw}, me={"id": 12, "login": "u12", "usual_first_name": "Ana"})


def test_every_page_route_serves_the_same_index_html_to_the_right_people(engine, dist):
    c, _ = react_client(engine, dist)
    for path in ("/me", "/ayuda", "/campus"):
        assert c.get(path).status_code == 302 and c.get(path).headers["location"] == "/login"        # sin sesión, al login
    anon = c.get("/login")
    assert anon.status_code == 200 and 'id="root"' in anon.text and anon.headers["content-type"].startswith("text/html")
    assert c.get("/").text == anon.text                                                              # la portada es el mismo documento
    login(c)
    for path in ("/me", "/ayuda", "/campus"):
        r = c.get(path)
        assert r.status_code == 200 and r.text == anon.text, path
    assert c.get("/login").headers["location"] == "/me" and c.get("/").headers["location"] == "/me"


def test_react_pages_keep_the_security_headers_and_never_get_cached(engine, dist):
    c, _ = react_client(engine, dist)
    r = c.get("/login")
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"


def test_hashed_assets_are_cached_for_a_year_and_other_static_files_for_minutes(engine, dist):
    c, _ = react_client(engine, dist)
    a = c.get("/static/assets/app-abc123.js")
    assert a.status_code == 200 and a.headers["cache-control"] == "public, max-age=31536000, immutable"
    t = c.get("/static/theme-init.js")
    assert t.status_code == 200 and t.headers["cache-control"] == "public, max-age=300"
    assert c.get("/static/ayuda.js").status_code == 404                                              # lo clásico no se mezcla con React


def test_classic_frontend_is_used_without_a_build_or_when_forced(engine, dist, tmp_path, monkeypatch):
    c, _ = make_client(engine, app_kw={"frontend": "react", "app_dir": tmp_path / "no-existe"})       # sin compilación: clásica
    assert "/static/style.css" in c.get("/login").text
    c, _ = make_client(engine, app_kw={"frontend": "classic", "app_dir": dist})                       # forzada
    assert "/static/style.css" in c.get("/login").text
    monkeypatch.setenv("FT_FRONTEND", "classic")
    c, _ = make_client(engine, app_kw={"app_dir": dist})                                              # por variable de entorno
    assert "/static/style.css" in c.get("/login").text and 'id="root"' not in c.get("/login").text


def test_the_oauth_fallback_on_the_root_still_finishes_the_login_with_react(engine, dist):
    from urllib.parse import parse_qs, urlparse
    c, _ = react_client(engine, dist)
    state = parse_qs(urlparse(c.get("/auth/login").headers["location"]).query)["state"][0]
    r = c.get("/", params={"code": "CODE", "state": state})
    assert r.status_code == 302 and r.headers["location"] == "/me"
