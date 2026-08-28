#!/usr/bin/env bash
# Prepara e sobe o docker-jitsi-meet oficial no macOS/Linux.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINO="$(cd "$SCRIPT_DIR/../../.." && pwd)/docker-jitsi-meet"
VERSAO="stable"
PORTA_HTTP=8081
URL_PUBLICA="http://localhost:8081"
IPS_ANUNCIADOS="127.0.0.1"

usage() {
  cat <<'TXT'
Uso: scripts/preparar_jitsi.sh [opções]

  --destino PATH
  --versao TAG
  --porta-http PORTA
  --url-publica URL
  --ips-anunciados LISTA
TXT
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destino) DESTINO="${2:?Informe o destino}"; shift 2 ;;
    --versao) VERSAO="${2:?Informe a versão}"; shift 2 ;;
    --porta-http) PORTA_HTTP="${2:?Informe a porta}"; shift 2 ;;
    --url-publica) URL_PUBLICA="${2:?Informe a URL pública}"; shift 2 ;;
    --ips-anunciados) IPS_ANUNCIADOS="${2:?Informe os IPs anunciados}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

novo_segredo() {
  openssl rand -base64 32 | tr -d '+/='
}

definir_env() {
  local arquivo="$1" nome="$2" valor="$3" tmp
  tmp="$(mktemp)"
  if grep -Eq "^[[:space:]]*#?[[:space:]]*${nome}=" "$arquivo"; then
    awk -v nome="$nome" -v valor="$valor" '
      $0 ~ "^[[:space:]]*#?[[:space:]]*" nome "=" { print nome "=" valor; next }
      { print }
    ' "$arquivo" > "$tmp"
  else
    cat "$arquivo" > "$tmp"
    printf '%s=%s\n' "$nome" "$valor" >> "$tmp"
  fi
  mv "$tmp" "$arquivo"
}

command -v git >/dev/null || { echo "Git não encontrado." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker não encontrado." >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl não encontrado." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker não está respondendo. Abra o Docker Desktop." >&2; exit 1; }

mkdir -p "$(dirname "$DESTINO")"
if [[ ! -f "$DESTINO/docker-compose.yml" ]]; then
  echo "Baixando o docker-jitsi-meet oficial..."
  git clone --depth 1 https://github.com/jitsi/docker-jitsi-meet.git "$DESTINO"
fi

arquivo_env="$DESTINO/.env"
novo_ambiente=0
if [[ ! -f "$arquivo_env" ]]; then
  [[ -f "$DESTINO/env.example" ]] || { echo "env.example do Jitsi não encontrado em $DESTINO." >&2; exit 1; }
  cp "$DESTINO/env.example" "$arquivo_env"
  novo_ambiente=1
fi

definir_env "$arquivo_env" CONFIG "./.jitsi-meet-cfg"
definir_env "$arquivo_env" HTTP_PORT "$PORTA_HTTP"
definir_env "$arquivo_env" HTTPS_PORT "8444"
definir_env "$arquivo_env" PUBLIC_URL "$URL_PUBLICA"
definir_env "$arquivo_env" JVB_ADVERTISE_IPS "$IPS_ANUNCIADOS"
definir_env "$arquivo_env" JITSI_IMAGE_VERSION "$VERSAO"
if [[ "$URL_PUBLICA" == https://* ]]; then
  definir_env "$arquivo_env" DISABLE_HTTPS "0"
else
  definir_env "$arquivo_env" DISABLE_HTTPS "1"
fi
definir_env "$arquivo_env" ENABLE_XMPP_WEBSOCKET "1"
definir_env "$arquivo_env" ENABLE_AUTH "0"
definir_env "$arquivo_env" ENABLE_GUESTS "1"

if [[ "$novo_ambiente" -eq 1 ]]; then
  for nome in \
    JICOFO_AUTH_PASSWORD \
    JVB_AUTH_PASSWORD \
    JIGASI_XMPP_PASSWORD \
    JIBRI_RECORDER_PASSWORD \
    JIBRI_XMPP_PASSWORD
  do
    definir_env "$arquivo_env" "$nome" "$(novo_segredo)"
  done
  echo "Configuração local do Jitsi criada em $arquivo_env"
fi

mkdir -p \
  "$DESTINO/.jitsi-meet-cfg/web" \
  "$DESTINO/.jitsi-meet-cfg/storage/web" \
  "$DESTINO/.jitsi-meet-cfg/storage/transcripts" \
  "$DESTINO/.jitsi-meet-cfg/tmp/web-crontabs" \
  "$DESTINO/.jitsi-meet-cfg/tmp/web-load-test" \
  "$DESTINO/.jitsi-meet-cfg/prosody/config" \
  "$DESTINO/.jitsi-meet-cfg/prosody/prosody-plugins-custom" \
  "$DESTINO/.jitsi-meet-cfg/storage/prosody" \
  "$DESTINO/.jitsi-meet-cfg/jicofo" \
  "$DESTINO/.jitsi-meet-cfg/jvb"

(cd "$DESTINO" && docker compose up -d)
printf '%s\n' "$DESTINO"
