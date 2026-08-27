# syntax=docker/dockerfile:1
#
# UMA IMAGEM PARA O REPOSITORIO INTEIRO — e por que isso nao e preguica.
#
# O pipeline da casa (components/ci-platform/pipeline-generic) constroi UM
# Dockerfile na raiz e entrega UMA imagem por repositorio; quem vira servicos
# distintos e o compose, trocando o `command`. E assim no dflegal e nos sidaf,
# e este arquivo segue o mesmo contrato em vez de inventar outro.
#
# Aqui dentro moram os quatro processos do Acervo:
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

# msodbcsql18: o registro dos casos vive num SQL Server e o pyodbc precisa do
# driver da Microsoft — nao ha wheel que o traga. O Driver 18 liga criptografia
# por padrao e o servidor atual nao tem certificado; o compose resolve com
# SQLSERVER_DRIVER, sem tocar em codigo (app/banco.py ja le a variavel).
# libglib/libgomp/libgl: o que paddle e opencv-headless pedem em slim.
#
# `libgssapi-krb5-2` aparece explicito, e nao por tabela, porque ela entra como
# dependencia do curl e o `autoremove` la embaixo a levava embora DEPOIS de o
# driver ja estar instalado. O sintoma engana: o unixODBC diz "file not found"
# apontando para o .so do driver, que esta la — quem falta e esta biblioteca
# que ele carrega. Listada aqui, o apt a marca como manual e o autoremove nao
# toca nela. Medido: sem esta linha, `pyodbc.connect` falha na imagem.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 ca-certificates libglib2.0-0 libgomp1 libgl1 \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 unixodbc libgssapi-krb5-2 libreoffice-writer fonts-liberation \
    && apt-get purge -y curl gnupg2 && apt-get autoremove -y \
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
