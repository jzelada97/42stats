# Etapa 1: compila la interfaz React (Vite + TypeScript). Solo el resultado estático pasa a la imagen final.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
# vite.config.ts saca la compilación a ../src/stats42/web_app, es decir, /src/stats42/web_app dentro de esta etapa
RUN npm run build

# Etapa 2: la API y la web
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY --from=ui /src/stats42/web_app ./src/stats42/web_app
RUN pip install --upgrade pip && pip install .

# Usuario sin privilegios y volumen para la base de datos SQLite
RUN useradd --system --uid 1000 app && mkdir /data && chown app /data
USER app
ENV FT_DATABASE_URL=sqlite:////data/stats42.db \
    FT_SETTINGS_DATABASE_URL=sqlite:////data/user_settings.db \
    FT_PROPOSALS_DATABASE_URL=sqlite:////data/proposals.db
VOLUME /data

ENTRYPOINT ["stats42"]
CMD ["status"]
