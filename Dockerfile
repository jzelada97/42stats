FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# Usuario sin privilegios y volumen para la base de datos SQLite
RUN useradd --system --uid 1000 app && mkdir /data && chown app /data
USER app
ENV FT_DATABASE_URL=sqlite:////data/stats42.db
VOLUME /data

ENTRYPOINT ["stats42"]
CMD ["status"]
