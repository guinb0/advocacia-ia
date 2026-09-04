# syntax=docker/dockerfile:1
#
# UMA IMAGEM PARA O REPOSITORIO INTEIRO — e por que isso nao e preguica.
#
# O pipeline da casa (components/ci-platform/pipeline-generic) constroi UM
# Dockerfile na raiz e entrega UMA imagem por repositorio; quem vira servicos
# distintos e o compose, trocando o `command`. E assim no dflegal e nos sidaf,
# e este arquivo segue o mesmo contrato em vez de inventar outro.
#
# Aqui dentro moram os quatro processos do Forense:
#   - API (uvicorn app.main)             — porta 8100
#   - transcricao (app.servico_transcricao) — porta 8200
#   - worker + beat (celery)             — sem porta
#   - frontend (Next standalone)         — porta 3000
#
# O frontend e Node e o resto e Python. Em vez de duas imagens (que o pipeline
# nao constroi), o binario `node` e copiado para dentro da imagem Python — o
# build standalone do Next so precisa dele, sem npm nem node_modules.
#
# ARGs `environment` e `VERSION` vem do pipeline (build_args_additional e
# build_args_version), no mesmo formato do dflegal.

# ---------------------------------------------------------------- frontend
FROM node:22-slim AS frontend_builder
ARG environment
ARG VERSION
# NEXT_PUBLIC_* e embutido no bundle NO BUILD — runtime nao muda mais.
# Vazios de proposito: o front usa o host de onde a pagina foi aberta (ver
# frontend/src/lib/api.ts). So preencha via build_args_additional quando api e
# pagina morarem em DOMINIOS diferentes atras do nginx.
ARG NEXT_PUBLIC_OCR_API=""
ARG NEXT_PUBLIC_TRANSCRICAO_API=""
ARG NEXT_PUBLIC_JITSI_URL=""

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1 \
    BUILD_STANDALONE=1 \
    NEXT_PUBLIC_OCR_API=${NEXT_PUBLIC_OCR_API} \
    NEXT_PUBLIC_TRANSCRICAO_API=${NEXT_PUBLIC_TRANSCRICAO_API} \
    NEXT_PUBLIC_JITSI_URL=${NEXT_PUBLIC_JITSI_URL}
RUN npm run build

# ---------------------------------------------------------------- runtime
# 3.11 e teto, nao escolha: o paddlepaddle nao publica wheel para 3.13+
# (mesmo motivo do `uv venv --python 3.11` no iniciar.ps1).
FROM python:3.11-slim
ARG environment
ARG VERSION
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AMBIENTE=${environment} \
    VERSION=${VERSION}

# Postgres-only: o registro dos casos e o de precedentes vivem os dois em
# PostgreSQL — nao ha SQL Server, driver ODBC nem pyodbc na imagem (removidos
# junto com a migracao; ver CONTEXTO.md). O que resta e so o que o resto do
# sistema pede: libglib/libgomp/libgl (paddle e opencv-headless em slim) e
# LibreOffice (gera o PDF/docx dos contratos).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libglib2.0-0 libgomp1 libgl1 \
        libreoffice-writer fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# So o binario. O standalone do Next carrega os proprios node_modules minimos.
COPY --from=frontend_builder /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY sql ./sql
COPY static ./static
# docs/ nao e documentacao morta: os .docx oficiais (contrato, procuracao,
# declaracao) sao lidos dali por app/contrato.py na geracao da papelada.
COPY docs ./docs

COPY --from=frontend_builder /app/frontend/.next/standalone ./frontend
COPY --from=frontend_builder /app/frontend/.next/static ./frontend/.next/static
COPY --from=frontend_builder /app/frontend/public ./frontend/public

# dados/ e o unico estado local (arquivos de casos, contratos assinados,
# segredo do portal). O compose monta volume aqui; o registro esta no SQL
# Server e some da equacao.
RUN adduser --system --uid 1000 appuser \
    && mkdir -p dados logs \
    && chown -R appuser /app
USER appuser

EXPOSE 8100 8200 3000

# O comando padrao e a API; os outros servicos trocam o `command` no compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--timeout-keep-alive", "65"]
