# Acervo — onde o projeto está

## Vetorização CONCLUÍDA — 13/08/2026, 17h06

Confira sozinho, a qualquer momento, em vez de confiar nos números abaixo:

```powershell
.venv\Scripts\python.exe -m scripts.estado_rag
.venv\Scripts\python.exe -m scripts.estado_rag --busca "acidente com o dedo na máquina"
```

O `--busca` prova o caminho inteiro (texto → embedding → HNSW → processo) e é o
único que gasta uma chamada de embeddings.

**5.824 documentos / 52.926 chunks / 1.745 processos — 100% vetorizado.**

| origem | vetorizados |
|---|---|
| `trt8_juris` | 43.106 / 43.106 |
| `tst` | 5.122 / 5.122 |
| `djen` | 4.660 / 4.660 |
| `dejt` | 38 / 38 |

Aferido de ponta a ponta: uma busca por "acidente de trabalho com o dedo na
máquina, empresa não emitiu CAT" devolveu em **1,88s** cinco processos entre
0,776 e 0,809 de similaridade, de varas do Pará e do Amapá. A conferência da
entrevista e o `/api/estrategia` citam precedente de verdade.

A última corrida gravou 10.180 chunks em ~2h, com **27 quedas de conexão** pelo
caminho — nenhuma delas fatal, porque o orçamento de retentativas só conta falha
estéril (ver abaixo).

**A tarefa NÃO está desabilitada**, ao contrário do que este documento dizia
até 13/08. `AdvocaciaIA-SincronizarRAG` está `Ready`, com execução agendada, e
rodou em 13/08 às 09:27 (terminada: `LastTaskResult` 0x41306). Ela volta a rodar
sozinha — e agora o que ela vetoriza é só o que a ingestão trouxer de novo.

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
  gravacao.py     guarda o áudio da entrevista e o converte em .mp4
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
- **O áudio das entrevistas fica em claro em `dados/entrevistas/`**, sem prazo de
  descarte, e as rotas que o servem não têm autenticação — o que as protege hoje
  é o serviço só escutar em `127.0.0.1`. É a mesma decisão de retenção acima, com
  um agravante: voz é dado biométrico, e o arquivo é a conversa inteira.

---

## O que está quebrado ou faltando

- **README** ainda é o template do GitLab; não documenta o setup real.
- **Paginação de listas analíticas ainda é do frontend.** O painel do caso agora
  limita/pagina visualmente listas longas (fatos, ocorrências, pendências,
  responsáveis e histórico), para não transformar o dashboard numa rolagem sem
  fim. Mas a rota `/api/casos/{id}/painel` continua devolvendo tudo. A solução
  correta é o backend paginar listas longas com `items`, `total`, `page` e
  `page_size` ou cursor, mantendo agregados/gráficos calculados sobre o conjunto
  completo quando necessário.
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
- **A GPU é uma RTX 4050 Laptop de 6 GB, e ela é disputada.** PaddleOCR (backend),
  Whisper (transcrição) e o navegador dividem a mesma placa. Depois de aquecido,
  um trecho de fala sai em ~1s; sob disputa, os primeiros custaram 25s, 30s e um
  de **135s**. Se a transcrição voltar a demorar, medir isto ANTES de mexer no
  código: `nvidia-smi --query-compute-apps=pid,process_name --format=csv`.
- **O `next dev` vaza memória e morre.** Duas vezes em 15/08, com
  `FATAL ERROR: Ineffective mark-compacts near heap limit — JavaScript heap out
  of memory`. Não é a máquina: havia 16,5 GB livres. É o heap do V8, e o
  crescimento **não depende de tráfego** — o segundo processo morreu tendo
  servido dois `GET /`, subindo sozinho até o teto de 4 GB que já era o dobro do
  padrão. O suspeito é o watcher do Turbopack (Next 16.2.12).

  Aumentar `--max-old-space-size` só adia: de 2 GB para 4 GB ele demorou mais e
  morreu igual. Para uma sessão que não pode cair — demonstração, teste com o
  escritório —, servir o **build de produção** (`.\iniciar.ps1 -Prod`, ou
  `npm run build` + `npm run start`), que fica em **~130 MB somados** e não tem
  watcher nem HMR. O custo é perder o hot reload: mudou código, rebuild.

  E **não rodar `npm run build` com o `next dev` no ar** — são dois processos
  Node pesados na mesma máquina, e foi o que precipitou a primeira queda.

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

## Chamada da entrevista — guia em `docs/CHAMADA.md`

Como o pessoal roda: subir o Jitsi à parte (`docker compose up -d` em
`docker-jitsi-meet`, porta 8081), abrir a chamada na coluna direita da entrevista
e mandar o link sorteado ao entrevistado.

**A voz da chamada alimenta a transcrição** — 14/08/2026. Quando o cliente entra,
a faixa remota do WebRTC (a voz DELE, isolada da do entrevistador) vira a fonte
da transcrição, no lugar do microfone. `PainelChamada.onFaixaRemota` chama
`Roteiro.usarFaixaDaChamada` → `CapturaEntrevista.usarTrilha`, que troca a fonte
sem fechar a conexão de transcrição. O microfone da máquina fica de reserva para
a entrevista presencial.

Isto esteve **desligado** por um tempo: a faixa remota chegava muda e o VAD do
Whisper descartava a resposta inteira. A causa era o `AudioContext` forçado a
16 kHz recebendo a faixa do WebRTC a 48 kHz — nesse descompasso o
`MediaStreamAudioSourceNode` de faixa remota devolve silêncio, e o microfone
escondia o defeito porque o `getUserMedia` capta já na taxa do contexto. Corrigido
rodando o contexto na taxa nativa e reamostrando para 16 kHz **no worklet**
(`frontend/public/worklet-pcm.js`, interpolação linear). Prova em
`tests.test_worklet`: um Chrome real, senoide de 440 Hz num contexto a 48 kHz, e
a saída volta não-silenciosa e ainda a 440 Hz — o que só fecha se a taxa de saída
for mesmo 16 kHz. Não cobre a faixa remota em si (exigiria um segundo par na
chamada); cobre a peça que estava quebrada.

**Ainda só funciona na própria máquina.** O link é `localhost:3000/chamada/…`, e
trocar por IP não resolve: navegador não libera microfone fora de contexto seguro.
Cliente à distância exige HTTPS — mesmo bloqueio do portal, que hoje manda senha
em claro. Detalhes e diagnóstico de falha no guia.

### A chamada PERMANECE ao trocar de tela — 14/08/2026

Antes, cada tela criava a sua `ChamadaJitsi` e a desligava ao sair: a ligação
caía no instante em que o atendente ia da entrevista para o checklist, ou o
cliente trocava de aba. O escritório pediu o contrário — a chamada permanece,
para acompanhar o cliente pelo envio dos documentos sem largar a conversa.

Agora a instância vive no **`ProvedorChamada`** (`lib/ChamadaContexto.tsx`),
montado na raiz do app (`app/layout.tsx`), acima da troca de telas. As telas não
a possuem mais: entram, controlam e mostram a chamada, mas quem a segura é o
provedor, que não desmonta entre uma tela e a seguinte. Encerra só o botão de
desligar, ou fechar a aba (`pagehide`). Um **painel flutuante** (`DockChamada`)
aparece num canto quando há chamada e nenhuma tela a mostra por inteiro — é ele
que faz a ligação "seguir" o usuário. Vale para os dois lados: o mesmo provedor
está na raiz do escritório e na do cliente (portal e página da chamada são rotas
do mesmo app).

As quatro telas de chamada agora consomem o contexto: a coluna da entrevista
(`PainelChamada`), a chamada do checklist (`ChamadaAoVivo`), a página do cliente
(`app/chamada/[sala]`) e a seção do portal (`portal/[token]`). `new ChamadaJitsi`
só existe dentro do provedor.

**Cuidado que não é óbvio no código:** o objeto do contexto é recriado a cada
render do provedor, mas as ações são `useCallback` estáveis. Os efeitos de
assinatura (`registrarPainel`, `aoReceberFaixa`) dependem SÓ dessas funções
estáveis, nunca do objeto inteiro — senão cada render re-assinaria e **remontaria
o AudioContext da faixa remota**, picando a transcrição. Callbacks vindos de
props inline entram por `ref` para a assinatura rodar uma vez.

**O que ficou pela metade — sala da entrevista ≠ token do portal.** A entrevista
abre uma sala sorteada (`criarSalaChamada`), antes de o caso existir; o portal usa
o token do caso. São ids diferentes. A persistência mantém a sala que estiver
ATIVA, e o portal do cliente, se já houver chamada de pé, **usa a que existe** em
vez de forçar a sua — então quem faz a entrevista e segue conversando fica na
mesma sala o tempo todo. O furo é só o cliente que começa a chamada DIRETO pelo
portal (sala do token) enquanto o escritório está preso na sala da entrevista:
aí ficam em salas diferentes. Fechar isso de vez pede unificar os dois ids
(nascer o caso com a sala da entrevista como token), que é mudança de fluxo no
backend — não feita.

**Não testado ao vivo aqui.** Typecheck e build passam, e a lógica de troca de
tela é determinística; mas a ligação em si precisa do Jitsi de pé e de dois pares.
Conferir com duas abas: entrar na chamada pela entrevista, concluir, abrir o caso
— a chamada tem de continuar no painel do canto, sem reconectar.

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

## Relatório analisado da entrevista, com o símbolo do escritório — 14/08/2026

`POST /api/entrevista/relatorio` agora sai **analisado**, em **PDF**, e com o **emblema de
LARA & MELO** no cabeçalho. O botão "Gerar relatório analisado (PDF)" aparece
quando a entrevista fecha (`RelatorioEntrevista.tsx`, na `TriagemEntrevista`).

- **O emblema** é `app/marca.py`: um monograma e a razão social numa serifada
  editorial (Georgia), gerados com PIL em alta resolução e embutidos no PDF
  como imagem. Não havia logotipo no repositório; quando houver, `RELATORIO_LOGO`
  aponta para o PNG/JPG real e o desenho é ignorado. O .docx é montado à mão
  (zip + XML, sem python-docx), então embutir imagem exigiu as peças do OOXML:
  `word/media/logo.png`, a relação `rIdLogo`, o `Default Extension="png"` e os
  namespaces de DrawingML no elemento raiz.
- **A análise** reusa o motor do `/api/estrategia` (`rag.sugerir_acoes`): síntese,
  ações sugeridas, riscos e lacunas, cada item citando o precedente que o
  sustenta. Vem ANTES das 86 respostas em detalhe — é a síntese que se lê
  primeiro. É apoio à decisão, não conclusão: o rodapé e o aviso deixam explícito,
  o mesmo contrato do `/api/estrategia`.
- **Melhor-esforço, como o resto que depende do pgvector.** Base fora do ar não
  impede o relatório: a seção vira uma nota ("não respondeu a tempo") e o
  documento sai organizado. O cabeçalho `X-Analise` (`sim`/`indisponivel`/`nao`)
  diz à tela o que entrou.
- **Um clique, não download automático.** A análise busca precedentes e chama o
  modelo (até ~1 min); baixar sozinho no meio disso pareceria travamento. O botão
  deixa o tempo visível.
- **Falhar no emblema não custa o relatório.** Se o PIL/​fonte falhar, o .docx sai
  sem símbolo, com as respostas — a entrega é o que importa.

Testes: `.venv\Scripts\python.exe -m tests.test_relatorio` — monta o .docx de
verdade e confere zip íntegro, XML bem-formado em todas as partes, o PNG do
emblema ligado por relação, a análise com as citações `[P1, P3]`, a degradação
sem análise e com base fora do ar, e que campo torto do modelo não quebra a
geração. Não abre o Word (não há), mas valida tudo que ele exige para abrir.

---

## O Whisper agora AQUECE no boot — 16/08/2026

`transcricao.aquecer_modelo`, chamado pelo `lifespan` do serviço de transcrição.

O sintoma: entrevista começada, cliente falando, e o painel parado em *"ouvindo
— nada reconhecido ainda"*. Não era o microfone (o painel distingue os dois
casos, e teria dito "microfone sem som"). Era o tempo de inferência no log:

    inferencia=30036ms   para 2,3s de fala
    inferencia=25791ms   para 34,6s
    inferencia=135022ms  para 1,5s
    ...
    inferencia=1149ms    daí em diante

Carregar os pesos não é estar pronto. A primeira `transcribe` de verdade compila
kernels CUDA e aloca caches do cuDNN, e o `lifespan` só chamava
`carregar_modelo()` — pagava a carga (5,6s) e deixava a inferência fria para o
primeiro cliente. Agora ele roda **uma inferência de mentira** no boot: 6,5s
nesta máquina, pagos antes de alguém falar.

Dois detalhes que parecem irrelevantes e decidem se o aquecimento funciona:

- **ruído baixo, não silêncio, e `vad_filter=False`.** Com o VAD ligado o
  silêncio é cortado inteiro, nada chega ao decodificador, e metade dos kernels
  continua fria — justamente a metade cara.
- **`transcribe` devolve um gerador preguiçoso.** Sem `list(segmentos)` nada roda
  e o aquecimento seria uma linha de log mentindo.

Falha no aquecimento não derruba nada: loga e segue, porque é otimização — o
caminho normal carrega o modelo de novo.

---

## O trecho que abre um módulo é lido duas vezes — 16/08/2026

`escuta._abertas_pelo_rastreio`. O escritório notou que o sistema "parou de
preencher as perguntas mais à frente". Medido contra a escuta real, com a MESMA
frase — *"Fui assaltado sim. Tenho o boletim de ocorrência e a CAT, e fiquei
afastado pelo INSS"*:

| estado do roteiro | o que preenchia |
|---|---|
| rastreio ainda não respondido | só `r_assalto` |
| `r_assalto` já positivo | `as_ocorrencias`, `as_cat`, `as_inss` |

As perguntas do módulo **não existem** até o rastreio abri-lo, e o cliente conta
a história inteira antes de alguém perguntar. O módulo nascia no mesmo instante
em que o resto da frase era descartado, por não ter onde cair.

Agora, quando um rastreio dá positivo, o mesmo trecho é lido de novo contra as
perguntas recém-nascidas. É uma chamada a mais ao modelo, no máximo uma por
módulo — quatro por entrevista no pior caso — e a mesma frase passou a preencher
os quatro campos de uma vez.

Detalhe que o teste pegou: ler o mesmo trecho duas vezes gera o **mesmo lembrete
duas vezes**, e duas linhas idênticas num painel lido de relance parecem dois
assuntos. Os lembretes são deduplicados por texto na junção.

---

## O atendimento inteiro numa rolagem só — 17/08/2026

`EntrevistaComChamada` deixou de ser "a tela da entrevista" e passou a ser a tela
do ATENDIMENTO. O escritório pediu "tudo numa paulada só", e o corte que existia
— concluir a entrevista para então aparecer outra tela — era o problema: ele
encerrava a gravação e a chamada **justamente quando o roteiro manda permanecer
nelas**, para a avaliação do Google.

A ordem, agora, rolando para baixo:

    roteiro → Google Meu Negócio → relatório → os três documentos e a
    assinatura → criar o caso → checklist recebendo documentos → encerrar

**O roteiro não fecha mais nada.** Ele reporta as respostas conforme mudam
(`onRespostas`) e as etapas seguintes leem isso ao vivo — o contrato pede nome e
CPF, e eles chegam nas duas primeiras perguntas. O botão de encerrar saiu de
dentro dele: com as etapas na mesma rolagem, ele caía no MEIO do atendimento.

**O caso nasce aqui** (`CasoEDocumentos`), com o cliente na linha, e o checklist
abre em seguida. O ganho é um só e é grande: o cliente envia o que já tem
**agora**, com alguém do outro lado para dizer se a foto saiu legível — em vez de
o escritório descobrir dias depois. O que ele não tiver, manda pelo mesmo link, e
para isso existe o botão de encerrar a chamada sem encerrar o caso.

**Criar o caso põe o advogado na sala dele.** Isto fecha a pendência anotada em
13/08 ("sala da entrevista ≠ token do portal"): a entrevista abria uma sala
sorteada antes de o caso existir, e o cliente que entrasse pelo portal ia parar
noutra. Agora o advogado entra sozinho, sem senha — ele já está autenticado —, e
a tela avisa se a conversa vinha de outra sala, porque **o cliente ficou lá** e
precisa ser chamado.

Duas armadilhas que isso destapou:

- **A câmera não atravessava a troca de sala.** Entrar noutra sala fecha a
  chamada e cria outra, que nasce sem câmera a menos que alguém peça. E o estado
  `temCamera` só era escrito pelo `alternarCamera`, então a imagem ficava no ar
  com o botão dizendo "Câmera" — o primeiro clique DESLIGAVA. Corrigido nos dois
  lugares; o segundo defeito era anterior e valia para qualquer entrada com
  câmera.
- **O checklist embute o painel do portal, que abre uma chamada própria.** Dentro
  do atendimento isso virava duas chamadas do mesmo lado, com câmera e tudo. O
  `dentroDoAtendimento` corta a segunda. O link e a senha continuam à vista, com
  a linha que faltava: **eles são do cliente** — quem está ali entrou pelo login
  e já está na sala.

**Encerrar são dois cliques, e a gravação corre até o primeiro.** O primeiro
fecha a gravação e abre o fecho com os três arquivos: áudio (do servidor),
**transcrição bruta** (.txt, a fala como saiu do Whisper, com hora de parede em
cada trecho) e o vídeo, que continua no bloco lá em cima. Só então "Sair do
atendimento". A transcrição bruta é coisa diferente do que está nos campos, e o
cabeçalho do arquivo diz isso: o que está nos campos é o que o sistema
interpretou; o arquivo é o que foi dito — inclusive o que a escuta descartou.

Falha ao fechar a gravação não prende o atendimento: o fecho abre com o aviso, e
vídeo e transcrição seguem valendo.

---

## Nome e CPF são digitados, e é o que libera o microfone — 17/08/2026

Regra do escritório, e ela conserta um defeito medido. Nome e CPF já foram
sugestão da escuta, com um clique para confirmar. No áudio real não funcionava:

    Whisper small   "Meu nome é com o Patrã Guilherme, nome de Bezerra."
                    "Eu não é um completo aglermino, não desbezerra..."

O trecho chegava à escuta e o modelo — corretamente, seguindo a própria instrução
("na dúvida sobre o que foi dito, NÃO preencha") — recusava-se a sugerir. Na tela
isso era um campo vazio sem explicação, e o sintoma relatado foi "não preenche
nem o nome".

Agora `escuta.DADOS_DIGITADOS` tira os dois da escuta por completo: não são
oferecidos ao modelo e são descartados se ele insistir. E o botão de abrir o
microfone fica travado até os dois estarem preenchidos, com CPF válido pelo
dígito verificador — o aviso diz o que falta e leva ao campo.

Efeito colateral: **nada mais vira sugestão**, e a máquina de conferência
(selo "OUVIDO · CONFIRA NO FIM", a conferência no fim do roteiro, a contagem no
painel) ficou inerte. Não foi removida — está morta, não atrapalha, e o caminho
serve se um dia outro campo depender de confirmação humana.

---

## Whisper `medium`, por medição — 17/08/2026

O `small` destruía nome próprio, que é o dado que abre contrato, procuração e
declaração. Mesmo arquivo de 96,8s, os dois modelos:

| falado | `small` | `medium` |
|---|---|---|
| Guilherme Nunes | "Guilherme **Inunes**" | "Guilherme Nunes" |
| auxiliar de manutenção industrial | "o **CIDA de Mando Tensão** Industrial" | "auxiliar de manutenção industrial" |
| Metal Forge … LTDA | "**Metalford** … **LTA**" | "Metal Forge … LTDA" |
| velocidade | 27,1x tempo real | **31,5x** |

Mais certo e mais rápido. Custa VRAM: ~1,5 GB contra ~0,5 GB, e com ele o serviço
ocupa **4.230 MiB dos 6.141** da RTX 4050 — cabe junto do PaddleOCR com folga de
quase 2 GB. Faltando memória, `WHISPER_MODELO=small` no `.env` volta atrás sem
tocar em código.

O `large-v3` não chegou a ser medido: o download travou e foi abortado. Como o
`medium` resolveu o caso que motivou a troca, não se insistiu.

---

## A papelada são TRÊS documentos, não um — 17/08/2026

`contrato.MODELOS` + `gerar_todos`. O escritório soltou em `docs/` a **procuração
ad judicia** e a **declaração de hipossuficiência econômica**, e elas usam a
mesma convenção de colchetes do contrato — a máquina de preenchimento que já
existia serviu sem alteração. O que mudou foi o escopo: gerar só o contrato
deixava o atendimento pela metade, porque **sem procuração o advogado não
peticiona e sem declaração não há gratuidade**, e as duas seguiam sendo montadas
à mão depois, fora do sistema, que é onde se perdem.

Os três modelos pedem o mesmo dado com nomes diferentes — `[nome da pessoa]`,
`[nome completo]`, `[nome do outorgante]`, `[nome do declarante]`; RG inteiro na
procuração e partido no contrato. Um dicionário só serve aos três: `preencher`
troca o que encontra e ignora o resto. E `_validar_e_normalizar_obrigatorios`
força o nome **já validado** em todos os apelidos — sem isso o mesmo cliente
sairia com duas grafias no mesmo maço.

**Na tela, um botão por documento.** Eles formam uma papelada só, mas na mesa do
escritório são três arquivos com três destinos, e quase sempre se quer um deles
(a procuração para protocolar hoje, o contrato para reenviar). O aviso de campo
em branco é **por documento**: o contrato pede telefone e e-mail, a procuração
não, e somá-los sugeriria buraco onde não há.

**Na assinatura, os três de uma vez.** A ZapSign trabalha com um envelope por
documento — link, estado e trilha próprios —, então o cliente recebe três
convites e a tela acompanha os três em separado. Um contador somado esconderia o
que o escritório precisa saber: QUAL deles está parado.

Se o segundo ou o terceiro for recusado depois de o primeiro já ter subido, a
resposta traz o que já foi enviado e um aviso para mandar só o que faltou —
reenviar tudo duplicaria convites que o cliente já recebeu.

Os dois modelos novos trazem o corpo **duplicado** dentro do .docx (via do
cliente e via do escritório, provavelmente). Não foi mexido: é documento do
escritório, e o cliente assina o que está lá.

---

## A cobrança recolhe quando a entrevista flui — 17/08/2026

Medido em uso: a placa de PARE ficou **62 segundos** no ar sobre "Nome completo"
enquanto o cliente respondia — o rastreio de assalto entrou sozinho no mesmo
período. Pela regra do escritório estava certo (não é a pergunta da vez), mas um
alarme que fica minutos no ar vira paisagem, e aí não serve para o caso em que
importa: o cliente falando do filho, da vizinha, sem nada entrando em campo
nenhum.

Agora, enquanto cair resposta em QUALQUER pergunta (janela de 20s), a placa
recolhe para uma linha âmbar — *"62s sem responder esta. Ele está respondendo
outras — encaixe esta quando ele terminar a frase"*. O relógio não para e a
pergunta continua aberta; o que muda é o tom. Parou de entrar qualquer coisa, a
placa volta inteira, com a frase de corte.

---

## A tela do atendimento só mostra o atendimento — 17/08/2026

`ListaCasos` + `ChamadaDoAtendimento.tsx`. Duas coisas atrapalhavam a tela em
que o caso nasce, logo depois da entrevista:

**A lista de quinze casos antigos ao lado do atendimento em curso.** Ela é a
porta de entrada de OUTRO trabalho — abrir o checklist de um cliente de semanas
atrás — e quinze linhas clicáveis são quinze chances de sair do atendimento sem
querer, com o cliente na linha. Some enquanto durar o atendimento e volta
sozinha quando o caso é criado.

**A chamada virava uma pílula num canto.** Ela já sobrevivia à saída da
entrevista (vive no `ProvedorChamada`, na raiz), mas a etapa seguinte é a do
Google Meu Negócio, que manda PERMANECER na videoconferência enquanto o cliente
avalia. Instrução assim ao lado de um canto discreto é instrução que ninguém
segue. Agora a chamada ocupa a coluna que a lista desocupou, com os retratos, o
estado e o aviso de não desligar; o "desligar" fica discreto de propósito,
porque nesta tela é quase sempre o botão errado.

O aviso que a `TriagemEntrevista` manda para fora é uma FASE ("entrevista",
"pos-entrevista", "nenhum"), não um sim/não: durante a entrevista a chamada já
está na coluna da direita, e um booleano faria o mesmo vídeo ser decodificado em
dois lugares ao mesmo tempo.

---

## Os documentos do caso num ZIP só — 16/08/2026

`GET /api/casos/{id}/documentos.zip` (`casos.montar_zip`) e o botão no alto do
checklist (`BaixarDocumentos.tsx`). O escritório baixava documento por
documento, clicando linha por linha: trinta arquivos, trinta cliques, e a
certeza de esquecer um.

- **A ordem é a do checklist e o nome do item vai no arquivo** —
  `03 - Laudos medicos - foto.jpg`. Quem abre o pacote está conferindo contra a
  mesma lista, e o descompactador ordena por nome.
- **Cada entrega entra uma vez.** Uma CIN que atende RG e CPF aparece em dois
  itens e é um arquivo só; duplicá-la faria o conferente procurar diferença
  entre duas cópias idênticas.
- **Montado a cada pedido, apagado depois.** Nasce em `pipeline.TMP_DIR` e some
  no `BackgroundTask` quando o último byte sai — papelada de cliente não fica
  sobrando em disco, e documento novo entra no pacote seguinte sem cache para
  invalidar. Vai para disco e não para a memória: um caso instruído passa fácil
  de cem megabytes, e dois atendentes baixando ao mesmo tempo derrubariam o
  servidor.
- **O que sumiu do disco é contado, não inventado.** `X-Faltando` sobe no
  cabeçalho e a tela avisa: ZIP silenciosamente incompleto é pior que erro,
  porque ninguém confere o que não sabe que faltou.
- **O download vai por `fetch`, não por `<a href>`**: link cru não manda o
  Bearer, e o que desceria seria um 401 salvo em disco com nome de `.zip`.
  Mesmo motivo de `baixarArquivoEntrega`.

O botão aparece assim que houver um documento — baixar o que já chegou é útil no
meio do caminho — mas só fica **cheio** quando o checklist fecha, que é quando
ele deixa de ser conveniência e passa a ser o próximo passo.

---

## Áudio da entrevista gravado e baixável — 14/08/2026

`app/gravacao.py` + três rotas no serviço de transcrição (`:8200`). A entrevista
já era transcrita; agora o áudio também fica guardado, e sai em **.mp4** pelo
painel no fim do roteiro e na tela da triagem.

| rota | para quê |
|---|---|
| `GET /entrevista/{id}/gravacao` | se há áudio, quanto dura, se o MP4 já saiu |
| `POST /entrevista/{id}/encerrar` | fecha e converte; devolve o pronto se já houver |
| `GET /entrevista/{id}/audio` | o arquivo, com `Content-Disposition: attachment` |

**Quem grava é o servidor, do mesmo PCM que alimenta o Whisper.** É o que garante
a única propriedade que importa num arquivo que pode virar prova: o áudio é
exatamente o que foi transcrito. Um `MediaRecorder` no navegador seria uma
segunda captura, com começo e fim próprios, e as duas divergiriam no dia em que
uma falhasse — além de morrer junto com a aba.

**O arquivo é mais curto que a entrevista, de propósito.** Só entra o que foi
ENVIADO: durante a pausa o navegador para de mandar bytes (é para isso que a
pausa existe), e entre perguntas também não vai nada. Emendar isso calado seria
editar áudio sem dizer — por isso cada retomada vira um trecho no manifesto
`dados/entrevistas/<id>.json`, com o instante de relógio em que aconteceu. A tela
diz a mesma coisa em uma linha, embaixo do player.

**WAV primeiro, MP4 só no fim.** O MP4 guarda o índice no fecho: processo que
morre no meio deixa arquivo que nenhum player abre. O WAV cru sobrevive, e
`_reparar_cabecalho` refaz os tamanhos a partir do tamanho do arquivo — coberto
por teste que simula a queda. Um `entrevistaId` que reaparece **continua** o
arquivo em vez de sobrescrevê-lo: é o F5 no meio da entrevista.

**48 kbps, medido.** Convertendo 5 minutos de áudio 16 kHz mono nesta máquina:

| bitrate | tamanho | tempo | |
|---|---|---|---|
| 32k | 1,23 MB | 2,91s | 103x o tempo real |
| 48k | 1,82 MB | 3,12s | 96x o tempo real |
| 64k | 1,87 MB | 14,96s | 20x o tempo real |

O encoder AAC nativo satura perto dos 48 kbps nessa taxa: pedir 64 custa cinco
vezes o tempo para entregar 3% mais bytes. Uma entrevista de 40 min vira ~17 MB
e converte em ~25s — daí a conversão ser um POST à parte, com "preparando o
arquivo" na tela, e não algo que aconteça dentro do download.

**Sem dependência nova.** O PyAV já vinha com o faster-whisper e traz o FFmpeg
embutido; não há `ffmpeg` no PATH desta máquina e continua não sendo preciso
haver.

**O que ainda não está resolvido:**

- **Retenção e base legal.** Áudio de entrevista tem voz, CPF e dado de saúde, e
  hoje ele fica em claro em `dados/entrevistas/`, sem prazo de descarte e sem
  autenticação na rota (o serviço só escuta em `127.0.0.1`). Ver a ressalva da
  tabela `entrevistas` na seção de Segurança — é a mesma decisão pendente.
- **A saudação do roteiro não menciona gravação.** Ela promete sigilo. Enquanto
  o texto do escritório não for atualizado, quem avisa é o entrevistador, e o
  lembrete fica na tela durante a escuta.
- **Nada apaga arquivo velho.** São ~22 MB por hora de conversa, para sempre.

Testes: `.venv\Scripts\python.exe -m tests.test_gravacao` — cobre o ciclo PCM →
MP4 (decodificando o resultado de volta), a queda no meio, o F5, dois cliques em
encerrar, entrevista sem áudio, id com travessia de caminho e as três rotas de
ponta a ponta. Não carrega o Whisper: manda menos de meio segundo por sessão e
não manda `stop`.

---

## Vídeo da entrevista — grava no navegador, NÃO fica guardado — 14/08/2026

`frontend/lib/gravacaoVideo.ts` + `components/VideoDaEntrevista.tsx`. Botão no
alto do roteiro, ao lado de "Começar a entrevista". Não há rota, não há pasta e
não há upload: **o vídeo existe só na aba**, e quem não baixar, perde.

**A assimetria com o áudio é a decisão, não um passo que faltou.** Áudio o
servidor guarda, porque ele é a memória do atendimento e é o que sustenta a
transcrição. Vídeo é o dado mais pesado e mais sensível que este sistema toca —
rosto, sala, documento na mão — e guardá-lo criaria um acervo de imagem com
retenção indefinida, num sistema que ainda não decidiu retenção nem base legal
nem para o áudio. Enquanto essa decisão não existir, o vídeo sai pela mão de
quem gravou e não fica.

Isso muda o que a TELA precisa fazer, e é aí que está o trabalho:

- o botão de baixar fica **cheio e vermelho** enquanto o arquivo não foi salvo;
- `beforeunload` segura o fechamento da aba;
- **Concluir entrevista** e **Fechar sem concluir** perguntam antes (é o
  `temVideoPendente` no `ManipuladorRoteiro`) — os dois desmontam a tela, e
  desmontar a tela é destruir o arquivo.

**Duas fontes, porque são duas entrevistas diferentes.** `câmera` é a
presencial: câmera e microfone desta máquina, com `getUserMedia` próprio — o
microfone da transcrição é da `CapturaEntrevista`, e pará-lo aqui emudeceria a
entrevista inteira. `tela` é a por chamada: **esta aba** por `getDisplayMedia`,
com o microfone daqui **misturado** num grafo de áudio, senão a gravação teria a
voz do cliente e nenhuma das perguntas — o `MediaRecorder` grava uma faixa de
áudio só, e a segunda seria descartada em silêncio.

### A tela gravada é a do sistema, e só ela — 15/08/2026

O escritório reclamou de a gravação sair como "as abas do Chrome". Era o seletor
padrão do `getDisplayMedia`: ele oferecia guia, janela e tela inteira, e a
entrevista podia acabar gravada como o e-mail de outro cliente ou a área de
trabalho da máquina — o que num vídeo que vai por WhatsApp é vazamento de dado
de terceiro, não arquivo errado.

Duas travas, porque a primeira é preferência e a segunda é regra:

1. `ESTA_ABA` em `gravacaoVideo.ts` — `preferCurrentTab` prende a captura nesta
   aba, `selfBrowserSurface: include` faz o Chrome parar de esconder a própria
   aba da lista (o padrão dele é escondê-la) e `surfaceSwitching: exclude` tira o
   botão de trocar de guia no meio da gravação. O Chrome ainda pede "compartilhar
   esta guia?", e não há como evitar — dá para reduzir a um sim ou não, sem
   escolha errada possível.
2. **Conferência do que veio.** `preferCurrentTab` é do Chrome; Firefox e Safari
   o ignoram e entregam o que a pessoa escolher. Se `displaySurface` voltar
   diferente de `browser`, as trilhas são fechadas e a gravação não começa. Só
   recusa quando o navegador DIZ o que entregou — `displaySurface` é opcional, e
   tratar "não informou" como "é a tela inteira" tiraria a gravação de quem usa
   um navegador mais calado.

Conferido num Chrome de verdade, nos dois caminhos: com a aba atual a gravação
sai e a superfície volta como `browser`; forçando "Entire screen" pelo
`--auto-select-desktop-capture-source`, a trava recusa e o estado fica `parado`.
Fica o registro de uma armadilha: `--use-fake-ui-for-media-stream` (a flag que o
`tests/test_video.py` usa para a câmera) **atropela o seletor e devolve a tela
inteira**, ignorando o `preferCurrentTab`. Um teste de captura de aba precisa
subir o Chrome sem ela, com `--auto-accept-this-tab-capture`.

**MP4 quando dá, WebM quando não dá**, e a extensão do arquivo segue o que foi
realmente gravado: um `.mp4` que por dentro é WebM não abre no player de quem
recebe. Medido no Chrome desta máquina — ele aceita
`video/mp4;codecs="avc1.42E01E,mp4a.40.2"`, então sai MP4.

1,2 Mbps de vídeo e fatias de 5s no `MediaRecorder`: são ~9 MB por minuto, e a
fatia é o que faz o navegador mandar o blob para o disco em vez de segurar uma
entrevista inteira na memória da aba.

Teste: `.venv\Scripts\python.exe -m tests.test_video` — **abre um Chrome de
verdade**, headless, com câmera e microfone falsos. É o único teste do projeto
que sobe navegador, e o motivo é que o objeto testado é o `MediaRecorder`: um
dublê provaria só que o dublê funciona, justamente na parte que muda de versão
para versão. Ele compila o módulo com o `tsc` do projeto, serve a página em
`127.0.0.1` (getUserMedia exige contexto seguro) e confere que saiu MP4 com
faixa de vídeo e de áudio, que o player abre o arquivo, que ele vive em `blob:`
e que `descartar` revoga o blob. Sem Chrome instalado, o teste se diz PULADO em
vez de falhar.

---

## Condução da entrevista pelo roteiro — 15/08/2026

`frontend/components/Conducao.tsx`. O escritório fechou a regra numa frase: "não
é o que o cliente quer ou nós entendemos — tem que ser o que o advogado
determina". A tela tinha escuta e painel, mas ninguém dizia qual era a **próxima
pergunta**: o entrevistador escolhia entre 86 enunciados enquanto o cliente
falava, e a conversa ia para o filho, a vizinha e a cirurgia que não é a do
processo.

Agora há uma barra grudada no alto da coluna do roteiro com **uma** pergunta: a
primeira ainda em aberto, na ordem do documento. É a única coisa ali — o painel
do lado continua listando o que falta e o que já entrou, mas isso é para
conferir, não para escolher.

**Os dez segundos.** Passado esse tempo sem a pergunta ATUAL respondida, a barra
fica vermelha e abre uma faixa de **PARE** de ponta a ponta: *DIRECIONE A
PERGUNTA — NÃO PERCA TEMPO*. É placa, não texto — o entrevistador está olhando o
cliente, e o que ele capta pelo canto do olho tem de ser "corta e volta ao
roteiro". Não pisca: movimento na periferia da visão sequestra a atenção de quem
deveria estar ouvindo, e quem apaga o alarme é a resposta, não o entrevistador
olhar para a tela. O relógio zera quando a pergunta muda, e ela só muda quando
foi respondida ou deixada para depois.

O cliente falar de outro assunto **não** zera o relógio, e isso é a regra, não um
descuido — foi a pergunta que o escritório respondeu explicitamente: *"não importa
o que ele esteja respondendo, o que importa é a sequência de perguntas"*. O que
ele contar fora de ordem a escuta aproveita de qualquer jeito (`app/escuta.py`),
e a pergunta correspondente some da sequência sozinha: é assim que uma entrevista
de 86 perguntas fecha em poucos minutos sem ninguém perder o fio.

**A frase do corte, escrita.** Só apontar o tempo não resolve: cortar um cliente
que está desabafando é constrangedor, e por isso ninguém corta — a entrevista de
20 minutos vira uma de 50 e as perguntas do fim ficam sem resposta. Junto da
placa de PARE a tela mostra, em três peças e na ordem em que se fala:

    LEIA AO CLIENTE   a retomada, que acaba em dois-pontos
    (o enunciado)     em corpo grande, logo abaixo — a frase emenda nele
    o fecho           "Aqui basta o(a) senhor(a) me dizer sim ou não."

As retomadas estão em `roteiros.RETOMADAS`, junto da saudação e do encerramento,
porque são palavra do escritório e é lá que ele mexe. **Elas não foram
inventadas**: apoiam-se no que a saudação já prometeu ao cliente e ele aceitou —
"farei algumas perguntas bastante específicas", "essenciais para que nenhuma
informação relevante deixe de ser considerada", "costuma durar entre 20 e 30
minutos". Cortar lembrando o combinado não é grosseria; é o combinado.

**A ordem da lista é de firmeza**, e a tela sobe um degrau a cada vez que o
cliente segue sem responder (10s, 25s, 45s, 70s — `DEGRAUS_S` no `Conducao.tsx`).
É como um entrevistador experiente faz: não se sobe o tom de uma vez, e não se
repete a mesma frase gentil enquanto a entrevista escorre. O `FECHOS_POR_TIPO`
diz o TAMANHO da resposta esperada, e `relato` fica de fora de propósito — ali a
resposta longa é o objetivo.

O `tests/test_roteiros.py` trava as duas invariantes que uma reescrita
bem-intencionada quebraria em silêncio: toda retomada termina em dois-pontos (sem
isso a leitura em voz alta quebra no meio, com o cliente na linha) e todo fecho é
de um tipo que o roteiro realmente usa.

**A conferência de nome e CPF virou etapa do FIM.** Nome e CPF nunca entram
sozinhos: a escuta os manda como sugestão e quem confirma é quem está ouvindo
(`escuta.DADOS_PERMITIDOS` — número ditado a transcrição erra e ninguém confere
dígito de ouvido). Isso não mudou. O que mudou foi **quando** se confere.

A caixa "confirme o que eu ouvi" ficava no painel lateral, pedindo o clique no
meio da conversa. Somada à condução, ela travava duas vezes por entrevista: como
a barra aponta para "a primeira não respondida" e sugestão não é resposta, o
roteiro parava nas duas primeiras perguntas até alguém achar o clique — com a
placa de PARE mandando insistir numa pergunta que o cliente já tinha respondido.
O escritório foi direto: *"a conferência desses campos só no final, para não
travar o processo"*.

Então:

- a condução **pula** o que está esperando confirmação — "esperando clique" é
  outra coisa que "o cliente não respondeu"; ele já falou o nome dele;
- o painel lateral perdeu a caixa e os botões, e ficou só com a contagem
  ("2 respostas ouvidas ficam para conferir no fim") — botão ali é convite a
  parar a entrevista, que é o que se quis tirar;
- a conferência inteira acontece na `Conducao`, no estado de **roteiro
  percorrido**: valor em mono e corpo grande (proporcional embaralha 1, l e I
  num CPF), a citação do que foi dito, e dois botões. **Descartar devolve a
  pergunta à condução** — descartar significa perguntar de novo;
- **Concluir entrevista** pergunta antes, se sobrou algo por conferir. Sem isso,
  sair da tela descartaria em silêncio os dois campos que identificam o cliente,
  e o contrato nasceria em branco neles.

**A condução não atropela quem está respondendo.** O primeiro trecho que a
escuta devolve já preenche o campo, e campo cheio fazia a barra pular para a
pergunta seguinte **no meio da frase do cliente** — o entrevistador lia a
próxima e cortava o raciocínio dele. Conduzir não é atropelar.

Agora a barra SEGURA a pergunta enquanto trechos continuarem caindo nela
(`SEGUNDOS_ANTES_DE_ANDAR`, 8s desde o último), e o relógio de 10s fica suspenso
nesse tempo — o cabeçalho troca o cronômetro por *"respondendo — deixe
terminar"*. Cair trecho em OUTRA pergunta não segura nada: resposta adiantada é
o que encurta a entrevista, e falar de outro assunto não pausa a cobrança, que é
a regra do escritório.

Decisões que vão junto:

- **"Deixar para depois" existe porque a cobrança não pode ser inescapável.** Uma
  pergunta que o cliente não sabe responder travaria a sequência com o alarme
  tocando sem saída. A pulada sai da vez, continua pendente no painel e volta ao
  fim do roteiro — não é resposta, e a tela não a conta como uma.
- **O bloco delegado saiu da sequência.** A qualificação é do Departamento de
  Documentação, depois do encerramento (`roteiros.IDENTIFICACAO`). Ela segue na
  tela, agora com o aviso de que não se percorre agora — antes nada dizia isso, e
  quem não conhecia o roteiro datilografava catorze campos de cadastro com o
  cliente esperando. O contador `feitas/total` passou a contar só o que a
  entrevista percorre.
- **A seção "pergunte agora" do painel virou "aprofundar depois desta".** Ela é o
  que o modelo sugeriu aprofundar, e com aquele nome disputava com o roteiro a
  pergunta seguinte. Quem manda na próxima pergunta é a barra.

### Google Meu Negócio é etapa, não sugestão — 15/08/2026

`components/AvaliacaoGoogle.tsx`, entre o fim da entrevista e o contrato. O
roteiro não manda avaliar depois: manda avaliar **agora**, com o atendente na
linha — está no `FECHAMENTO`, palavra por palavra ("peço apenas que realize a
avaliação agora. Eu permanecerei na videoconferência aguardando para confirmar
que deu tudo certo"). A tela passou a dizer isso: desligar a chamada antes é
perder a avaliação, e não há segunda chance depois que o cliente sai.

E ganhou a **marcação do atendente**, que é o que faltava para a etapa existir.
O rótulo afirma o que aconteceu — "o cliente concluiu a avaliação e eu confirmei
com ele na chamada" — e não um "concluído" genérico que cada atendente
interpretaria do seu jeito; mandar o link não é avaliação feita. O selo ao lado
do título fica em **pendente** até a marca.

A marcação mora na `TriagemEntrevista`, não na caixa: "Voltar ao roteiro"
desmonta a caixa, e a marca sumiria junto — dando por pendente uma etapa
cumprida.

Falta: **a marca não é persistida**. Ela vive na tela do atendimento; recarregar
a página zera. Para virar registro de verdade precisa de coluna no caso e de uma
rota — e aí também entra no relatório da entrevista, que hoje não sabe dela.

Falta: a barra não fala com o backend. Se um dia a condução precisar valer entre
abas ou entrar no relatório da entrevista ("quanto tempo em cada pergunta", "onde
o entrevistador se perdeu"), o relógio tem de subir junto com a transcrição.

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

---

## Módulo do agente jurídico — implementado em 13/08/2026

`app/agente/` liga o Acervo ao serviço `ia-juridica`, que guarda o **Case State**:
fato com proveniência, classificação, pendência de playbook e pesquisa de
jurisprudência. A tela nova é o **Dossiê do caso** (`frontend/src/components/admin/Dossie.tsx`),
alcançada pela barra de abas dentro do caso.

```
OCR (este repositório)                  agente (ia-juridica, :8000)
──────────────────────                  ──────────────────────────
caso, cliente, checklist       ──push──▶ caso espelhado
extração de cada documento     ──push──▶ fato com proveniência
qualificação do contrato       ──confere▶ divergência com os documentos
Dossiê do advogado             ◀──read── classificação, pendência, precedente
```

| rota | para quê |
|---|---|
| `GET /api/agente/config` | se a ligação está ligada **e** se o agente responde |
| `POST /api/agente/casos/{id}/sincronizar` | cria o caso lá e manda os documentos que faltavam |
| `GET /api/agente/casos/{id}` | o dossiê inteiro, dos dois lados, com a linha do processo |
| `POST /api/agente/casos/{id}/analise` | classifica e recalcula pendências (202, roda em worker) |
| `POST /api/agente/casos/{id}/pesquisa` | dispara a pesquisa de jurisprudência (202) |
| `GET /api/agente/casos/{id}/pesquisa/{ref}` | precedentes, aplicabilidade, trechos e filtros usados |
| `POST /api/agente/casos/{id}/contrato/conferencia` | confere a qualificação contra os fatos |

**Decisões que não são óbvias no código:**

- **Ponte, não cópia.** O agente continua sendo outro serviço, com banco e testes
  próprios. Trazê-lo para dentro faria o PaddleOCR (que satura CPU) dividir processo
  com o agente (que espera I/O de LLM), e traria 15 migrations para um repositório
  que hoje sobe com `iniciar.ps1` numa máquina de escritório.
- **O envio do documento é automático e silencioso.** Ao fim do OCR, se o caso já
  estiver vinculado, a extração vai para o agente numa thread de fundo. Falha ali não
  pode marcar a entrega como erro de leitura — o documento foi lido; quem não
  respondeu foi outro serviço. O motivo fica em `vinculos_agente.ultimo_erro`.
- **Só caso já vinculado recebe envio automático.** Vincular sozinho criaria caso no
  agente para toda foto que chega pelo portal, inclusive de caso que ninguém abriu lá.
- **A chave de idempotência é o id da entrega.** Reenviar não duplica documento do
  outro lado, e o vínculo guarda o que já foi para não reenviar o caso inteiro a cada
  abertura do dossiê.
- **Agente fora do ar nunca vira caso vazio.** A etapa fica `indisponivel` com o
  motivo, e a tela diz isso. "Não consegui olhar" e "não há nada" levam a decisões
  opostas.
- **A qualificação do contrato não vira fato.** Os documentos já produzem os mesmos
  fatos com proveniência; registrar de novo pelo contrato criaria uma segunda versão
  da mesma verdade, sem origem conferível. O que se faz é **conferir**: CPF digitado
  na entrevista contra o CPF lido da CTPS. Divergência antes da assinatura custa uma
  conferência; depois, um aditivo.

**Medido em 13/08**, com os dois no ar: caso criado no Acervo, CTPS entregue, e o
agente devolveu 3 fatos com origem rastreável (`ocr_document, página 1, campo pis`).
A ficha do cliente do dossiê é montada a partir desses fatos, não de digitação.

**Duas descobertas da validação, ambas de configuração:**

1. **O worker do agente estava de pé mas não consumia a fila.** Cinco documentos
   ficaram parados em `dramatiq:document_processing` sem erro visível; reiniciar o
   worker drenou tudo. Vale um alarme de fila parada — o sintoma é "o dossiê não
   mostra os fatos", e ninguém vai olhar a fila.
2. **Os contêineres do agente subiam sem as chaves.** O `docker-compose.yml` de lá
   não passava `.env`, então não havia provedor de IA nem corpus: a análise saía sem
   classificação e a pesquisa falhava com `CORPUS_NOT_CONFIGURED`. Corrigido com
   `env_file: .env` nos serviços `api` e `worker`.

Configuração: `AGENTE_API_URL` (vazio desliga tudo), `AGENTE_TOKEN`,
`AGENTE_JURISDICAO_PADRAO` (TRT8 — é ela que restringe quais precedentes valem).

Migração para os bancos de verdade: **`docs/PLANO-BANCOS.md`**.

Testes: `.venv\Scripts\python.exe -m tests.test_agente` (sem rede, com dublê).

---

## PENDENTE — diarização pós-entrevista com pyannote

Adicionar `pyannote.audio` com o pipeline local
`pyannote/speaker-diarization-community-1`, usando `num_speakers=2` e, de
preferência, `exclusive_speaker_diarization` para alinhar os intervalos com os
segmentos temporais do Faster-Whisper.

**Decisão arquitetural:** não colocar pyannote no preenchimento ao vivo. O
pipeline oficial não é streaming, acrescenta latência e VRAM e devolve rótulos
anônimos (`SPEAKER_00`/`SPEAKER_01`). Durante chamadas, a faixa remota do Jitsi
já identifica a voz do cliente; manter o filtro textual de enunciado na escuta
ao vivo. A diarização entra como tarefa assíncrona depois que o áudio completo
for fechado, especialmente para entrevistas presenciais com microfone único.

Saída pretendida:

- cruzar os intervalos do pyannote com os timestamps do Whisper;
- identificar o advogado pelo locutor que lê os enunciados conhecidos;
- rotular o outro locutor como cliente, guardando também os ids originais;
- produzir transcrição final `Advogado:`/`Cliente:` para auditoria e PDF;
- nunca substituir a transcrição bruta nem apagar trechos de baixa confiança;
- executar em fila própria ou sob a trava de GPU, sem concorrer com OCR e
  Whisper durante a entrevista.

Pré-requisitos externos: aceitar os termos do modelo no Hugging Face, criar
`HUGGINGFACE_TOKEN`, garantir FFmpeg e medir tempo/VRAM nesta máquina antes de
ativar por padrão. Não usar o pipeline legado `speaker-diarization-3.1` em
implementação nova.
