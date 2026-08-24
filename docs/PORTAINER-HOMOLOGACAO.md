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

## Login: sem aplicação separada

O Keycloak saiu. Não há mais aplicação de identidade no Portainer, nem caminho
`/auth/*` para reservar no proxy, nem banco `keycloak` para provisionar — quem
assina a sessão é a própria API (`app/auth.py`) e as contas ficam em
`dbo.acervo_usuarios`, no mesmo banco `advocacia` do resto do sistema.

O proxy volta a ter uma regra só:

```text
https://advocacia.levelhom.com.br/*  -> frontend:3000/*
```

Variáveis da API:

```env
# Gere com: python -c "import secrets; print(secrets.token_urlsafe(48))"
# É o segredo que assina toda sessão: trocá-lo desloga todo mundo na hora.
JWT_SECRET=<segredo-do-Portainer>
JWT_ISSUER=https://advocacia.levelhom.com.br/
JWT_AUDIENCE=https://advocacia.levelhom.com.br/
JWT_HORAS=24

# HTTPS em homologação, então `Secure=1`. `SameSite=lax` basta enquanto frontend
# e API respondem pelo MESMO domínio; em domínios diferentes, use `none` (que
# exige `Secure=1`) e preencha `JWT_COOKIE_DOMAIN` com o domínio pai dos dois.
JWT_COOKIE=JwtToken
JWT_COOKIE_SECURE=1
JWT_COOKIE_SAMESITE=lax
JWT_COOKIE_DOMAIN=

# A conta inicial, criada só quando a tabela está vazia.
ACERVO_ADMIN_EMAIL=admin@advocacia.levelhom.com.br
ACERVO_ADMIN_SENHA=<senha-forte-do-Portainer>

# Precisa listar a origem do frontend: com cookie de sessão em jogo, `*` faz o
# navegador RECUSAR a resposta, e o erro que aparece não menciona cookie nenhum.
ORIGENS_PERMITIDAS=https://advocacia.levelhom.com.br
```

Variáveis usadas no build do frontend:

```env
NEXT_PUBLIC_OCR_API=https://advocacia.levelhom.com.br
NEXT_PUBLIC_AUTH_DESATIVADA=0
```

E, no ambiente de execução do frontend (não é `NEXT_PUBLIC_`, e não deve ser):
o `src/proxy.ts` confere a mesma assinatura antes de servir `/home`, então
precisa do **mesmo** `JWT_SECRET` da API. Com o prefixo público ele iria para o
pacote do navegador e qualquer pessoa poderia forjar sessão.

```env
JWT_SECRET=<o mesmo segredo da API>
```

O proxy deve encaminhar `X-Forwarded-Proto=https`, `X-Forwarded-Host` e
`X-Forwarded-Port=443` — sem `X-Forwarded-Proto` a API não se reconhece atrás de
HTTPS e o cookie `Secure` não gruda.
