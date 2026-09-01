#!/usr/bin/env bash
# Sobe o Acervo no macOS/Linux: Docker de apoio, agente, API, workers, transcrição e Next.
#
#   ./iniciar.sh              -> modo desenvolvimento
#   ./iniciar.sh --prod       -> usa build de produção do Next
#   ./iniciar.sh --sem-auth   -> desliga autenticação local
#   ./iniciar.sh --sem-agente -> não sobe ia-juridica
#   ./iniciar.sh --sem-jitsi  -> não sobe chamadas
#   ./iniciar.sh --porta 3100 -> troca a porta do frontend

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PROD=0
PORTA=3000
SEM_AUTH=0
SEM_AGENTE=0
SEM_JITSI=0

BACKEND_PID=""
TRANSCRICAO_PID=""
WORKER_OCR_PID=""
WORKER_BACKGROUND_PID=""
BEAT_PID=""
AGENTE_API_PID=""
AGENTE_WORKER_PID=""
CLEANED_UP=0

usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 && !/^#/ { exit }' "$0"
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

import_env_preserve() {
  local file="$1"
  local line name value
  [[ -f "$file" ]] || {
    echo "Arquivo de ambiente ausente: $file. Copie .env.example para .env e preencha os segredos." >&2
    exit 1
  }
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="$(trim "$line")"
    [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *=* ]] && continue
    name="$(trim "${line%%=*}")"
    value="$(trim "${line#*=}")"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z "${!name+x}" ]]; then
      export "$name=$value"
    fi
  done < "$file"
}

import_env_override() {
  local file="$1"
  local line name value
  [[ -f "$file" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="$(trim "$line")"
    [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *=* ]] && continue
    name="$(trim "${line%%=*}")"
    value="$(trim "${line#*=}")"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$name=$value"
  done < "$file"
}

http_ok() {
  curl -fsS --max-time "${2:-3}" "$1" >/dev/null 2>&1
}

# Alguém já escuta em 127.0.0.1:<porta>? Usado antes de subir o agente: dois uvicorn
# no mesmo porto (um em 127.0.0.1, outro em 0.0.0.0) não dão erro no macOS, mas as
# conexões passam a resetar de forma intermitente — e o dossiê recria o caso no
# agente a cada abertura por achar que ele sumiu.
porta_ocupada() {
  python3 - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    print("1")
except OSError:
    print("0")
finally:
    s.close()
PY
}

wait_modelo_aquecido() {
  local url="$1" pid="$2" timeout="$3" deadline
  deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "O processo encerrou durante o aquecimento: $url" >&2
      return 1
    fi
    if curl -fsS --max-time 2 "$url" 2>/dev/null | grep -q '"modelo_aquecido"[[:space:]]*:[[:space:]]*true'; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wait_worker_ocr() {
  local pid="$1" destino="$2" timeout="${3:-120}" deadline resposta status
  deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "O worker de OCR encerrou durante a inicialização." >&2
      return 1
    fi
    set +e
    resposta="$(.venv/bin/python -m celery -A app.celery_app:celery_app inspect ping -d "$destino" --timeout 2 2>&1)"
    status=$?
    set -e
    if [[ "$status" -eq 0 && "$resposta" == *pong* ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

normalizar_debug_python() {
  case "${DEBUG:-}" in
    true|false|True|False|TRUE|FALSE|1|0|yes|no|on|off|"") ;;
    *) export DEBUG=false ;;
  esac
}

diagnostico_jitsi() {
  local url="$1"
  cat <<TXT
Jitsi não respondeu em $url.

Causas prováveis:
  - Docker Desktop ainda não terminou de iniciar;
  - porta 8081 ocupada;
  - JITSI_PUBLIC_URL aponta para outro host;
  - containers do docker-jitsi-meet falharam.

Para rodar sem chamadas temporariamente: ./iniciar.sh --sem-jitsi
TXT
}

kill_if_running() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  [[ "$CLEANED_UP" -eq 0 ]] || return 0
  CLEANED_UP=1
  local pid
  for pid in \
    "$BACKEND_PID" \
    "$TRANSCRICAO_PID" \
    "$WORKER_OCR_PID" \
    "$WORKER_BACKGROUND_PID" \
    "$BEAT_PID" \
    "$AGENTE_API_PID" \
    "$AGENTE_WORKER_PID"
  do
    kill_if_running "$pid"
  done
  wait "$BACKEND_PID" "$TRANSCRICAO_PID" "$WORKER_OCR_PID" "$WORKER_BACKGROUND_PID" "$BEAT_PID" "$AGENTE_API_PID" "$AGENTE_WORKER_PID" 2>/dev/null || true
  echo
  echo "Backend, workers e transcrição encerrados."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod) PROD=1; shift ;;
    --porta) PORTA="${2:?Informe a porta depois de --porta}"; shift 2 ;;
    --sem-auth) SEM_AUTH=1; shift ;;
    --sem-agente) SEM_AGENTE=1; shift ;;
    --sem-jitsi) SEM_JITSI=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

import_env_preserve ".env"

for comando in docker uv npm curl openssl; do
  command -v "$comando" >/dev/null || {
    echo "Dependência ausente: $comando" >&2
    exit 1
  }
done
docker info >/dev/null 2>&1 || { echo "Docker não está respondendo. Abra o Docker Desktop." >&2; exit 1; }

PORTA_BACKEND=8100
PORTA_TRANSCRICAO=8200
HOST_ESCUTA="${APP_BIND_HOST:-0.0.0.0}"
URL_FRONTEND="${APP_PUBLIC_URL:-http://localhost:$PORTA}"
URL_FRONTEND="${URL_FRONTEND%/}"
if [[ "$PORTA" != "3000" && ( "$URL_FRONTEND" == "http://localhost:3000" || "$URL_FRONTEND" == "http://127.0.0.1:3000" ) ]]; then
  URL_FRONTEND="${URL_FRONTEND%:3000}:$PORTA"
fi
URL_API="${OCR_API_PUBLIC_URL:-http://127.0.0.1:$PORTA_BACKEND}"
URL_API="${URL_API%/}"
URL_TRANSCRICAO="${TRANSCRICAO_PUBLIC_URL:-http://127.0.0.1:$PORTA_TRANSCRICAO}"
URL_TRANSCRICAO="${URL_TRANSCRICAO%/}"
URL_JITSI="${JITSI_PUBLIC_URL:-http://localhost:8081}"
URL_JITSI="${URL_JITSI%/}"

if [[ "$SEM_AUTH" -eq 1 ]]; then
  export JWT_SECRET=" "
  export AUTH_DESATIVADA=1
  export NEXT_PUBLIC_AUTH_DESATIVADA=1
  echo "AUTENTICAÇÃO DESLIGADA -- a API responde sem sessão."
else
  export AUTH_DESATIVADA=0
  export NEXT_PUBLIC_AUTH_DESATIVADA=0
  if [[ -z "${JWT_SECRET:-}" ]]; then
    echo "Falta JWT_SECRET no .env. Gere um segredo ou rode com --sem-auth." >&2
    exit 1
  fi
  if [[ "$URL_API" == *127.0.0.1* && "$URL_FRONTEND" == *localhost* ]]; then
    URL_API="${URL_API/127.0.0.1/localhost}"
    echo "API anunciada como $URL_API para preservar cookie de sessão."
  fi
  echo "Login próprio (JWT em cookie HttpOnly)."
fi

echo "Subindo Redis, banco de jobs e observabilidade..."
docker compose up -d --wait --wait-timeout 60 redis jobs-db flower prometheus grafana
export REDIS_URL="redis://127.0.0.1:6380/0"
export CELERY_BROKER_URL="redis://127.0.0.1:6380/0"
export CELERY_RESULT_BACKEND="redis://127.0.0.1:6380/1"
export JOBS_DATABASE_URL="${JOBS_DATABASE_URL:-postgresql://advocacia:advocacia_local@127.0.0.1:5434/advocacia_jobs}"

export NEXT_PUBLIC_OCR_API="${OCR_API_PUBLIC_URL:+$URL_API}"
export NEXT_PUBLIC_TRANSCRICAO_API="${TRANSCRICAO_PUBLIC_URL:+$URL_TRANSCRICAO}"
export ORIGENS_PERMITIDAS="$(printf '%s\n' "http://localhost:$PORTA" "http://127.0.0.1:$PORTA" "$URL_FRONTEND" ${ORIGENS_PERMITIDAS:-} | tr ',' '\n' | sed 's:/*$::' | awk 'NF && !seen[$0]++' | paste -sd, -)"
export URL_PORTAL="$URL_FRONTEND"
export NEXT_PUBLIC_JITSI_URL="$URL_JITSI"

if [[ "$SEM_JITSI" -eq 0 ]]; then
  if ! http_ok "$URL_JITSI/libs/lib-jitsi-meet.min.js" 3; then
    echo "Preparando o servidor de chamadas Jitsi..."
    scripts/preparar_jitsi.sh \
      --versao "${JITSI_IMAGE_VERSION:-stable}" \
      --url-publica "$URL_JITSI" \
      --ips-anunciados "${JITSI_ADVERTISE_IPS:-127.0.0.1}"
  fi
  limite=$((SECONDS + 120))
  while (( SECONDS < limite )); do
    http_ok "$URL_JITSI/libs/lib-jitsi-meet.min.js" 3 && break
    sleep 1
  done
  if ! http_ok "$URL_JITSI/libs/lib-jitsi-meet.min.js" 3; then
    diagnostico_jitsi "$URL_JITSI" >&2
    exit 1
  fi
  echo "Chamadas: $URL_JITSI"
else
  echo "Jitsi não iniciado (--sem-jitsi)."
fi

mkdir -p dados
if [[ ! -f dados/.portal-segredo ]]; then
  openssl rand -base64 32 > dados/.portal-segredo
  chmod 600 dados/.portal-segredo
  echo "Segredo do portal gerado em dados/.portal-segredo"
fi
export PORTAL_SEGREDO="$(tr -d '\r\n' < dados/.portal-segredo)"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Criando ambiente Python..."
  uv venv --python 3.11
fi
uv pip install --python .venv/bin/python -r requirements.txt >/dev/null

if [[ ! -d "frontend/node_modules" ]]; then
  echo "Instalando dependências do frontend..."
  (cd frontend && npm install)
fi

if [[ "$PROD" -eq 1 ]]; then
  echo "Compilando frontend de produção..."
  (cd frontend && npm run build)
fi

if [[ "$SEM_AGENTE" -eq 0 ]]; then
  export AGENTE_API_URL="${AGENTE_API_URL:-http://127.0.0.1:8011}"
  URL_AGENTE="${AGENTE_API_URL%/}"
  PORTA_AGENTE="$(python3 - <<PY
from urllib.parse import urlparse
print(urlparse("$URL_AGENTE").port or 8011)
PY
)"
  # Dá tempo ao agente vizinho de responder antes de concluir que ele não existe.
  # Um único teste de 2s dava falso-negativo quando o ia-juridica ainda estava
  # subindo, e o Acervo abria um SEGUNDO uvicorn no mesmo porto.
  agente_no_ar=0
  for _ in {1..5}; do
    if http_ok "$URL_AGENTE/api/health" 2; then agente_no_ar=1; break; fi
    [[ "$(porta_ocupada "$PORTA_AGENTE")" == "1" ]] || break
    sleep 2
  done
  if [[ "$agente_no_ar" -eq 1 ]]; then
    echo "Agente jurídico já estava no ar: $URL_AGENTE"
  elif [[ "$(porta_ocupada "$PORTA_AGENTE")" == "1" ]]; then
    echo "A porta $PORTA_AGENTE já está ocupada, mas /api/health não respondeu." >&2
    echo "Há um agente subindo (aguarde e rode de novo) ou um processo preso ali:" >&2
    echo "  lsof -tiTCP:$PORTA_AGENTE -sTCP:LISTEN | xargs kill" >&2
    exit 1
  else
    RAIZ_AGENTE="$(cd "$ROOT/../ia-juridica" 2>/dev/null && pwd || true)"
    if [[ -z "$RAIZ_AGENTE" || ! -f "$RAIZ_AGENTE/.env" ]]; then
      echo "Falta ia-juridica/.env ou o repositório vizinho. Use --sem-agente só para diagnóstico isolado." >&2
      exit 1
    fi
    if [[ ! -x "$RAIZ_AGENTE/.venv/bin/python" ]]; then
      echo "Preparando ambiente do Agente Jurídico..."
      (cd "$RAIZ_AGENTE" && uv sync --python 3.12)
    fi
    echo "Aplicando migrations do Agente Jurídico..."
    # Não aborta o Acervo se a migration falhar: o iniciar.ps1 nem roda migrations do
    # agente, e o caso mais comum de falha aqui é o banco do agente estar numa revisão
    # de outra branch (ex.: "Can't locate revision identified by '0018'"). Nesse caso o
    # schema já existe; o que falta é o alembic concordar com a branch atual.
    if ! (
      cd "$RAIZ_AGENTE"
      import_env_override ".env"
      normalizar_debug_python
      export PYTHONPATH=src
      exec .venv/bin/python -m alembic upgrade head
    ); then
      echo "AVISO: 'alembic upgrade head' do Agente Jurídico falhou; seguindo mesmo assim." >&2
      echo "       Se o banco estiver numa revisão de outra branch, rode em ia-juridica:" >&2
      echo "         PYTHONPATH=src .venv/bin/python -m alembic stamp --purge head" >&2
      echo "       (ou 'alembic upgrade head' na branch dona do schema) e reinicie." >&2
    fi
    (
      cd "$RAIZ_AGENTE"
      import_env_override ".env"
      normalizar_debug_python
      export PYTHONPATH=src
      exec .venv/bin/python -m uvicorn legal_agent.main:app --host "$HOST_ESCUTA" --port "$PORTA_AGENTE"
    ) &
    AGENTE_API_PID=$!
    (
      cd "$RAIZ_AGENTE"
      import_env_override ".env"
      normalizar_debug_python
      export PYTHONPATH=src
      exec .venv/bin/python -m dramatiq legal_agent.workers --processes 1 --threads 4
    ) &
    AGENTE_WORKER_PID=$!
    for _ in {1..30}; do
      http_ok "$URL_AGENTE/api/health" 2 && break
      sleep 1
    done
    http_ok "$URL_AGENTE/api/health" 2 || { echo "Agente jurídico não respondeu em $URL_AGENTE." >&2; exit 1; }
    echo "Agente jurídico pronto: $URL_AGENTE"
  fi
else
  URL_AGENTE=""
  echo "Agente Jurídico não iniciado (--sem-agente)."
fi

echo
echo "Backend      : $URL_API (docs em /docs)"
echo "Frontend     : $URL_FRONTEND"
echo "Transcrição  : $URL_TRANSCRICAO"
[[ "$SEM_AGENTE" -eq 0 ]] && echo "Agente       : $URL_AGENTE"
echo "Flower       : http://localhost:5555"
echo "Grafana      : http://localhost:3001"
echo

trap cleanup EXIT
trap 'exit 130' INT TERM

.venv/bin/python -m uvicorn app.main:app --host "$HOST_ESCUTA" --port "$PORTA_BACKEND" --timeout-keep-alive 65 &
BACKEND_PID=$!

INSTANCIA_CELERY="$(openssl rand -hex 4)"
HOST_CELERY="$(hostname)"
WORKER_OCR_NAME="ocr@${HOST_CELERY}-${INSTANCIA_CELERY}"

.venv/bin/python -m celery -A app.celery_app:celery_app worker --pool=solo --concurrency=1 -Q gpu_background -n "$WORKER_OCR_NAME" &
WORKER_OCR_PID=$!
.venv/bin/python -m celery -A app.celery_app:celery_app worker --pool=solo --concurrency=1 -Q ai,documents,default,low -n "background@${HOST_CELERY}-${INSTANCIA_CELERY}" &
WORKER_BACKGROUND_PID=$!
.venv/bin/python -m celery -A app.celery_app:celery_app beat &
BEAT_PID=$!

for _ in {1..90}; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "O backend encerrou durante a inicialização." >&2
    exit 1
  fi
  http_ok "http://127.0.0.1:$PORTA_BACKEND/api/saude" 2 && break
  sleep 0.5
done
http_ok "http://127.0.0.1:$PORTA_BACKEND/api/saude" 2 || { echo "Backend não respondeu em /api/saude." >&2; exit 1; }

echo "Preparando o leitor de documentos..."
if ! wait_worker_ocr "$WORKER_OCR_PID" "$WORKER_OCR_NAME" 180; then
  echo "O worker de OCR não respondeu em 180 segundos." >&2
  exit 1
fi
echo "Leitor de documentos pronto."

echo "Aquecendo transcrição..."
.venv/bin/python -m uvicorn app.servico_transcricao:app --host "$HOST_ESCUTA" --port "$PORTA_TRANSCRICAO" --ws-ping-interval 0 --ws-ping-timeout 0 &
TRANSCRICAO_PID=$!
if ! wait_modelo_aquecido "http://127.0.0.1:$PORTA_TRANSCRICAO/saude" "$TRANSCRICAO_PID" 180; then
  echo "Transcrição não terminou o aquecimento em 180 segundos." >&2
  exit 1
fi
echo "Transcrição pronta."

cd frontend
export PORT="$PORTA"
if [[ "$PROD" -eq 1 ]]; then
  npm run start -- -H "$HOST_ESCUTA"
else
  npm run dev -- -H "$HOST_ESCUTA"
fi
