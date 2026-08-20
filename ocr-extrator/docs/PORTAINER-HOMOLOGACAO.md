# Homologação no Portainer

## OpenTelemetry / Grafana

Definir na API e nos workers Celery:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=advocacia-api
OTEL_SERVICE_VERSION=<versao-da-imagem-ou-commit>
```

O nome identifica o serviço nos traces e a versão separa os deploys. O Grafana
do compose consome métricas do Prometheus; traces OTLP exigem um Collector com
destino Tempo/OTLP disponível na infraestrutura.

## Keycloak separado

O Keycloak é uma aplicação própria no Portainer e administra o realm
`advocacia`. Como o domínio também atende o frontend, o proxy precisa reservar
um caminho para a porta 8180:

```text
https://advocacia.levelhom.com.br/auth/*  -> keycloak:8180/auth/*
https://advocacia.levelhom.com.br/*       -> frontend:3000/*
```

Variáveis do container Keycloak:

```env
KC_HTTP_PORT=8180
KC_HTTP_RELATIVE_PATH=/auth
KC_PROXY_HEADERS=xforwarded
KC_HOSTNAME=https://advocacia.levelhom.com.br/auth
KC_HEALTH_ENABLED=true
```

Variáveis da API:

```env
KEYCLOAK_URL=https://advocacia.levelhom.com.br/auth
KEYCLOAK_PUBLIC_URL=https://advocacia.levelhom.com.br/auth
KEYCLOAK_INTERNAL_URL=http://keycloak:8180/auth
KEYCLOAK_REALM=advocacia
KEYCLOAK_CLIENT_ID=acervo-frontend
KEYCLOAK_AUDIENCE=acervo-api
```

Variáveis usadas no build do frontend:

```env
NEXT_PUBLIC_KEYCLOAK_URL=https://advocacia.levelhom.com.br/auth
NEXT_PUBLIC_KEYCLOAK_REALM=advocacia
NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=acervo-frontend
```

Configuração do cliente `acervo-frontend` no realm:

```text
Valid redirect URIs: https://advocacia.levelhom.com.br/*
Web origins:         https://advocacia.levelhom.com.br
Root/Home URL:       https://advocacia.levelhom.com.br
```

O proxy deve encaminhar `X-Forwarded-Proto=https`, `X-Forwarded-Host` e
`X-Forwarded-Port=443`. A URL interna nunca vai para o JavaScript; ela serve
somente para a API buscar JWKS e administrar usuários.
