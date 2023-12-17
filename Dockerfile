FROM alpine:3.19

LABEL org.label-schema.name="Iceberg" \
      org.label-schema.description="Iceberg Debrid Downloader" \
      org.label-schema.url="https://github.com/dreulavelle/iceberg"

RUN apk --update add \
    python3 py3-pip \
    nodejs npm \
    bash shadow \
    vim nano curl \
    rclone && \
    rm -rf /var/cache/apk/*

RUN npm install -g pnpm

WORKDIR /iceberg
COPY . /iceberg/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN python3 -m venv /venv && \
    source /venv/bin/activate && \
    pip3 install --no-cache-dir -r /iceberg/requirements.txt

RUN cd /iceberg/frontend && \
    pnpm install && \
    pnpm run build

EXPOSE 4173 8080
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Start the backend first, then the frontend (suppressed frontend output)
CMD cd /iceberg/backend && source /venv/bin/activate && exec python main.py & \
    cd /iceberg/frontend && pnpm run preview --host 0.0.0.0 >/dev/null 2>&1
