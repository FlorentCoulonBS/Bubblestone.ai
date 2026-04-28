FROM node:25-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV ZAP_VERSION=2.17.0
ENV ZAP_PATH=/opt/zaproxy

# System dependencies (Python, Java for ZAP, wkhtmltopdf for PDF, Chrome for Lighthouse)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates curl unzip \
    python3 python3-pip python3-venv \
    openjdk-17-jre-headless \
    wkhtmltopdf \
    xvfb \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome (for Lighthouse)
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Lighthouse
RUN npm i -g lighthouse

# OWASP ZAP
RUN wget -q "https://github.com/zaproxy/zaproxy/releases/download/v${ZAP_VERSION}/ZAP_${ZAP_VERSION}_Linux.tar.gz" \
      -O /tmp/zap.tar.gz \
    && mkdir -p /opt \
    && tar xzf /tmp/zap.tar.gz -C /opt \
    && mv "/opt/ZAP_${ZAP_VERSION}" "${ZAP_PATH}" \
    && rm /tmp/zap.tar.gz
RUN wget -q "https://raw.githubusercontent.com/zaproxy/zaproxy/main/docker/zap-baseline.py" \
      -O /usr/local/bin/zap-baseline.py \
    && wget -q "https://raw.githubusercontent.com/zaproxy/zaproxy/main/docker/zap_common.py" \
      -O /usr/local/bin/zap_common.py \
    && chmod +x /usr/local/bin/zap-baseline.py

ENV PATH="${ZAP_PATH}:${PATH}"

# Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages -r /tmp/requirements.txt

WORKDIR /app

# Application code
COPY app.py run_audit.py crawler.py migration_analysis.py geo_audit.py responsive_check.py ./
COPY check_headers.py detect_stack.py generate_report.py ./
COPY dns_email.py ssl_deep.py wordpress_scan.py wordpress_internal.py ./
COPY audit.sh ./
RUN chmod +x audit.sh
COPY template.html ./
COPY tpl_*.html ./

ENV HOME=/root
ENV ZAP_HOME=/root/.ZAP
RUN mkdir -p /root/.ZAP

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "--timeout", "900", "app:app"]
