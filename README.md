# 42stats

Estadísticas del campus 42 Madrid a partir de la API de 42. Un job diario sincroniza los datos
a una base de datos y calcula las stats; la web solo lee resultados ya calculados.

## Puesta en marcha

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env      # y rellena FT_UID / FT_SECRET (nunca los subas a git)
```

## Uso

```powershell
.\.venv\Scripts\stats42 check          # 1 petición por recurso: valida filtros y credenciales
.\.venv\Scripts\stats42 sync -v        # sincroniza todo (incremental y reanudable)
.\.venv\Scripts\stats42 sync project_users --full
.\.venv\Scripts\stats42 status
```

La primera sincronización es una carga completa y puede tardar horas (límite de la API: 2 req/s y
1.200 req/h). Si se corta, repetir el comando retoma desde el último checkpoint. Después, cada
ejecución solo trae lo modificado desde la última (con 1 día de solape).

## Estructura

- `src/stats42/client.py` — cliente de la API: token, límite de peticiones, reintentos, paginación.
- `src/stats42/sync.py` — sincronización incremental con checkpoint por página.
- `src/stats42/resources.py` — qué endpoints se sincronizan y cómo se mapean a tablas.
- `src/stats42/db.py` — modelos SQLAlchemy (SQLite por defecto; PostgreSQL con `FT_DATABASE_URL`).
- `scripts/explore42.py` — script de exploración de la API usado al inicio.
- `spike/` — prueba de concepto de un LLM local en el navegador (aparcada; ver notas).

## Privacidad

No se guardan emails, teléfonos ni nombres. El detalle individual solo se muestra al propio alumno
(login con 42); del resto del campus, solo agregados.

**Nada es público salvo el login.** Las estadísticas del campus (`/campus` y todas las rutas `/api/*` de datos) solo
responden a una sesión válida de un alumno que entró con 42 y está en los datos del campus de Madrid. Algunas cifras
agregadas (p. ej. a qué horas está vacío el edificio) no deben ser públicas. `FT_REQUIRE_LOGIN=0` lo desactiva solo para
desarrollo local. Las páginas llevan `noindex` y `robots.txt` lo prohíbe todo.

## Login con 42 y panel personal

`/login` lleva a 42 (OAuth, permiso `public`); 42 devuelve al alumno a `FT_BASE_URL/auth/callback` y la web crea una
cookie de sesión firmada con su id, login y nombre visible. **No se guarda el token.** `/me` muestra solo los datos de quien ha entrado:
ritmo, milestones, actividad, comparación con su cursus y consejos por reglas (sin modelo).

La sesión dura 12 h como máximo, la cookie muere al cerrar el navegador y cada sesión tiene su fila en `user_sessions`: salir
(o borrar tus datos desde `/me`) la revoca aunque alguien hubiera copiado la cookie. El texto libre de la ayuda no admite
enlaces, las peticiones se borran al cerrarlas o a los 30 días y los envíos rechazados a los 30 días.

La web y la sincronización usan **aplicaciones de 42 distintas**: `.env` (sincronización) y `.env.web` (web, con su
propio `FT_UID`/`FT_SECRET`). Así tienen límite de ritmo propio (42 permite 2 peticiones por segundo por aplicación) y
un secreto filtrado de la web no da acceso a la sincronización.

Para activarlo hay que añadir `FT_BASE_URL/auth/callback` como *Redirect URI* de la aplicación en
`profile.intra.42.fr/oauth/applications` y definir `FT_SESSION_SECRET` y `FT_BASE_URL` en `.env`.

Los logins de `FT_ADMIN_LOGINS` ejecutan, al entrar, un sondeo que compara lo que devuelve el token del alumno con el de la
aplicación (y con la API interna `intrapy`) y lo guarda en `/data/probe-<login>.json`.
