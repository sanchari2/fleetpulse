FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir requests==2.32.3 \
 && useradd --uid 10002 --no-create-home --shell /usr/sbin/nologin simulator

WORKDIR /app
COPY --chown=10002:10002 simulator/simulate.py ./simulate.py

USER 10002
CMD ["python", "simulate.py"]
