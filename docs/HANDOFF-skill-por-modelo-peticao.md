# Handoff — skill por modelo de petição + integração ia-juridica desligada

Escrito em 09/09/2026, ao fim de uma sessão. Nada abaixo foi commitado — é tudo
working tree local nos dois repositórios (`advocacia-ia` e `ia-juridica`), pronto
para revisão, teste e commit por quem continuar.

Objetivo deste arquivo: qualquer pessoa (ou outro agente de IA) consegue retomar
sem precisar re-perguntar o que já foi decidido.

---

## 1. Tarefa original (issue)

**[Petição - Modelos] Configurar skill por modelo de petição**, aberta por Lucas e
Silva Pinto. Resumo: permitir configurar uma skill/prompt específica para cada
modelo de petição, persistir a configuração, usá-la na geração/processamento, com
edição restrita a usuário autorizado e sem afetar as demais configurações.

## 2. Decisões tomadas (e por quê)

1. **"Modelo de petição" = `categoria`** (`app/categorias.py`: `acidente_trabalho_correios`,
   `acidente_trabalho_geral`, `doenca_ocupacional`, `auxilio_acidente` — as 4 ativas).
   Não existe hoje mais de um `tipo_peca` (só `INITIAL_PETITION`), então a chave
   ficou só na categoria; o campo dá para virar `(categoria, tipo_peca)` depois
   sem quebrar nada.

2. **Onde persistir: Postgres/pgvector (`advocacia_ia`), não o SQL Server do
   Acervo.** Instrução explícita do usuário: "tudo relacionado a IA vai no
   Postgres, é o único que tem pgvector". O SQL Server (`banco.py`) é para o
   estado operacional do caso (casos, entregas, entrevistas); o Postgres é para
   insumo de IA (RAG, jobs, e agora skills).

3. **Não acoplar ao `ia-juridica`.** O agente está de pé na infra mas
   **desligado de propósito** (`AGENTE_API_URL` vazio no `.env` do Acervo — ver
   §4). A skill roda 100% dentro do `peticao_local.py` (o pipeline "sem agente").
   Quando o `ia-juridica` for ativado, ver §6 para o caminho de migração — ele já
   tem o equivalente pronto (`ConfiguracaoDeGeracao.drafting_instructions`).

4. **Permissão:** reaproveitado o gate que já existe para essa tela inteira —
   `auth.exigir_modulo("agente")` (`PodeManterModeloPeticao` em `main.py`). Não
   criei papel novo.

5. **Versionamento:** não implementado. A issue só pedia "avaliar a necessidade"
   — nenhuma outra config do sistema guarda histórico versionado (roteiros,
   modelos .docx), então não há motivo para esta ser a exceção. Fica como
   "próximo passo possível" em §7 se algum dia for pedido.

---

## 3. O que foi implementado (repo `advocacia-ia`, nada commitado)

| Arquivo | Estado | O que tem |
|---|---|---|
| `app/peticao_skills.py` | **novo** | Módulo Postgres — `_conectar()`, `inicializar()` (`CREATE TABLE IF NOT EXISTS`, idempotente, mesmo padrão de `app/jobs.py`), `salvar()`, `obter()`, `listar()`, `instrucoes_da_categoria()` (nunca propaga erro de conexão — falha vira `""`, prompt padrão continua valendo) |
| `sql/004_peticao_skills.sql` | **novo** | Registro do schema (mesmo padrão de `002_jobs.sql`); quem garante a tabela em produção de fato é o `inicializar()` |
| `app/main.py` | modificado | Import de `peticao_local` e `peticao_skills` no bloco `from . import (...)` (ver §5 — corrige um bug real). Endpoints novos: `GET /api/modelos/peticao/skills`, `PUT /api/modelos/peticao/skills/{categoria}` (ambos atrás de `PodeManterModeloPeticao`) |
| `app/peticao_local.py` | modificado | Import de `peticao_skills`. Novo helper `_com_skill_do_escritorio(caso_id, instrucao)` — busca a categoria do caso e acrescenta a instrução **depois** do contrato do prompt (nunca antes, para não arriscar o formato JSON que `_normalizar_secoes` espera). Aplicado nas 3 chamadas à DeepSeek: `analisar()`, `redigir()`, `gerar()` |
| `frontend/src/lib/api.ts` | modificado | Tipo `SkillDePeticao`, funções `listarSkillsDePeticao()`, `salvarSkillDePeticao(categoria, instrucoes)` |
| `frontend/src/components/ModelosDePeticao.tsx` | modificado | Card novo "Skill de redação por categoria" — select de categoria + textarea + salvar. Funciona **independente** do agente jurídico (ver §4) |

**Fluxo de dados:** `main.py` → `peticao_skills.salvar/obter/listar` (Postgres) →
`peticao_local._com_skill_do_escritorio` injeta no prompt → `_llm_json` manda pra
DeepSeek.

**Verificado nesta sessão:**
- `python -c "import app.main"` no venv real do projeto — carrega limpo (só os
  avisos esperados de `JWT_SECRET`/`PORTAL_SEGREDO` ausentes em dev).
- `npx tsc --noEmit` no frontend — limpo.

**Validado nesta sessão (09/09/2026, com VPN ligada) contra a infra real:**
- `peticao_skills.inicializar()` cria a tabela no Postgres de verdade (`10.200.1.1/advocacia_ia`).
- `salvar`/`obter`/`listar` funcionam; `ON CONFLICT` atualiza sem duplicar linha
  (`criado_em` preservado, `atualizado_em` muda).
- Os dois endpoints testados via `TestClient` (FastAPI real, sem mock): `PUT` em
  duas categorias diferentes com textos diferentes → `GET` confirma que cada uma
  guardou o seu e as outras duas continuam vazias — **é literalmente o cenário
  de teste da issue**, passou. `PUT` em categoria inexistente → `404`.
- `_com_skill_do_escritorio` confirmado: categoria sem skill devolve o prompt
  intocado; categoria com skill acrescenta o bloco no fim.
- Dados de teste foram limpos depois (categorias voltaram a instruções vazias,
  linha de categoria fake removida).
- **Achado, não bug:** a conexão com o pgvector via VPN (`10.200.1.1`) é
  instável — bati timeout e "connection closed" mais de uma vez nos testes,
  inclusive logo depois de ligar a VPN (route ainda "esquentando"). Nesses
  casos o middleware `rede_de_seguranca` do `main.py` devolveu um 503 limpo
  ("tente de novo em instantes") em vez de stack trace, e a chamada seguinte
  funcionou. `instrucoes_da_categoria()` também absorve esse tipo de falha e
  devolve `""` — uma oscilação de rede não derruba a geração de petição.

**Ponta a ponta validado (09/09/2026, mesma sessão):** usei o caso real já no
banco `4cae9633-9e41-4c77-996c-c783d9dc24ed` ("Teste final de Verdade",
categoria `acidente_trabalho_correios`, com documentos OCR e entrevista já
cadastrados). Configurei a skill dessa categoria com um marcador único
(`[TESTE-SKILL-E2E-9f3a1c]`, instrução: "inclua isto no campo `observacoes`") e
chamei `peticao_local.analisar(caso_id, texto_entrevista=...)` — chamada real à
DeepSeek, sem mock. A resposta voltou com
`"observacoes": "[TESTE-SKILL-E2E-9f3a1c] A ..."`: a instrução da skill chegou
ao prompt e foi seguida pelo modelo, ao lado de uma análise real e coerente dos
documentos do caso. Usei `analisar()` (não `gerar()`) de propósito — não
persiste nada em `peticoes_locais`, então nenhum dado do caso real foi tocado.
Skill de teste removida depois (categoria voltou a `instrucoes: ''`).

**Não verificado ainda:** a suíte de testes automatizados do repo (não
localizada nesta sessão — conferir se existe `tests/` e rodar antes do
commit). `gerar()` (que persiste a petição) não foi exercitado neste teste de
propósito, para não sujar `peticoes_locais` de um caso do banco de produção —
mas usa exatamente o mesmo `_com_skill_do_escritorio`, já validado por
`analisar()`.

---

## 4. Bug corrigido no caminho: integração com `ia-juridica`

O `.env` do Acervo tinha `AGENTE_API_URL=http://127.0.0.1:8011` preenchido, o que
"liga" a integração no código (`config().ligado`) mesmo sem nada rodando ali —
cada tela que toca o agente (dossiê, painel, `ModelosDePeticao`) esperava o
timeout inteiro (até 20s) tentando falar com um serviço fora do ar.

- **`.env`** — linha comentada (`# AGENTE_API_URL=...`), com nota explicando como
  reativar. **Isso não vai para o git** (`.env` está no `.gitignore`) — se quem
  continuar clonar de novo ou usar outra máquina, precisa aplicar essa mudança de
  novo à mão, ou documentar em `.env.example`/README que o padrão recomendado é
  vazio até o agente ser ativado de verdade.
- **`ModelosDePeticao.tsx`** — antes chamava `taxonomiaDeEstilo()` (rota do
  agente) sem checar se ele estava ligado, e mostrava erro vermelho. Agora chama
  `configDoAgente()` primeiro (mesmo padrão que `SaudeAgente.tsx` já usava) e
  mostra aviso amarelo calmo "ainda não ativado" quando desligado, sem tentar as
  chamadas que dependem dele. O card de logo/fonte (`modeloVisual`) e o novo card
  de skill continuam funcionando normalmente — são locais, não dependem do agente.

## 5. Bug corrigido no caminho: `peticao_local` nunca importado em `main.py`

`app/main.py` usava `peticao_local.X` em ~10 lugares (rotas do modelo visual,
`/api/casos/{id}/peticao*`) sem NUNCA importar o módulo — só era importado em
`app/agente/rotas.py`. Era um `NameError` real esperando a primeira chamada a
essas rotas. Corrigido junto (adicionado `peticao_local, peticao_skills` ao bloco
`from . import (...)`) e confirmado com `import app.main` no venv real.

---

## 6. Caminho de migração para o `ia-juridica` (quando for ativado)

O `ia-juridica` **já tem** o equivalente desta feature, pronto e mais completo:
`ConfiguracaoDeGeracao.drafting_instructions`, por `taxonomy_code` + `document_type`,
exposto em `/api/v1/style/generation-config` (`GET`/`PUT`), já consumido pelo
card antigo "Configuração da peça" em `ModelosDePeticao.tsx` (esse card só
aparece quando `configAgente.ligado === true`).

Quando o agente for ativado de vez, o corte é limpo porque:

- **Bancos são fisicamente separados.** O Acervo fala com `10.200.1.1:5432/advocacia_ia`
  (pgvector); o `ia-juridica` tem Postgres próprio no compose dele
  (`legal_agent`, container `postgres`). "Migrar" não é mover uma tabela — é
  trocar a implementação por trás de uma função.
- **O ponto de troca é um só:** `_com_skill_do_escritorio` em `peticao_local.py`.
  Troca o corpo de "ler `peticao_skills.instrucoes_da_categoria()`" para "chamar
  `agente.Cliente().configuracao_de_geracao(taxonomy_code=categoria, ...)`" — o
  resto do pipeline (`analisar`/`redigir`/`gerar`) não muda.
- **Vocabulário já bate:** a `categoria` do Acervo e o `taxonomy_code` do
  `ia-juridica` usam os mesmos códigos (confirmado em `ModelosDePeticao.tsx`,
  que já casa os dois ao montar `checklistAcao`).
- Nesse momento, dá para **aposentar** `app/peticao_skills.py` e a tabela
  `peticao_skills` (ou deixar como fallback caso o agente fique indisponível —
  a decidir).

---

## 7. Próximos passos sugeridos (em ordem)

1. ~~Rodar `inicializar()` contra o Postgres de verdade e testar `salvar` →
   `obter` → `listar`~~ — **feito nesta sessão**, ver §3.
2. ~~Testar os endpoints (configurar duas categorias diferentes e validar
   isolamento) e o ponta a ponta com caso real + DeepSeek~~ — **feito nesta
   sessão**, ver §3.
3. **Procurar a suíte de testes do repo** (não localizada nesta sessão) e rodar
   antes de commitar.
4. **Decidir sobre `.env.example`**: vale documentar lá que `AGENTE_API_URL`
   deve ficar vazio até o `ia-juridica` estar pronto para uso, para não repetir
   o problema do §4 em outra máquina/deploy.
5. **Commit.** Ainda não commitei nada — nem isto, nem o resto que já estava
   modificado antes desta sessão (`entrevista.py`, `carteira.py`, `Dossie.tsx`,
   `FollowUp.tsx`, que não são meus, já estavam pendentes). Separar em commits
   por assunto ao invés de um só grande.
6. **(Opcional, não pedido pela issue) Versionamento de skill** — se o
   escritório pedir depois, dá pra guardar histórico numa tabela
   `peticao_skills_historico` (categoria, instrucoes, atualizado_por,
   criado_em) que recebe um INSERT a cada `salvar()`, sem mudar a tabela atual.
7. **(Opcional) Retry na conexão do `peticao_skills.py`** — hoje ele não tem
   retry/backoff pra oscilação de VPN, diferente do `rag.py`
   (`_consultar_pgvector`, que tenta de novo com backoff exponencial). Não é
   bug — o `jobs.py`, que segue o mesmo padrão sem retry, nunca precisou — mas
   se o 503 esporádico incomodar na tela, dá pra copiar o retry do `rag.py`.

---

## 8. Arquivos para ler primeiro, se for retomar do zero

- `app/categorias.py` — o que é "categoria"/"modelo de petição" no sistema
- `app/peticao_local.py` — o pipeline de geração que a skill alimenta
- `app/peticao_skills.py` — o módulo novo
- `app/agente/cliente.py` e `app/agente/config.py` — a ligação com o `ia-juridica`
  (por que ela é segura de deixar desligada, e como reativar)
- `frontend/src/components/ModelosDePeticao.tsx` — a tela, com os dois cards
  (skill local + o antigo, que depende do agente)
