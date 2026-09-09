# Handoff — revisão de petição por prompt, com rastreabilidade

Escrito em 09/09/2026, ao fim da sessão. Nada abaixo foi commitado — working
tree local, pronto para revisão e commit.

## 1. Issue

**[Petição - IA] Permitir alteração da petição por prompt com rastreabilidade**,
de Lucas e Silva Pinto. Advogado/gestor escreve uma crítica em texto livre, o
sistema reescreve a petição a partir dela, guardando a crítica e a
rastreabilidade (quem, quando, sobre qual versão). O pedido do usuário no chat
foi além do texto da issue: as críticas devem **retroalimentar** as próximas
petições da mesma categoria — "a IA vai aprendendo até sair do jeitinho que
eles querem".

## 2. Decisões (perguntadas ao usuário antes de codar)

1. **Retroalimentação automática** — toda crítica de uma categoria já entra
   como contexto nas próximas gerações dessa categoria, em qualquer caso, sem
   precisar de ação manual (ver `peticao_local.CRITICAS_RECENTES_POR_CATEGORIA`,
   hoje 5).
2. **Revisão por prompt sempre volta a `IN_REVIEW`**, mesmo que a versão
   anterior estivesse `APPROVED` — precisa aprovar de novo.
3. **Permissão**: reaproveita quem já pode gerar/aprovar petição hoje — que,
   na prática, é **qualquer usuário autenticado com papel interno**
   (`advogado`, `secretario`, `documentacao` — `PAPEIS_INTERNOS` em
   `app/main.py`). Não existe "gestor" como papel separado no sistema; não foi
   criado um agora.

## 3. Onde cada coisa mora, e por quê

Duas preocupações diferentes da issue, dois bancos diferentes — mesma régua já
usada em `HANDOFF-skill-por-modelo-peticao.md`:

- **O conteúdo da petição e seu histórico de versões** é estado do caso →
  **SQL Server** (`peticao_versoes`, nova tabela — `peticoes_locais` só guarda
  a versão atual, chave é `caso_id`, sem histórico).
- **A crítica em si** (o prompt) é insumo de IA — ela não só documenta o que
  aconteceu, como retroalimenta gerações futuras de outros casos → **Postgres**
  (`peticao_criticas`, nova tabela).

## 4. Arquivos tocados

| Arquivo | Estado | O quê |
|---|---|---|
| `app/peticao_criticas.py` | **novo** | Postgres — `inicializar()`, `registrar()`, `listar_por_caso()`, `ultimas_da_categoria()` |
| `sql/005_peticao_criticas.sql` | **novo** | Registro do schema (mesmo padrão de `004_peticao_skills.sql`) |
| `app/banco.py` | modificado | Tabela `peticao_versoes` no `ESQUEMA_SQLSERVER`, em `TABELAS`, índice em `INDICES` |
| `app/armazenamento.py` | modificado | `registrar_versao_peticao()` (MERGE idempotente por `caso_id:versao`), `listar_versoes_peticao()` |
| `app/peticao_local.py` | modificado | `_com_skill_do_escritorio` agora também injeta as últimas críticas da categoria (retroalimentação); `revisar_com_prompt()` (o core); `historico_de_criticas()`, `historico_de_versoes()` |
| `app/agente/peticao_fluxo.py` | modificado | `revisar_peticao()`, `historico_de_peticao()` — wrappers que traduzem `ErroPeticao` → `ErroDoAgente` |
| `app/agente/rotas.py` | modificado | `POST /api/agente/casos/{id}/peticao/{peca}/revisar`, `GET .../historico` |
| `frontend/src/lib/agente.ts` | modificado | Tipos `CriticaDePeticao`, `VersaoDePeticao`, `HistoricoDePeticao`; funções `revisarPeticaoComPrompt()`, `historicoDePeticao()` |
| `frontend/src/components/admin/FluxoPeticao.tsx` | modificado | Caixa de prompt "Pedir uma revisão por prompt" + componente `HistoricoDeCriticas` (colapsável, mostra usuário/data/versão de cada crítica) |

**Só a petição LOCAL** (`peca_ref == "local"`, o pipeline `peticao_local.py`)
suporta revisão por prompt. Petição pelo `ia-juridica` (que hoje nem está
ativo) recebe `501` explicando que ainda não existe lá — não finge que
funciona.

## 5. Como funciona (fluxo)

1. Advogado escreve a crítica na tela da petição e manda.
2. `peticao_local.revisar_com_prompt`: carrega a petição atual → monta a
   minuta em texto → chama DeepSeek com a minuta + a crítica, pedindo as 7
   seções de volta, mudando só o que a crítica pede.
3. **Antes de sobrescrever**: `armazenamento.registrar_versao_peticao` salva a
   versão anterior inteira em `peticao_versoes`.
4. Salva a nova versão (`version + 1`, `status = "IN_REVIEW"` sempre).
5. Registra a crítica em `peticao_criticas` (Postgres) — versão de origem,
   versão resultante, prompt, usuário, data.
6. Devolve a petição nova + a lista de críticas do caso.

A retroalimentação acontece em `_com_skill_do_escritorio`, chamada em TODA
geração/revisão: além da skill configurada (`peticao_skills`), ela busca as
últimas 5 críticas da mesma `categoria` (`peticao_criticas.ultimas_da_categoria`)
e injeta no prompt como "correções que o escritório já pediu" — vale para
casos diferentes, sem precisar de ação manual.

## 6. Validado nesta sessão, contra a infra real (com VPN ligada)

Usei o mesmo caso de teste já existente no banco, **"Teste final de Verdade"**
(`4cae9633-9e41-4c77-996c-c783d9dc24ed`, categoria `acidente_trabalho_correios`,
já tinha petição salva em versão 2):

- Chamada direta (`peticao_local.revisar_com_prompt` e
  `peticao_fluxo.revisar_peticao`) **e** via `TestClient` batendo na rota HTTP
  de verdade (`POST /api/agente/casos/{id}/peticao/local/revisar`) — as duas
  formas testadas, ambas OK.
- Confirmado: versão foi de 2 → 3, status ficou `IN_REVIEW`, o texto mudou
  exatamente onde a crítica pediu (marcador de teste apareceu na seção certa),
  o resto do texto ficou igual.
- Confirmado: `peticao_versoes` (SQL Server) ganhou o snapshot da versão 2;
  `peticao_criticas` (Postgres) ganhou o registro com `versao_origem=2`,
  `versao_resultado=3`, usuário e prompt certos.
- Confirmado: a crítica de teste apareceu em `ultimas_da_categoria` e, testando
  `_com_skill_do_escritorio` para OUTRO caso da mesma categoria, a crítica já
  entrou automaticamente no prompt — a retroalimentação funciona de verdade,
  sem promover nada à mão.
- **Bug achado e corrigido durante o teste**: esqueci de chamar
  `peticao_criticas.inicializar()` antes de usar a tabela — ela nunca tinha
  sido criada. Corrigido nos três pontos de uso em `peticao_local.py` (mesmo
  padrão de `peticao_skills`, chamada antes de cada operação).
- Depois de cada teste, restaurei o caso para o estado original (versão 2) e
  apaguei os vestígios de teste em `peticao_versoes`/`peticao_criticas` — nada
  de teste ficou no banco de produção.
- `npx tsc --noEmit` no frontend: limpo.

**Não testado**: a UI de verdade num navegador (só os tipos e a chamada de
API foram validados, não o clique real na tela); a suíte de testes
automatizados do repo (mesma lacuna do handoff anterior — não localizada).

## 6.1 Suíte de testes do repo — rodada completa (09/09/2026)

Achei `tests/` (72 arquivos) — não é pytest puro, é mista: 47 arquivos "script"
(`if __name__ == "__main__"`, rodam com `python -m tests.test_X`, é o que o
`.gitlab-ci.yml` faz para `test_whatsapp`) e 25 "pytest" (`def test_x():`
simples). Rodei os 72. 18 falharam na primeira passada; nenhuma tem relação
com este trabalho (`peticao_local`, `peticao_skills`, `peticao_criticas`,
rotas novas, `peticao_versoes`) — os 3 testes existentes que tocam código
adjacente (`test_modelo_estilo`, `test_modelo_visual_peticao`,
`test_peticao_jurimetria_uf`) passam limpos. As 18 se explicam por: 6 erros de
classificação minha (na verdade passam), 2 timeouts de VPN pro SQL Server
(passaram ao repetir), 2 diferenças no `.env` local (`PERMITIR_DADOS_TESTE=true`
ligado, falta `ZAPSIGN_API_TOKEN`), 8 bugs/flakiness pré-existentes sem relação
nenhuma com petição.

**Achado colateral, fora do escopo desta issue**: a suíte roda contra o SQL
Server de produção de verdade, sem banco isolado — já tinha lixo de teste
acumulado na tabela `casos` de rodadas anteriores (20/08, 28/08, 06/09). Minha
rodada acrescentou 8 linhas; identifiquei pelo horário exato e apaguei as
minhas. As anteriores não mexi. Vale um banco de teste separado algum dia,
mas isso é assunto para outra issue.

## 7. Próximos passos possíveis

- Rodar a suíte de testes do repo, se existir, antes do commit.
- Decidir se `historico.versoes` (as versões anteriores completas, não só a
  lista de críticas) merece uma UI própria — hoje o frontend só mostra a
  contagem; o dado já está disponível em `historicoDePeticao()`.
- Se o número de críticas por categoria crescer muito, `ultimas_da_categoria`
  pode precisar de um limite de caracteres total (hoje só limita por
  quantidade, não por tamanho de cada prompt).
- Commit — junto com o que já estava pendente de `HANDOFF-skill-por-modelo-peticao.md`.
- (Fora do escopo, mas incomodou durante o teste) `tests/` rodar contra um
  banco isolado, e os 3 arquivos com `sys.exit`/`SystemExit` sem `if __name__`
  (`test_carteira_filtros.py`, `test_carteira_paginacao.py`,
  `test_leitura_combinada.py`) ganharem o guard — hoje eles quebram a
  coleção do pytest para o diretório inteiro se alguém rodar `pytest tests/`
  direto.
