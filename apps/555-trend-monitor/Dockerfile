FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg cron supervisor && \
    rm -rf /var/lib/apt/lists/*

# Build context = /root/src/ai_trend_monitor/
# Recreate the expected layout for pip install
WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
RUN mkdir -p /build/src
COPY . /build/src/ai_trend_monitor/

# Remove non-source files from package dir
RUN rm -f /build/src/ai_trend_monitor/Dockerfile \
          /build/src/ai_trend_monitor/pyproject.toml \
          /build/src/ai_trend_monitor/supervisord.conf && \
    rm -rf /build/src/ai_trend_monitor/scripts

# Install with CPU-only torch
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
    /build/ && \
    rm -rf /root/.cache/pip

WORKDIR /app

# Utility scripts
COPY scripts/ /scripts/

# Cron: collect every 3h (env vars injected at runtime via entrypoint)
RUN printf 'SHELL=/bin/bash\n0 */3 * * * /scripts/collect.sh\n' > /etc/cron.d/collect && \
    chmod 0644 /etc/cron.d/collect && \
    crontab /etc/cron.d/collect && \
    touch /var/log/collect.log

# Collect wrapper: sources env vars so cron inherits GMAIL_* etc.
RUN printf '#!/bin/bash\nsource /etc/environment 2>/dev/null\nexec python -m ai_trend_monitor --collect >> /var/log/collect.log 2>&1\n' > /scripts/collect.sh && \
    chmod +x /scripts/collect.sh

# Entrypoint: dump runtime env vars for cron, then exec CMD
RUN printf '#!/bin/bash\nenv | grep -E "^(GMAIL_|DATABASE_|OPML_|PATH=)" > /etc/environment\nexec "$@"\n' > /scripts/entrypoint.sh && \
    chmod +x /scripts/entrypoint.sh

# Supervisord
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf


ENTRYPOINT ["/scripts/entrypoint.sh"]

ENV DATABASE_PATH=/data/trends.db
ENV OPML_PATH=/data/feeds.opml

EXPOSE 5000

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
