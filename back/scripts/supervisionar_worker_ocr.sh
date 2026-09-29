#!/bin/sh
# Mantém este container útil: healthcheck do Docker só marca "unhealthy"; ele
# não reinicia o serviço. Este supervisor encerra o processo principal quando o
# worker OCR perde o contato com o broker/control por três ciclos seguidos, e a
# política `restart_policy` do Swarm cria uma réplica nova.
set -eu

"$@" &
worker_pid=$!
falhas=0

encerrar() {
    kill -TERM "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
    exit 0
}
trap encerrar INT TERM

while kill -0 "$worker_pid" 2>/dev/null; do
    sleep 30
    if celery -A app.celery_app:celery_app inspect ping \
        -d "ocr@${HOSTNAME}" --timeout=5 2>/dev/null | grep -q pong; then
        falhas=0
        continue
    fi

    falhas=$((falhas + 1))
    echo "worker OCR sem resposta ao inspect (${falhas}/3)" >&2
    if [ "$falhas" -ge 3 ]; then
        echo "reiniciando worker OCR sem resposta" >&2
        kill -TERM "$worker_pid" 2>/dev/null || true
        wait "$worker_pid" 2>/dev/null || true
        exit 1
    fi
done

wait "$worker_pid"
