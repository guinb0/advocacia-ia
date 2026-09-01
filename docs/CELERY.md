# Processamento assíncrono

O OCR não ocupa mais a requisição HTTP do frontend. `POST /api/extrair/jobs`
grava o upload temporário, cria uma linha em `jobs`, publica na fila
`gpu_background` e responde `202`. O cliente consulta `GET /api/jobs/{id}` até
`COMPLETED` ou `FAILED`. A rota síncrona antiga permanece durante a transição.

## Componentes

- Redis 7 com AOF: broker (`/0`) e resultados efêmeros (`/1`), exposto em 6380
  para não colidir com outros projetos da estação.
- PostgreSQL local na porta 5434: estado durável, progresso, erro e resultado
  na tabela `jobs`. Ele é separado do pgvector remoto para o OCR não depender
  da conectividade da base jurisprudencial.
- Worker `ocr`: `gpu_background`, concorrência 1.
- Worker `background`: `ai`, `documents`, `default` e `low`, concorrência 1.
- Whisper: permanece quente em `servico_transcricao.py`; não há um job por frame.
- Redis lock `gpu:0`: compartilhado pelo Whisper e pelo OCR quando
  `OCR_USA_GPU=1`. Com a configuração medida atual, PaddleOCR continua em CPU.
- Beat: limpa temporários a cada hora e marca jobs abandonados a cada 15 minutos.

## Operação local

`iniciar.ps1` sobe Redis, workers, Beat, API, frontend, Whisper e os painéis.

- App: <http://localhost:3000>
- API: <http://127.0.0.1:8100/docs>
- Flower: <http://localhost:5555>
- Prometheus: <http://localhost:9090>
- Grafana: <http://localhost:3001>
- Métricas da API: <http://127.0.0.1:8100/metrics>

Variáveis obrigatórias: `DATABASE_URL` (ou `JOBS_DATABASE_URL`) e as
credenciais `SQLSERVER_*` exigidas pelo Acervo. Redis usa localhost por padrão.
Sentry e OTLP só são ligados quando seus respectivos endpoints são definidos.

## Filas e prioridade

| Trabalho | Fila | Comportamento |
|---|---|---|
| Streaming Whisper | serviço quente | prioridade realtime, sem overhead Celery |
| OCR | `gpu_background` | ack tardio, prefetch 1, retry exponencial |
| IA não realtime | `ai` | isolada do OCR |
| PDF/documentos | `documents` | CPU normal |
| Limpeza/agendamentos | `low` | disparada pelo Beat |

Para escalar, execute os mesmos comandos de worker em outra máquina apontando
`CELERY_BROKER_URL` para o Redis compartilhado. Workers GPU devem manter
concorrência 1 e compartilhar uma chave de lock por GPU física. Não é necessário
alterar a API.

## Estados

`QUEUED → STARTED → PROCESSING → COMPLETED`, ou `FAILED`. Uma tentativa repetida
volta a `STARTED`. O resultado Celery expira; o registro PostgreSQL não.
