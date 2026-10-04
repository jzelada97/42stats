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

## Copias de seguridad

`stats42 backup --dest DIR --keep 14` guarda una copia consistente (API de copias de SQLite, válida con la sincronización
escribiendo) de la base del campus y de la de ajustes de usuarios, comprueba su integridad, la comprime (`.db.gz`, permisos 0600)
y conserva las 14 más recientes de cada una. En la VM la lanza `deploy/stats42-backup.timer` cada día a las 07:00 y las deja en
`/var/backups/stats42`. Restaurar: `gunzip -c stats42-AAAAMMDD-HHMMSS.db.gz > stats42.db` con la web y la sincronización paradas.
Las copias están en el mismo disco que los datos: para protegerse de perder la VM hay que bajarlas a otro sitio de vez en cuando.

## Interfaz

Hay dos interfaces. La **React** (Vite + TypeScript, en `frontend/`) es la principal: tema claro y oscuro (papel y matcha / musgo y
bambú), con una sola página de entrada que el servidor devuelve en `/`, `/login`, `/me`, `/ayuda` y `/campus`. La **clásica**
(HTML y JS a mano en `src/stats42/web/`) queda como reserva.

- El servidor usa React si existe `src/stats42/web_app/index.html` (lo genera `npm run build`; no se versiona) y, si no, la clásica.
  `FT_FRONTEND=classic` fuerza la clásica; `FT_FRONTEND=react` avisa en el log si falta la compilación.
- El `Dockerfile` compila React en una etapa de Node y copia solo el resultado estático a la imagen final.
- Desarrollo: `cd frontend && npm install && npm run dev` (proxy a la API en el puerto 8042); `npm test` (Vitest) y `npm run typecheck`.
- Seguridad: el CSP no admite scripts en línea y el texto de otros alumnos se pinta siempre como texto. `tests/test_frontend_react.py` vigila
  que el código no use `dangerouslySetInnerHTML` ni `innerHTML`, que cada `href` pase por `safeUrl`/`profileUrl` y que la compilación
  real sea compatible con el CSP.

## Avisos por correo (opt-in) con Brevo

Los avisos son opcionales: sin `FT_SMTP_HOST` y `FT_MAIL_FROM` la web no los ofrece. Brevo tiene un plan gratuito de 300 correos al día.

1. Crea una cuenta en Brevo, añade tu dominio y autentícalo (registros DNS de DKIM y DMARC).
2. En *Settings > SMTP & API* copia el **Login** (un correo único) y crea una **SMTP key**: es la contraseña (no la de la cuenta ni una API key).
3. Pon en `.env.web` (nunca en git): `FT_SMTP_HOST=smtp-relay.brevo.com`, `FT_SMTP_PORT=587`, `FT_SMTP_USER=<login>`,
   `FT_SMTP_PASSWORD=<smtp key>` y `FT_MAIL_FROM=42stats <avisos@tudominio>` (el remitente debe estar en el dominio autenticado). Opcional: `FT_MAIL_REPLY_TO=tu@tudominio` para que las respuestas lleguen a tu buzón.
4. Prueba: `docker compose -f docker-compose.vm.yml run --rm web mailtest --to tu@correo` (o `stats42 mailtest --to ...` en local).
5. Resumen diario a los mentores: instala `deploy/stats42-notify.timer` (`systemctl enable --now stats42-notify.timer`).

`src/stats42/mailer.py` solo usa la biblioteca estándar: se puede copiar tal cual a otro proyecto.

