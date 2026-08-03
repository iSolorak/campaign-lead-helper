FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system django \
    && adduser --system --ingroup django --home /app django \
    && mkdir -p /data /app/staticfiles \
    && chown -R django:django /app /data

COPY --chown=django:django requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY --chown=django:django . /app

USER django
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket; connection=socket.create_connection(('127.0.0.1',8000),3); connection.close()" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
