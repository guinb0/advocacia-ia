# Acervo — onde o projeto está

## Checkpoint da vetorização — medido em 13/08/2026, 14h

Confira sozinho, a qualquer momento, em vez de confiar nos números abaixo:

```powershell
.venv\Scripts\python.exe -m scripts.estado_rag
.venv\Scripts\python.exe -m scripts.estado_rag --busca "acidente com o dedo na máquina"
```

O `--busca` prova o caminho inteiro (texto → embedding → HNSW → processo) e é o
único que gasta uma chamada de embeddings.

**Estado:** 5.824 documentos / 52.926 chunks / 1.745 processos.
**42.490 embeddings (80,28%)**, 10.436 pendentes.

| origem | vetorizados |
|---|---|
| `trt8_juris` | 42.490 / 43.106 (98,57%) |
| `tst` | 0 / 5.122 |
| `djen` | 0 / 4.660 |
| `dejt` | 0 / 38 |

O TRT8 está praticamente pronto; o que falta é inteiro das outras três fontes,
que ainda não começaram. A busca por similaridade já funciona — a conferência da
entrevista cita processos —, só não alcança precedente do TST.

**A tarefa NÃO está desabilitada**, ao contrário do que este documento dizia
até 13/08. `AdvocaciaIA-SincronizarRAG` está `Ready`, com execução agendada, e
rodou em 13/08 às 09:27 (terminada: `LastTaskResult` 0x41306). Ela volta a rodar
sozinha.

### A retomada que travava em silêncio — corrigida em 13/08/2026

Medido antes da correção: um `scripts.vetorizar_pendentes --lote 64` iniciado às
13:46:53 seguia vivo 25 minutos depois com **1,1s de CPU acumulada, zero bytes de
log e a contagem parada** em 42.490, com a conexão `Established` desde 13:46:54.
Ele conectou e ficou pendurado esperando uma resposta que nunca veio.

Eram dois defeitos somados, e cada um sozinho já bastava:

1. **Nada tinha prazo depois da conexão aberta.** O `connect_timeout` cobre só o
   aperto de mão; uma leitura que não retorna bloqueia para sempre. Agora a
   conexão leva `keepalives` (o sistema derruba a conexão morta em ~1 min) e
   `statement_timeout=180s` (o servidor aborta a consulta que se arrasta).
2. **O `while True` do `main()` impedia o processo de sair** — e o
   `sincronizar-rag.ps1`, que tem 30 retentativas com log timestampado, só age
   quando o Python termina com código diferente de zero. Duas camadas de
   retentativa, e a de dentro anulando a de fora. Agora são `--tentativas 5`
   (configurável) e `sys.exit(1)` ao desistir.

Também: cada lote imprime com data e hora. É o que separa "está devagar" de
"está pendurado desde as 13h46" ao ler o log depois.

### A causa que estava embaixo de tudo: transações órfãs

Medido em 13/08, às 14h47, em `pg_stat_activity`: **oito** sessões `active` com
`UPDATE knowledge_chunks`, transação aberta há até **1h56**, quase todas em
`wait_event = Client/ClientRead` — o servidor terminou e espera um cliente que
morreu. Cinco delas usavam `SET embedding=$1 WHERE id=$2`, uma linha por vez:
forma de uma versão do script anterior ao UPDATE em lote, ou seja, de execuções
bem antigas.

Elas travavam umas às outras em cadeia e travavam qualquer coisa nova na tabela.
A prova: o `CREATE INDEX` ficou 5 minutos esperando e, encerradas as órfãs,
completou em **0,06s**. Não era lentidão do servidor — era lock.

Por que se acumulam: matar o cliente não encerra a transação no servidor. Sem
keepalive do lado de lá, o backend fica em `ClientRead` para sempre. Toda vez
que uma vetorização for morta à força, convém conferir:

```sql
SELECT pid, now()-xact_start AS idade, wait_event_type, wait_event, query
  FROM pg_stat_activity
 WHERE datname = current_database() AND query ILIKE '%UPDATE knowledge_chunks%'
   AND xact_start < now() - interval '10 minutes';
-- e então, para cada pid:  SELECT pg_terminate_backend(<pid>);
```

Encerrá-las é seguro: o trabalho volta atrás, os chunks voltam a
`embedding IS NULL` e o vetorizador os refaz. É para isso que a carga é
idempotente.

**`idle_in_transaction_session_timeout` NÃO resolve isto** — e vale registrar por
quê, porque é a primeira ideia que ocorre a qualquer um:

- o servidor **já** o tem em **30s**, vindo da linha de comando do Postgres
  (`pg_settings.source = 'command line'`), valendo para todos os papéis;
- e mesmo assim as órfãs sobreviveram duas horas, porque ele só alcança sessões
  em estado `idle in transaction`. As nossas apareciam como `active` esperando em
  `Client/ClientRead` — o servidor as considera ocupadas, não ociosas.

Em 13/08 chegou-se a aplicar, no papel do `PGVECTOR_USER`, um
`ALTER ROLE … SET idle_in_transaction_session_timeout = '10min'`, e foi
**revertido na hora**: como o padrão do servidor já era 30s, aquilo afrouxava a
proteção existente em vez de criar uma. Hoje `pg_roles.rolconfig` está nulo para
todos os papéis, e é assim que deve ficar.

Os `keepalives` que o script passou a usar (acima) atacam o lado do cliente e são
a defesa que de fato existe. Do lado do servidor, o que restaria seria
`tcp_keepalives_idle` no `postgresql.conf` — que é global e não é só nosso.

### E a razão de o SELECT ser caro — `sql/003_indice_pendentes.sql`

Os dois defeitos acima explicavam por que a falha era **silenciosa**; não
explicavam por que ela acontecia. O plano do `SELECT` que pede o próximo lote
era percorrer a chave primária em ordem de id filtrando `embedding IS NULL`:

```
Index Scan using knowledge_chunks_pkey   Filter: (embedding IS NULL)
```

Os pendentes ocupavam os ids **42497 a 52932** — todos no fim da tabela. Cada
lote de 64 varria os ~42.490 já prontos antes de achar o primeiro pendente, e o
custo **cresce com o progresso**: quanto mais vetorizado, mais linhas pular. Com
a tabela em cache isso levava 0,48s; com cache frio ou o servidor sob carga,
passava dos 180s e a vetorização parava sozinha.

O índice parcial `ix_chunks_pendentes (id) WHERE embedding IS NULL` inverte a
curva: ele encolhe conforme a vetorização avança, e some quando ela termina.
Aplicado **só no `advocacia_ia`** — o servidor é compartilhado, e o arquivo em
`sql/` começa mandando conferir `current_database()`.

Sem `CONCURRENTLY` de propósito: com esta conexão, um `CONCURRENTLY` interrompido
deixa índice INVÁLIDO para trás. O `CREATE INDEX` comum é atômico — caindo a
conexão, não sobra nada.

Como reconhecer o sintoma, se voltar: processo vivo, log parado, CPU que não
cresce, contagem congelada.

```powershell
Get-Process -Id <pid> | Select-Object CPU        # não cresce
Get-NetTCPConnection -OwningProcess <pid>        # Established e velha
```

### Retomar

```powershell
Get-Process python | Where-Object { $_.CPU -lt 5 }   # confira travados antes
Start-ScheduledTask -TaskName 'AdvocaciaIA-SincronizarRAG'
```

Ou só a vetorização, sem reingerir:

```powershell
.venv\Scripts\python.exe -m scripts.vetorizar_pendentes --lote 64 --tentativas 20
```

A carga é idempotente e retoma pelos chunks cujo `embedding IS NULL`; não é
necessário apagar nem reingerir nada.

### Sobre a "instabilidade"

O servidor é remoto e compartilhado. Medido em 13/08: sondagens TCP seguidas
respondendo em 0,06s, e no meio delas conexões levando **7,09s** ou estourando
por completo. **Não é queda — é latência que varia uma ordem de grandeza**, e é
por isso que a conexão costuma dar certo na segunda tentativa.

Foi essa medição que calibrou o disjuntor de `app/analise_resposta.py`: 3s de
prazo e abertura na primeira falha descartavam precedente por causa de um pico,
com o banco vivo. Passou a 6s, abrindo só na **segunda falha seguida**, com 90s
de descanso em vez de 300 — um sucesso no meio zera a contagem. Ver a seção da
conferência mais abaixo.

Documento de passagem de bastão. Descreve o que existe, o que foi decidido e
por quê, e o que ficou pela metade. Atualizado em 13/08/2026.

---

## O que o sistema faz

Escritório trabalhista/previdenciário. O fluxo é:

```
entrevista → triagem (categoria) → caso → checklist de documentos
   → cliente envia pelo portal → OCR valida → pedido do que falta
```

**Stack:** FastAPI + PaddleOCR (Python 3.11) · Next.js 16 + TypeScript (CSS
Modules, sem Tailwind) · SQLite local · Keycloak em container · PostgreSQL com
pgvector (remoto).

**Subir tudo:** `.\iniciar.ps1` — sobe Keycloak, backend (:8100) e frontend
(:3000). `-SemAuth` desliga a autenticação e dispensa o Docker.
Login: `guinb` / `123`.

---

## Como está organizado

```
app/
  main.py         rotas; middleware de auth por allowlist
  contrato.py     preenche o modelo .docx do escritório (não redige cláusula)
  assinatura.py   manda assinar na ZapSign e acompanha quem já assinou
  triagem.py      classifica a entrevista (LLM + fallback local)
  casos.py        status derivado do checklist; visão do cliente
  extractors.py   extração de campos dos documentos
  pipeline.py     OCR → campos → validação
  quality.py      legibilidade da foto
  portal.py       senha/sessão do portal do cliente
  armazenamento.py  SQLite
frontend/
  app/page.tsx              Carteira · Checklist · análise avulsa
  app/portal/[token]/       portal público do cliente
  components/Carteira.tsx   tela principal
  lib/triagem, auth, api    clientes e hooks
sql/001_criar_banco_vetorial.sql   schema do pgvector (já aplicado)
tests/avaliar_triagem.py           mede a triagem com relatos gerados por LLM
```

---

## Decisões que não são óbvias no código

**Direção visual.** Escura, tipografia editorial (Newsreader/Archivo/IBM Plex
Mono), cantos retos, elevação por borda. É a direção "AUTOS" do `GUIA-LAYOUT.md`
misturada com a paleta da "PLANTÃO". O guia proíbe explicitamente: azul #3B82F6,
Inter, sidebar escura, cards com sombra, chat flutuante de IA.

**Upload é assíncrono.** O POST responde em ~0,3s e o OCR roda em thread de
fundo; a tela faz polling enquanto houver item `processando`. Antes a requisição
ficava presa até 200s e morria por timeout no celular do cliente.

**OCR leva 10-14s com a máquina livre e ~200s quando ela satura.** Medido. Foram
testadas e **descartadas por medição**: reduzir resolução (6% de ganho, perde
texto), desligar o classificador de orientação (0% de ganho, perde 15 blocos),
trocar para modelo mobile (2× mais lento), limitar `cpu_threads` (pior em 4, 6 e
8). O gargalo é CPU/RAM da máquina, não o código.

**CNH e CIN valem para RG e CPF ao mesmo tempo.** Decidido pelos campos
realmente extraídos, não pelo tipo detectado. Cartão de CPF fica de fora: não
carrega RG, e marcá-lo daria a identidade por entregue sem documento de
identidade no caso.

**Nos itens RG/CPF o tipo não é forçado na extração.** Forçar "cpf" numa CNH
impedia a leitura do RG — medido.

**Validação cruzada de datas.** `nascimento < emissão ≤ validade`. Cada data
isolada podia ser válida e o conjunto impossível; o documento saía aprovado.

**Filiação é rótulo neutro.** O documento não diz qual é mãe e qual é pai; o
campo saía trocado.

---

## Triagem da entrevista

`POST /api/triagem` recebe texto colado ou `.txt` e devolve o ranking de
categorias com a justificativa. **Não cria caso** — quem confirma é o advogado.

O classificador principal é o **DeepSeek** (`app/triagem.py`, constante
`INSTRUCAO`). Ele interpreta: reconheceu "entrega correspondência para a
estatal" como Correios sem a palavra aparecer.

**As regras do escritório vivem na `INSTRUCAO`** — é lá que se ensina o critério,
não em código:
- Terceirizado acidentado dentro da ECT → categoria dos Correios (tomadora).
- Acidente de trajeto → mesmo checklist do acidente comum.
- Doença crônica + acidente súbito juntos → não decidir sozinho.

**Três travas em código, porque prompt é melhor-esforço.** No teste o modelo
respondia `duvida: false` num relato que tinha doença crônica E acidente:
1. porta de confiança (≥0,75 e sem dúvida declarada);
2. divergência entre o modelo e o classificador local;
3. detecção de quadro crônico + acidente pontuando forte no mesmo texto.

**Medição** (`python -m tests.avaliar_triagem 4`): modelo **90%**, termos locais
**71%**, sobre relatos gerados por LLM. Os testes escritos à mão davam 100% e não
provavam nada — mesmo autor das pistas e dos testes.

> Ressalva: 90% é sobre relato **sintético**. Com entrevistas reais rotuladas o
> número muda. A tabela `entrevistas` no pgvector existe para coletar isso.

---

## Banco vetorial — criado e VAZIO

```
10.200.1.1:5432 / advocacia_ia    PostgreSQL 18.3
extensões: vector 0.8.2, pg_trgm, unaccent
```

| tabela | para quê |
|---|---|
| `fontes` | procedência (lei, súmula, jurisprudência) |
| `knowledge_chunks` | trechos + `vector(1536)`, índice HNSW cosseno |
| `entrevistas` | relato + categoria sugerida **e a confirmada pelo advogado** |

Testado: busca por similaridade responde e usa o índice HNSW (`Index Scan`, não
seq scan). Cascade de `fontes` → `knowledge_chunks` funciona.

**Nada no código Python usa este banco ainda.** Faltam três peças:
1. **Ingestor** de legislação (Planalto não tem API — será raspagem ou PDF).
2. **Gerador de embeddings** (chave do OpenRouter já está no `.env`).
3. **Ligação com a triagem**: buscar trechos e passar ao modelo junto do relato,
   para fundamentar a classificação em lei.

Dimensão 1536 escolhida para casar com `gemini-embedding-001`. **Trocar de modelo
depois obriga a recriar as colunas e reindexar.**

---

## Segurança — o que está resolvido e o que não está

**Resolvido**
- Senha do portal: 50 bits por CSPRNG, guardada como PBKDF2-SHA256 com sal,
  5 tentativas por 15 min. Aparece uma vez só, na geração.
- Hash e sal nunca saem pela API (`_sem_segredos` em `armazenamento.py`).
- Sessão do portal em `sessionStorage`, token do Keycloak só em memória.
- CORS restrito por lista; middleware fecha rota nova por padrão.
- Cliente do portal não vê alertas internos do OCR nem os campos extraídos.

**Pendente**
- **Credenciais a rotacionar**: o banco de produção `Visarj` (SES-RJ), o
  `JWT_SECRET` do vig-agent, as chaves DeepSeek e OpenRouter, a senha do
  PGVector e o **token da ZapSign** (`ZAPSIGN_API_TOKEN`, posto em 13/08/2026).
  Todas passaram por chat. O da ZapSign é o mais sensível da lista: com ele se
  cria e se lê **qualquer** documento da conta do escritório — contrato de
  cliente, com CPF e qualificação — e se gasta o plano de assinaturas.
- **Senhas de desenvolvimento estão no repositório público**: `guinb/123` no
  `keycloak/realm-advocacia.json` e `admin/admin` no `docker-compose.yml`.
  Decisão consciente do dono, mas o repo `guinb0/advocacia-ia` é público.
- **HTTP puro.** O link do portal trafega senha em claro. Exige HTTPS antes de
  sair da máquina.
- **Servidor pgvector é compartilhado** com `visadf`, `vigdigital_agent`,
  `portos_prod` e outros. Relato de entrevista tem CPF e dado de saúde — decidir
  retenção e base legal na LGPD antes de popular a tabela `entrevistas`.

---

## O que está quebrado ou faltando

- **README** ainda é o template do GitLab; não documenta o setup real.
- **`pytest` não está instalado** no venv — a suíte em `tests/` nunca rodou nesta
  máquina. Só os scripts avulsos foram executados.
- **Telas antigas não migraram** para a direção visual: `PainelEnvio`,
  `Resultado` e os painéis de validação/qualidade herdaram a paleta pelos
  apelidos de token, mas mantêm cantos arredondados.
- **Pré-filtro de nitidez não implementado.** O Laplaciano já é calculado, mas
  *depois* do OCR. Rodar antes custaria ~119ms contra 12s de OCR e cortaria foto
  tremida na entrada. Falta amostra de foto ruim para calibrar o limiar.
- **`ProgressoOcr` aceita `naFila`** mas ninguém passa: o `useSituacao` envia um
  documento por vez e não expõe fila.

---

## Comandos

```powershell
.\iniciar.ps1                  # tudo: Keycloak + backend + frontend
.\iniciar.ps1 -SemAuth         # sem Keycloak (dispensa Docker)
.\iniciar.ps1 -Porta 3100      # outra porta do front

docker compose up -d keycloak  # só o Keycloak

.venv\Scripts\python.exe -m tests.avaliar_triagem 4   # mede a triagem
cd frontend; npm run typecheck; npm run build
```

**Repositórios:** GitLab `ia/advocacia-ia` (origin) e GitHub `guinb0/advocacia-ia`
(github, **público**). `git push origin main` e `git push github main`.

---

## Conferência da resposta durante a entrevista — 13/08/2026

`app/analise_resposta.py` + `POST /api/entrevista/analise`. Ao fechar uma
resposta **narrativa** (as marcadas `transcrever` no roteiro), a tela mostra
embaixo da própria pergunta o que ela não trouxe: até 3 lacunas e até 3 perguntas
**prontas para ler em voz alta** ao cliente.

Dispara em dois momentos: ao finalizar a gravação e ao sair da caixa de texto
(o equivalente digitado de "finalizar"). Nunca a cada tecla — seria uma chamada
ao modelo por letra.

**Por que não é o `/api/estrategia`.** Aquele produz um parecer por caso, lido com
calma. Este roda uma vez por PERGUNTA, várias por entrevista. O que cabe entre
uma pergunta e a seguinte são três itens; mais que isso não é lido, e o que não é
lido não é conferido. Daí `max_tokens: 500`, 4 precedentes e listas cortadas em 3.

**O banco de precedentes é instável, não morto** (ver o checkpoint no topo).
Duas defesas, calibradas pela medição de 13/08:

1. **Prazo que cabe no pico** — 6s para conectar e para o embedding, contra os
   120s/10s da ingestão. `rag.buscar_similares` e `gerar_embeddings` ganharam
   esses parâmetros; o padrão continua o de antes. Foram 3s até se medir que o
   servidor às vezes leva 7,09s **e responde**.
2. **Disjuntor que distingue pico de queda** — abre na 2ª falha **seguida** e
   descansa 90s; um sucesso no meio zera a contagem. Sem ele, cada pergunta da
   entrevista pagaria o timeout de novo. Abrindo na primeira, um engasgo custava
   os precedentes do resto da entrevista.

Sem precedentes a conferência ainda sai, e sai **marcada** (`com_precedentes:
false`, selo "sem precedentes" na tela). Análise sem precedente é a leitura do
modelo sobre o texto — não "o que os processos semelhantes mostram", e as duas
não podem parecer a mesma coisa.

Cuidados que os testes fixam: índice de precedente citado mas inexistente é
descartado (alucinação de referência); `faltam` chegando como string vira objeto;
e o modelo dizendo `suficiente: true` **com** lacunas listadas perde para a lista.

Falta: o disjuntor é por processo, não compartilhado — dois workers do uvicorn
tentariam o banco uma vez cada.

---

## Gravação com pausa e complemento — 13/08/2026

Os botões da pergunta narrativa deixaram de ser um só. Agora: **Gravar resposta**
(vira **Adicionar complemento** quando já há texto), **Pausar/Retomar** e
**Finalizar resposta**.

- **Pausar não mexeu no protocolo.** O servidor acumula o PCM da sessão e
  transcreve o acumulado no `stop`; parar de mandar bytes é, para ele, silêncio
  que nunca existiu. Serve para o entrevistador falar sem entrar na transcrição.
- **Complemento acrescenta, não substitui.** É o caminho natural depois de ler a
  conferência: ela aponta que faltou perguntar da CAT, você grava só isso e o
  trecho entra no fim da resposta. A conferência então roda sobre o texto
  INTEIRO, não só sobre o complemento.

---

## Assinatura eletrônica do contrato — implementada em 13/08/2026

`app/assinatura.py` manda o contrato de honorários para a **ZapSign** e acompanha
quem assinou. O .docx que sobe é o mesmo que `app/contrato.py` gera — modelo do
escritório com os colchetes preenchidos, palavra por palavra. A conversão para
PDF é do lado deles; não há conversor na máquina (o LibreOffice não é dependência
do projeto), por isso vai `base64_docx` e não `base64_pdf`.

| rota | para quê |
|---|---|
| `GET /api/assinatura/config` | se o envio está ligado; a tela pergunta antes de oferecer o botão |
| `POST /api/contrato/assinatura` | gera o contrato e dispara os convites |
| `GET /api/assinaturas` | índice local, sem bater na ZapSign (filtra por `caso_id` ou `cliente`) |
| `GET /api/assinaturas/{id}` | quem assinou e quem falta, consultado na hora |
| `GET /api/assinaturas/{id}/arquivo` | o PDF assinado com a trilha de auditoria |

**Decisões que não são óbvias no código:**

- **O botão de baixar o .docx continua ali.** O envio depende de chave, de
  internet e de o cliente ter e-mail ou WhatsApp — nada disso é garantido numa
  entrevista. Sem a chave, a tela explica e o atendimento não para.
- **Estado desconhecido vira `pendente`, nunca `assinou`.** A API responde o
  estado do signatário ora em inglês (`new`, `link-opened`, `signed`), ora em
  português (`nao_abriu`, `abriu`, `assinou`), conforme o endpoint. Valor novo
  que eles inventem cai no lado seguro: errar para "ainda falta" faz conferir;
  errar para "já assinou" faz protocolar ação com contrato em branco.
- **Papel casado por e-mail/telefone, não por posição.** "Cliente" e "escritório"
  são rótulo nosso — a ZapSign não os guarda. A lista volta na ordem em que foi
  mandada, mas apoiar-se nisso troca os papéis no dia em que eles mudarem.
- **`sign_url` só vem na criação.** A consulta de detalhe não o repete, então o
  link individual é preservado a cada refresh. É ele que o escritório reenvia por
  WhatsApp quando o convite cai no spam do cliente.
- **Os links da ZapSign expiram em 60 minutos.** Por isso o download passa pelo
  backend e o PDF fica em `dados/contratos/` — a via assinada é do escritório e
  precisa existir anos depois, com ou sem a conta ativa.
- **Excluir daqui não exclui lá.** A tabela `assinaturas` é índice local; o
  registro com trilha de auditoria é o da ZapSign, e ele é prova.
- **A tela recarrega sozinha a cada 20s**, não a cada 3s como o polling do OCR:
  cada volta é uma requisição à conta deles e contrato assinado leva horas.

Falta: **webhook**. Hoje o estado só anda quando alguém abre a tela. A ZapSign
manda evento de assinatura concluída; ligar isso tiraria o polling e avisaria o
escritório sem ninguém olhando — mas exige a API alcançável de fora, o que hoje
não é o caso (ver "HTTP puro" em Segurança).

---

## RAG de processos — implementado em 10/08/2026

`scripts/ingerir_jurimetria.py` importa, de forma idempotente, sentenças e
decisões do TRT8, comunicações DJEN, páginas do DEJT e decisões/acórdãos do TST.
Cada chunk recebe número do processo, origem, tipo, órgão, assuntos e o desfecho
calculado pela jurimetria. CPF e e-mail são redigidos antes do envio ao serviço
de embeddings.

`scripts/vetorizar_pendentes.py` preenche os `vector(1536)` em lotes retomáveis.
`sincronizar-rag.ps1` executa ingestão e vetorização. A rota protegida
`POST /api/estrategia` recebe um relato, recupera processos diferentes por
similaridade e somente então pede ao DeepSeek ações, riscos e lacunas. A resposta
inclui os processos e documentos usados. É apoio ao advogado, não previsão ou
garantia de resultado.

Ainda falta o RAG de legislação e súmulas; o RAG processual não substitui essa
camada normativa.
