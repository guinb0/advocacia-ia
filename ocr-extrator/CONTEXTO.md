# Acervo — onde o projeto está

## Checkpoint da vetorização — pausada em 11/08/2026

A vetorização foi pausada manualmente por instabilidade da internet/banco remoto.
A tarefa `AdvocaciaIA-SincronizarRAG` está **desabilitada** e não voltará a rodar
sozinha até ser reativada.

- textos ingeridos: **5.824 documentos / 52.926 chunks / 1.745 processos**;
- embeddings gravados: **32.967 (62,29%)**;
- pendentes: **19.959**;
- fonte em andamento: `trt8_juris`;
- DJEN, TST e DEJT ainda aguardam vetorização;
- a carga é idempotente e retoma pelos chunks cujo `embedding IS NULL`.

Quando a conexão estiver estável, retomar com:

```powershell
Enable-ScheduledTask -TaskName 'AdvocaciaIA-SincronizarRAG'
Start-ScheduledTask -TaskName 'AdvocaciaIA-SincronizarRAG'
```

Não é necessário apagar nem reingerir dados antes da retomada.

Documento de passagem de bastão. Descreve o que existe, o que foi decidido e
por quê, e o que ficou pela metade. Atualizado em 10/08/2026.

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
  `JWT_SECRET` do vig-agent, as chaves DeepSeek e OpenRouter, e a senha do
  PGVector. Todas passaram por chat.
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
