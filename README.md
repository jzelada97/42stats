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

No se guardan emails, teléfonos ni nombres. El detalle individual solo debe mostrarse al propio
alumno (login con 42); del resto del campus, solo agregados.
