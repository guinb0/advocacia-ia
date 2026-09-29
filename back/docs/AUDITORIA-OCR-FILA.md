# Auditoria da fila de OCR

## Arquitetura encontrada

O pipeline usa Python, Celery e Redis/Valkey; não há BullMQ, Node worker ou
RabbitMQ neste fluxo. O upload cria a linha `entregas` no SQL Server com
`status_proc = 'na_fila'`, persiste o binário e então publica
`app.tasks.ocr.processar_entrega` em `gpu_background`.

O worker OCR consome essa fila, marca a entrega como `processando`, executa OCR
em subprocesso `spawn`, persiste o resultado como `pronto` e enfileira somente
o envio posterior ao agente. `task_acks_late`, `task_reject_on_worker_lost` e
prefetch 1 preservam mensagens quando um processo de trabalho é perdido.

## Evidências coletadas

- Em 24/09, depois de um deploy que retomou parte do consumo, a consulta à base
  mostrou 33 entregas em `na_fila` e 8 em `processando`; estas últimas eram
  antigas. Antes do deploy havia 67 aguardando.
- O deploy/restart faz o consumo voltar. Isto indica que upload e persistência
  continuam operacionais e que a falha fica entre broker e consumidor OCR.
- `entregas` não tinha `task_id`, `worker_id`, hora de início/fim nem tentativa.
  Portanto o estado `processando` não permitia provar se a tarefa continuava
  ativa, se o worker morreu ou se a mensagem foi perdida.
- A recuperação existente (`app.tasks.manutencao`) consulta `inspect` e evita
  reenfileirar quando não há consumidor, para não criar cópias. É correta como
  proteção contra duplicidade, mas não recupera o consumidor morto.
- O diagnóstico existente mede `LLEN` e `inspect.active_queues`, mas não mede
  heartbeat por réplica, idade da tarefa ativa, throughput nem último sucesso.

## Hipóteses de causa raiz

| Hipótese | Classificação | Evidência |
| --- | --- | --- |
| Consumidor OCR deixa de consumir embora uploads continuem | Fortemente indicada | Backlog acumulado, itens presos e retomada após restart. |
| Job órfão após queda/restart | Confirmada | Entregas antigas em `processando` sem identidade do worker. |
| OCR/subprocesso ou chamada externa bloqueia o worker | Possível | Há subprocessos e HTTP; havia timeout interno, mas não havia limite específico de task/reciclagem. |
| OOM/vazamento de memória | Possível | Não há logs de container disponíveis nesta máquina para confirmar; o OCR não tinha reciclagem de processo. |
| Redis inacessível/diferente entre API e worker | Possível | O código já trata esse cenário e o diagnóstico o identifica, mas não há log de produção que o confirme. |
| Falha de banco como causa raiz | Não comprovada | A persistência de uploads continuou funcionando durante os incidentes. |

## Proteções já aplicadas

- Três réplicas OCR, concorrência 1 por réplica.
- Limite de memória total da stack em 10 GB; cada OCR limitado a 2 GB.
- Processo filho reciclado por quantidade de tarefas/memória.
- Limites específico de OCR: aviso em 13 min e interrupção em 14 min.
- Supervisor de processo que testa `inspect ping` três vezes e encerra a réplica
  sem resposta para que a política de restart a recrie.
- Worker de manutenção isolado da fila de IA.

## Lacunas que a próxima alteração deve fechar

1. Heartbeat Redis por worker OCR, independente da tarefa em execução.
2. Identidade e tentativa por entrega (`task_id`, `worker_id`, horários).
3. Métrica de progresso: waiting, active, idade do mais antigo, workers
   saudáveis e último OCR concluído.
4. Recuperação de órfão baseada em heartbeat/tarefa ativa, com limite de
   tentativas e logs estruturados.
5. Testes de caos dentro de ambiente Docker com Redis, pois esta estação não
   possui acesso ao broker de produção para matar/inspecionar diretamente os
   containers.

## Operação segura

Nenhuma fila, volume ou documento foi apagado. Não foi executado `FLUSH*`,
remoção de volume ou reset de banco. O rollback do deploy é o rollback da stack
para a release anterior no Portainer/GitLab; os documentos permanecem no SQL
Server e no volume `dados`.

## Fase 2

### Implementado

- Migration aditiva em `acervo_entregas`: `ocr_task_id`, `ocr_worker_id`,
  `ocr_enfileirado_em`, `ocr_iniciado_em`, `ocr_finalizado_em` e
  `ocr_tentativas`.
- O upload grava o UUID da task antes de publicá-la. A task grava hostname do
  worker, início e tentativa de modo compatível com linhas antigas.
- Cada mestre de worker OCR publica `ocr:worker:<id>:heartbeat` a cada 15 s,
  com TTL de 60 s. A thread é independente da task e do subprocesso OCR.
- Snapshot `app.ocr_saude.snapshot`: cruza quantidade Redis, pendências SQL,
  tarefas ativas do Celery, heartbeats, idade e conclusões recentes.

### Regras de classificação

| Estado | Regra |
| --- | --- |
| `HEALTHY` | Sem backlog e broker acessível. |
| `DEGRADED` | Broker indisponível ou backlog com progresso ainda existente. |
| `STALLED` | Backlog com mais de 5 min, sem conclusão nos últimos 5 min e consumidores presentes. |
| `NO_CONSUMERS` | Backlog e nenhum heartbeat OCR válido. |
| `POSSIBLE_HUNG_TASK` | Task ativa com processamento acima de 13 min. |

### Testes realizados

- `python -m pytest tests/test_ocr_saude.py` e cenários unitários de requeue:
  **9 aprovados**.
- Compilação dos módulos alterados e validação do Compose: **aprovadas**.
- A execução completa de `test_entregas_travadas.py` ficou bloqueada por uma
  dependência local ausente (`prometheus_client`) em testes que importam a API;
  não é falha da fila.
- Testes de caos Docker/Redis reais **não foram executados**: o Docker Engine
  não está disponível nesta estação e não existe `redis-server` local. Não foi
  simulado como se fosse produção.

### Resultado e riscos restantes

O teste obrigatório de desconectar Redis por 30–60 segundos ainda precisa ser
executado num host Docker com Valkey da stack. Sem ele não é possível afirmar
que o consumidor Celery retoma após reconexão sem restart manual. Por essa
razão, a Fase 2 não está aprovada para deploy e não houve novo deploy.

# Fase 3 — Chaos validation

## Ambiente

`prometheus-client>=0.21,<1` já está declarado em `requirements.txt`; não há
falha de declaração de dependência. A ausência ocorreu no interpretador Python
local, que não foi provisionado a partir do requirements do projeto. Não foi
adicionada instalação manual como suposta correção.

O Docker Engine desta estação está indisponível (`dockerDesktopLinuxEngine`/
`docker_engine` não responde), não existe contexto remoto configurado e não há
`redis-server` local. Portanto não existe host Docker isolado acessível para a
stack exigida pela Fase 3.

## Resultados

| Teste | Resultado | Evidência |
| --- | --- | --- |
| Baseline: 3 workers + 20 jobs | BLOCKED | Sem Docker/Valkey isolado. |
| Matar uma réplica | BLOCKED | Sem containers de teste. |
| Matar três réplicas / `NO_CONSUMERS` | BLOCKED | Sem containers de teste. |
| Backlog de 50 jobs | BLOCKED | Sem broker de teste. |
| OCR fake HANG/CRASH | BLOCKED | Requer worker Celery real isolado. |
| Redis down por 60 s e reconexão | BLOCKED | Não foi possível iniciar/parar Valkey isolado. |
| Recuperação de órfão / duplicidade | BLOCKED | Depende dos cenários anteriores. |
| Classificação unitária do snapshot | PASS | 6 cenários unitários; conjunto alvo de 9 testes passou. |

## Timeline Redis

Não há timeline real: nenhum Redis de teste foi iniciado. Inventar timestamps
ou declarar reconexão sem observar um consumer real esconderia justamente a
causa que esta validação procura.

# Fase 4 — Correção da causa raiz (2026-09-24)

## Causa raiz confirmada

As tabelas `dbo.acervo_fila_jobs` e `dbo.acervo_fila_workers` existiam, mas
`fila_jobs` / `fila_workers` **não estavam** em `banco.TABELAS`. O `_qualificar`
não reescrevia o SQL; o enqueue falhava com "nome de objeto inválido"; a API
mascarava qualquer exceção como **"Fila de OCR indisponível."** e marcava a
entrega em `erro`. A fila SQL ficava vazia (0 jobs) enquanto centenas de
entregas morriam no upload.

## Correção

1. Incluir `fila_jobs` e `fila_workers` em `banco.TABELAS`.
2. Default `FILA_SQL_OCR_ATIVA=1` (SQL é o transporte de OCR).
3. Mensagens de erro reais no enqueue (sem máscara genérica).
4. UI distingue pending / processing / failed / classificado.
5. Retry SQL sincroniza `entregas` (`na_fila` no backoff; `erro` só no FAILED).
6. Logs estruturados: UPLOAD → OCR_QUEUED → OCR_CLAIMED → OCR_STARTED →
   OCR_COMPLETED → CLASSIFICATION_* .

## Evidência

- Integração no SQL remoto: enqueue + dedup + claim (2º worker = None) +
  COMPLETED → OK.
- `pytest tests/test_fila_sql.py` + alertas: 15 passed.

