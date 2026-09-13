# UI_REFACTOR_HANDOFF

Atualizado em 13/09/2026, **sessão 2** (Claude Code). Fonte de verdade da migração visual.
**A refatoração completa ainda não terminou.** A base do design system está sólida e validada; vários módulos já migraram. Não confundir "herdou os tokens" com "o fluxo foi revisto".

> Este arquivo substitui a versão da sessão 1. O que aquela sessão fez continua descrito aqui; o que a sessão 2 acrescentou está marcado com **[s2]**.

---

## 1. Objetivo do redesign

LegalTech premium, SaaS moderno, Navy + Gold sobre superfícies claras. Prioridades, nesta ordem: hierarquia, legibilidade, densidade operacional, acessibilidade e responsividade.

- Gold (`--marca-ouro`) é **acento e CTA**, nunca preenchimento decorativo.
- Navy é a cor da navegação e da identidade; não vira cor de ação.
- Sem símbolos jurídicos decorativos (balança, martelo) na interface de trabalho.
- Preservar APIs, regras de negócio, autenticação, permissões, chamadas e estados de atendimento.

O pedido original está nos anexos do usuário e em `../Refatoração UI-UX — LegalTech Navy & Gold.md`. Os HTMLs de referência ficam **um nível acima** desta raiz Git. Não publicar nem fazer deploy automaticamente.

---

## 2. Design system definido

Fonte dos valores: `frontend/src/app/globals.css`, exportados ao Tailwind em `@theme inline`.

### Paleta / tokens

| Token | Valor claro / finalidade |
|---|---|
| `--fundo` | `#F6F7F9` |
| `--papel` / `--papel-2` / `--papel-3` | `#FFFFFF` / `#F8F9FB` / `#EEF1F5` |
| `--tinta` / `--tinta-2` / `--tinta-3` | `#172033` / `#465166` / `#697386` |
| `--nav-fundo` / `--nav-fundo-ativo` / `--nav-fundo-hover` | `#0A1322` / `#16243A` / `#122036` |
| `--nav-texto` / `--nav-texto-2` / `--nav-texto-3` / `--nav-borda` | `#F6F7F9` / `#D5DCE7` / `#9BAAC0` / `#233047` |
| `--acao` / `--acao-forte` | `#0B1628` / `#16243A` |
| `--acao-texto` | `#0B1628` claro; `#B9D2F2` escuro — **cor de texto**, separada do preenchimento |
| `--acao-clara` / `--acao-borda` | `#EEF1F5` / `#CED6E2` |
| `--marca-ouro` / `--marca-ouro-hover` / `--marca-ouro-suave` | `#C6A15B` / `#B28A43` / `#E2C98D` |
| `--marca-ouro-claro` / `--marca-ouro-texto` | `#FAF5E9` / `#76591F`; `#302A20` / `#E2C98D` no escuro |
| `--primario-texto` | `#0B1628` nos dois temas (texto sobre Gold) |
| `--borda` / `--borda-forte` / `--borda-campo` | `#E5E7EB` / `#E5E7EB` / `#7A8B9F` |
| `--critico` / `--atencao` / `--ok` | `#B3261E` / `#8A5300` / `#1C6B3E` (texto de estado legível) |
| `--perigo-marca` / `--aviso-marca` / `--sucesso-marca` | `#C74444` / `#C88719` / `#16865C` (marcas; não substituem o texto de estado) |
| `--foco` | `#1F6FEB` claro; `#79B8FF` escuro |

### Tipografia
- Archivo em `--fonte-ui` e `--fonte-titulo`. Newsreader permanece carregada para branding/documentos. IBM Plex Mono para códigos.
- Escala: 13, 14, 15, 17, 22, 28 px. Ainda há microtextos legados de 10–12 px a revisar (P2).

### Espaço, raio, sombra
- Espaços nomeados: 4, 8, 12, 16, 24, 32 px (`--espaco-*`). Utilitários Tailwind continuam válidos.
- Raios: cartão 12 px (`rounded-cartao`), campo/botão 8 px (`rounded-campo`), selo 999 px (`rounded-pill`).
- Sombra de cartão: `0 1px 2px rgba(20,32,46,.04), 0 3px 12px rgba(20,32,46,.025)`.

### Componentes
- **Botões** (`Botao` / `LinkBotao`, variantes compartilhadas): `primario` = Gold + texto Navy, hover `#B28A43`; `secundario` = branco com borda; `perigo` = vermelho; `discreto`; `texto`. `carregando` **não** vira `disabled` (ver comentário no primitivo).
- **Campos** (`Campo`, `CampoSeletor`): mínimo 42 px, `--borda-campo`, foco visível, `disabled` e `aria-invalid` tratados no primitivo. **[s2]** Em telas de filtro, botões da mesma linha recebem `min-h-[42px]` explícito para alinhar com os campos.
- **Cartões** (`Cartao`), **tabelas** (`Tabela`/`Th`/`Td`/`TrZebra`) preservam densidade, hover e zebra.
- **Selos** (`Selo`) e **avisos** (`Aviso`): símbolo + palavra, nunca cor sozinha.
- **Abas** (`BarraAbas`/`BotaoAba`): superfície clara com filete Gold.
- **[s2] `Esqueleto`** (novo, em `Basicos.tsx`): bloco de carregamento com brilho, `motion-reduce:animate-none`. Substituiu três cópias manuais da mesma faixa. Semântica: `Esqueleto` = "ainda não chegou resposta"; `Vazio` = "chegou e veio vazio"; número real = "chegou zero". **Não trocar um pelo outro.**
- **Cabeçalho de página** (`CabecalhoPagina`): `contexto` (eyebrow) + `h1` + `descricao` + `acoes`. É o padrão de **todo módulo**.
- **Sidebar**: 248 px no desktop; gaveta de 264 px limitada a 82vw no móvel, breakpoint 1024 px. Busca sem acentos, grupos semânticos. Sem collapse no desktop nesta etapa.
- **Modais**: fundo `bg-tinta/40`, painel `rounded-cartao bg-papel`. **[s2]** Foco contido via `useFocoContido`.
- **IA**: filete Gold no cabeçalho do ajudante, balões do usuário em Navy. Não criar cartões chamativos para toda resposta.

### Estados
- Tema claro é o padrão; a preferência salva do usuário é respeitada. Seletor no cabeçalho do escritório e flutuante nas demais rotas; troca sincroniza desktop/mobile.
- Anel de foco global: `:focus-visible { outline: 3px solid var(--foco) }` — **fora de `@layer`, de propósito** (ver §8).
- **[s2]** Em botões e links, usar `focus-visible:ring-2 focus-visible:ring-foco`. `focus:ring-*` (sem `-visible`) fica só para campos de texto, onde acender no clique é correto.

---

## 3. Referências

São **moodboards, NÃO código da aplicação**. Não importar HTML de Behance/Envato para React.

Na pasta pai desta raiz:
- `ERP System Law Office _ SaaS Dashboard UI_UX Case Study __ Behance.html` — estrutura Navy e tipografia de produto.
- `SaaS Law firm dashboard __ Behance.html` — componentes compactos, agrupamento de informação, espaço entre blocos, estados discretos.
- `Law Firm Dashboard UI_UX Case Study __ Behance.html` — fonte e imagem identificadas; revisão visual integral da imagem longa ainda pendente.
- `Painel ... LegacyHub ... Envato.html` e `Randika Portfolio.html` — fontes inspecionadas; revisão detalhada pendente.

Os diretórios `_files` desses HTMLs não estavam presentes. Parte das imagens foi recuperada dos `srcset` para `%TEMP%/forense-ui-review`.
**Atenção:** as cores CSS predominantes dos HTMLs do Behance são do **site hospedeiro**, não do dashboard retratado — não usá-las como paleta do produto.

Há também protótipos preexistentes em `frontend/design/*.html`; **não** foram incorporados ao app.

---

## 4. O que já foi refatorado

### Base do sistema
- **[CONCLUÍDO]** Tokens claros Navy + Gold, CTA compartilhado, tipografia operacional, fundo limpo.
- **[CONCLUÍDO]** `CabecalhoPagina` — cabeçalho reutilizável de módulo.
- **[CONCLUÍDO] [s2]** `Esqueleto` — primitivo de carregamento (removeu 3 duplicações).
- **[CONCLUÍDO] [s2]** `useFocoContido` (`src/lib/foco.ts`) — contenção de Tab + devolução de foco, extraída da sidebar e reaproveitada nos modais.
- **[CONCLUÍDO] [s2]** **Correção de cascata em `globals.css`**: `h1–h4`, `a`, `button/select/input/textarea` e `::placeholder` foram para dentro de `@layer base`. Ver §8 — era um bug que anulava utilitárias em toda a aplicação.
- **[CONCLUÍDO] [s2]** Contraste no escuro: as 57 ocorrências de `text-acao` viraram `text-acao-texto`. Não restou nenhuma.

### Layout
- **[CONCLUÍDO]** Sidebar: grupos, busca de módulo, invisibilidade quando fechada no móvel, Escape, foco inicial/contido/devolvido, fechamento ao ampliar para desktop.
- **[CONCLUÍDO] [s2]** `AppShell`: a topbar deixou de repetir o título da página. Virou **barra de localização** (`[← Voltar] Carteira › Módulo`) e absorveu a migalha, que agora só existe abaixo de `lg`. Antes havia três camadas dizendo o mesmo nome.

### Módulos
- **[CONCLUÍDO] [s2]** Central de Documentação (`CentralDocumentacao.tsx`): carregamento inicial com esqueleto, erro de fila separado de erro de ação, estado bloqueante com "Tentar agora" quando o servidor nunca respondeu, horário da última atualização confirmada, `CabecalhoPagina`.
- **[CONCLUÍDO] [s2]** Login (`page.view.tsx`): retokenizado por completo — **0 cores hardcoded** (eram 29). Corrigiu contraste de ~1,3:1 (título, subtítulo e rótulos invisíveis no tema claro) e trocou o CTA azul pelo Gold do sistema.
- **[CONCLUÍDO] [s2]** Cabeçalho migrado para `CabecalhoPagina` em: **Usuários, Supervisão, Saúde do agente, Investigação, Operação, Acompanhamento (FollowUp), Roteiros, Glossário de documentos, Dados, Jurimetria**. Todos verificados: exatamente um `h1` e sem quebra quando a API falha.
- **[CONCLUÍDO] [s2]** `ChangePasswordModal`: foco contido, `aria-describedby` no erro de divergência, rótulos no peso do sistema, painel com altura máxima.
- **[PARCIAL] [s2]** Casos/clientes (`ListaCasos.tsx`): no celular o cadastro começa fechado atrás do botão "Novo caso" e os filtros secundários recolhem — a lista agora aparece na primeira tela. Filtros migrados para os primitivos e a grade realinhada (datas em par). Falta paginação e exclusão confirmada nas fixtures.
- **[PARCIAL] [s2]** Entrevista (`TriagemEntrevista.tsx`): ganhou `h1` próprio via `CabecalhoPagina` (era a única tela sem `h1`), anéis de foco no padrão, cartões de escolha com borda de 1 px e salto curto. `Roteiro.tsx`, `EntrevistaComChamada.tsx` e `PainelEscuta.tsx` **não** foram revistos.
- **[PARCIAL] [s2]** Modais de negócio: `VisorEntrega`, `EditorRoteiro`, `ImportarRoteiro`, `SeletorDeRoteiro` ganharam foco contido e canto do sistema; Esc foi adicionado só onde não há rascunho em risco.
- **[PARCIAL]** Dashboard/Carteira: cabeçalho sem decoração, atalhos limitados a quatro funções frequentes.
- **[PARCIAL]** Workspace do caso: abas com Gold discreto; Checklist/Dados/Jurimetria sem gradiente.
- **[PARCIAL]** IA: contraste de balões e acento no ajudante. Não validado contra serviço real.
- **[NÃO INICIADO em profundidade]** Petições e revisão (`ModelosDePeticao` tem cabeçalho, o resto não), portal do cliente (já está nos tokens, mas sem revisão de fluxo), chamada pública, configurações.

---

## 5. Arquivos alterados

Caminhos a partir desta raiz. Use `git diff` para o detalhe — **não descartar mudanças**. Total atual: **54 arquivos, ~973 inserções / ~811 remoções**.

### Novos
| Arquivo | Por quê |
|---|---|
| `frontend/src/components/ui/CabecalhoPagina.tsx` | Cabeçalho de módulo reutilizável (contexto + h1 + descrição + ações). |
| `frontend/src/lib/foco.ts` **[s2]** | `useFocoContido` — contenção de Tab e devolução de foco para diálogos e gavetas. |
| `frontend/scripts/ui-review.cjs` | Regressão visual com fixtures e screenshots, sem API real. |

### Base / design system
| Arquivo | Por quê |
|---|---|
| `frontend/src/app/globals.css` | Tokens; **[s2]** regras de elemento movidas para `@layer base`. |
| `frontend/src/components/ui/Basicos.tsx` | Botões, campos, abas, hover de tabela, contraste; **[s2]** primitivo `Esqueleto`. |
| `frontend/src/components/ui/AlternadorTema.tsx`, `frontend/src/app/layout.tsx` | Tema claro padrão, controle no cabeçalho, sincronização. |

### Layout
| Arquivo | Por quê |
|---|---|
| `frontend/src/components/layout/AppShell.tsx` | **[s2]** Topbar virou barra de localização; migalha absorvida; `DESCRICAO_TELA` removido. |
| `frontend/src/components/layout/BarraLateral.tsx` | Navegação, busca, mobile; **[s2]** foco delegado a `useFocoContido`. |
| `frontend/src/app/home/home.view.tsx` | Cabeçalho no desktop; **[s2]** sinal `pedidoNovoCaso`; chamadas sem `onVoltar` nos módulos migrados. |

### Telas
| Arquivo | Por quê |
|---|---|
| `frontend/src/app/page.view.tsx` **[s2]** | Login retokenizado, CTA Gold, contraste corrigido. |
| `frontend/src/app/ChangePasswordModal.tsx` **[s2]** | Foco contido, `aria-describedby`, altura máxima. |
| `frontend/src/components/documentacao/CentralDocumentacao.tsx` **[s2]** | Carregamento, erros separados, retry, `CabecalhoPagina`. |
| `frontend/src/components/carteira/ListaCasos.tsx` **[s2]** | Cadastro e filtros recolhíveis no celular; primitivos; grade realinhada. |
| `frontend/src/components/carteira/Carteira.tsx` | Hierarquia do dashboard; **[s2]** usa `Esqueleto`. |
| `frontend/src/components/caso/PainelCaso.tsx` **[s2]** | Usa `Esqueleto`. |
| `frontend/src/components/entrevista/TriagemEntrevista.tsx` **[s2]** | `CabecalhoPagina` + `h1`; foco e microinteração dos cartões. |
| `admin/Usuarios`, `admin/Supervisao`, `SaudeAgente`, `carteira/Investigacao`, `operacao/Operacao`, `admin/FollowUp`, `admin/CatalogoRoteiros`, `admin/GlossarioDocumentos`, `caso/Dados`, `admin/Jurimetria` **[s2]** | Cabeçalho migrado para `CabecalhoPagina`; botão "Voltar" duplicado removido; prop `onVoltar` eliminada onde ficou sem uso. |
| `caso/VisorEntrega`, `entrevista/EditorRoteiro`, `entrevista/ImportarRoteiro`, `entrevista/SeletorDeRoteiro` **[s2]** | Foco contido, canto do sistema, Esc onde é seguro. |
| `chamada/PainelChamada` **[s2]** | Anel de foco no padrão (`focus-visible` + `--foco`). |
| `frontend/src/components/Panorama.tsx`, `ModelosDePeticao.tsx` | Cabeçalho compartilhado. |
| `caso/Checklist`, `caso/CasoWorkspaceTabs`, `documentacao/CentralDocumentacao`, `entrevista/TriagemEntrevista` | Remoção de gradientes nos cabeçalhos (não são refatorações completas). |
| `AgenteGeral.module.css`, `AjudanteDoCaso.module.css` | Balões Navy e acento IA. |
| ~25 arquivos restantes | Somente a troca `text-acao` → `text-acao-texto` **[s2]**. `git diff --numstat` mostra 1–3 linhas em cada. |

### Documentação
| Arquivo | Por quê |
|---|---|
| `docs/GUIA-VISUAL.md` | Aviso de atualização; medições/tabela históricas **não** representam os tokens novos. |

---

## 6. O que falta fazer

### P0 — validar e não regredir

1. **Validar com backend de desenvolvimento e sessão autorizada** os fluxos caso → documentos → entrevista → petição. Todos os testes desta sessão usam fixtures; **nenhuma integração real foi exercida**.
2. **Revisar visualmente as telas que a correção de `@layer base` tocou sem screenshot.** A correção fez `text-sm`/`text-xs` voltarem a valer em **todo `<button>`**, e cores voltarem a valer em `h1–h4` e `<a>`. Onde havia um botão herdando 15 px e declarando `text-xs`, ele agora tem 12 px de verdade. Foram conferidos: dashboard, casos (claro/escuro/móvel), documentação (3 estados + móvel), entrevista, login, 9 módulos admin. **Não** foram conferidos: workspace do caso, petições, revisão, portal autenticado, chamada.
   - Arquivos-alvo: qualquer `<button>` com `text-[10px]`/`text-[11px]`/`text-xs`.
3. **Auditar os `h1–h4` que declaram `text-tinta-3`** — eles eram silenciosamente ignorados e agora ficam cinza de verdade: `admin/FluxoPeticao` (3×), `admin/FollowUp` (2×), `caso/Dados`, `caso/PainelJurimetriaCaso` (3×), `caso/ResumoDocumentos`. Confirmar se cinza é mesmo o desejado em cada um.

### P1 — cobertura dos módulos

1. **Entrevista (o grosso do que sobrou):** `EntrevistaComChamada.tsx` (593), `Roteiro.tsx` (2886), `PainelEscuta.tsx` (346), `Conducao.tsx` (374). Preservar transcrição, chamada e edição; reforçar progresso e foco nas perguntas.
2. **Documentos:** `Checklist.tsx`, `PainelEnvio.tsx` — revisar busca, estados e feedback dos uploads. (`CentralDocumentacao` já está pronta.)
3. **Petições e revisão:** `admin/FluxoPeticao.tsx`, `ModelosDePeticao.tsx`. **`ModelosDePeticao` contém a prévia do documento — a apresentação dela NÃO segue o tema da UI** (ver §8).
4. **Portal do cliente e chamada pública:** `app/portal/[token]/page.tsx`, `app/chamada/[sala]/page.tsx`. Já usam tokens (0 cores hardcoded) e não transbordam em 390 px; falta revisar o fluxo autenticado e os modais. **Não alterar autenticação/CAPTCHA/2FA.**
5. **Configurações e assinatura:** `configuracaoAssinatura`, `admin/ModelosContrato.tsx`.
6. **`ListaCasos`:** expandir fixtures para paginação e exclusão confirmada.
7. **Lint:** não existe script nem configuração de ESLint. Adicionar `eslint` + `eslint-config-next` é uma decisão com dependências novas — **confirmar com o usuário antes**.

### P2 — polish

- Auditar tamanhos abaixo de 13 px, raios e fontes hardcoded remanescentes.
- **`cn` dos primitivos não resolve conflito de Tailwind** — ver §8, item "cn". Decisão registrada, não executada.
- `Botao` não define `type` padrão; fora de `<form>` é inofensivo, mas `type="button"` explícito é mais seguro (já aplicado nos botões novos de `ListaCasos`).
- Avaliar grupos recolhíveis/collapse na sidebar; não quebrar permissões nem busca.
- `EditorRoteiro` precisa de confirmação de "descartar alterações?" — só então faz sentido ligar Esc nele.
- Revisar microinterações e espaçamentos restantes.
- Atualizar a tabela histórica e as medições de contraste de `docs/GUIA-VISUAL.md`.
- `CABECALHO.entrevista` em `home.model.ts` não é mais renderizado (o título vive em `TriagemEntrevista`); remover ou anotar.

---

## 7. NEXT ACTION

**Abra `frontend/src/components/entrevista/EntrevistaComChamada.tsx`, `frontend/src/components/entrevista/Roteiro.tsx` e `frontend/src/components/ui/Basicos.tsx`.**

A entrevista é o maior fluxo ainda não revisto e o único P1 que sobrou inteiro. A tela de entrada (`TriagemEntrevista`) **já** está migrada: tem `CabecalhoPagina` com `h1`, selos de etapa em `acoes` e cartões de escolha no padrão — **use-a como referência e não a refaça**.

Nesta ordem:

1. Em `EntrevistaComChamada.tsx`, aplique os primitivos (`Cartao`, `Selo`, `Aviso`, `Botao`) nos blocos que hoje montam caixa à mão, e verifique o contraste dos avisos de processamento. **Preserve intactos**: `useChamada`, os handlers de transcrição, os intervalos de presença e as props `onRespostas`/`onConcluir` — elas alimentam as etapas de baixo antes de a entrevista fechar.
2. Em `Roteiro.tsx`, não tente reescrever o arquivo (2886 linhas). Limite-se a: campos e botões nos primitivos, estados de progresso legíveis, e o realce `data-realce` que já existe em `globals.css` (`.roteiro-contentor`) — ele é setado fora do ciclo do React de propósito, **não converta em classe condicional**.
3. Depois de cada bloco, rode `npm run build` e `node scripts/ui-review.cjs` (receita em §10).
4. Acrescente uma fixture de entrevista ao script para cobrir a tela com roteiro aberto — hoje ela só é verificada no estado "Como você quer começar?".

Em seguida, siga para P1 #2 (Documentos: `Checklist.tsx`, `PainelEnvio.tsx`).

---

## 8. Decisões importantes

- **Arquitetura:** Next 16 / React 19 / Tailwind 4 e os componentes existentes. **Nenhuma biblioteca de UI nova.** Ler `node_modules/next/dist/docs/` antes de mexer em API do Next (ver `frontend/AGENTS.md`).
- **`/home` alterna módulos por estado**, não por rotas. Não converter: a chamada e o atendimento precisam sobreviver à troca de tela.
- **Sidebar** mantém `podeAbrirTela`, permissões filtradas e ordenação por módulos da sessão. Não inventar módulos de "Clientes"/"Insights" — clientes pertencem aos casos.
- **`--acao` não virou Gold.** Ele preenche gráficos e estados. O CTA Gold ficou isolado na variante `primario` para o dourado não se espalhar.
- **`--acao-texto` é a cor de texto; `--acao` é preenchimento.** No escuro `--acao` é azul `#1f6feb` (≈2,9:1 sobre `--acao-clara`) e `--acao-texto` é `#B9D2F2` (≈8,5:1). **[s2]** Já não existe `text-acao` no código — se for reintroduzir, use `text-acao-texto`.
- **[s2] Regras de elemento vão em `@layer base`.** `@import "tailwindcss"` declara as camadas; regra **fora** de camada vence qualquer regra **dentro** de camada, independentemente de especificidade. Com `h1–h4 { color }`, `a { color }` e `button { font-size: inherit }` soltos, o resultado medido no navegador era: `<h2 class="text-tinta-3">` saía `--tinta`; `<a class="text-critico">` saía `--acao-texto`; `<button class="text-sm">` dentro de um pai de 30 px saía **30 px**. Era também a razão do `!text-[...]` no título do login. **Não tirar essas regras de `@layer base`.**
- **[s2] `:focus-visible` continua FORA de camada, de propósito** — o anel de foco é garantia de acessibilidade e não deve poder ser desligado por classe utilitária.
- **[s2] A topbar do AppShell não repete o título da página.** Ela diz *onde você está* (`Carteira › Módulo`), e o `h1` do módulo diz *o que é*. Repetir o nome em 1,35 rem no topo, na migalha e no `h1` gastava ~90 px de altura sem informar nada. `DESCRICAO_TELA` foi removido junto (a descrição vive no `descricao` do `CabecalhoPagina`).
- **[s2] O "Voltar" é do AppShell.** Módulos não desenham o próprio botão de voltar — havia dois empilhados. A prop `onVoltar` saiu de `Usuarios`, `Supervisao`, `SaudeAgente`, `Investigacao`, `CatalogoRoteiros` e `GlossarioDocumentos` (e das chamadas em `home.view.tsx`).
- **[s2] Cabeçalho de módulo não tem ícone.** `CatalogoRoteiros` e `GlossarioDocumentos` tinham um selo com ícone ao lado do `h1`; foi removido porque nenhum outro cabeçalho tem um e a identidade do módulo já está no ícone da sidebar.
- **[s2] `pedidoNovoCaso` é contador, não booleano.** No celular a tela de casos abre com o cadastro fechado; o atalho "Novo caso" da Mesa do dia precisa viajar como sinal. Um booleano dispararia uma vez só e o atalho pararia de funcionar no segundo clique.
- **[s2] Esqueleto ≠ Vazio ≠ zero.** Mostrar `0` antes da primeira resposta do servidor faz um painel de plantão mentir sobre a fila. A Central de Documentação separa os três estados e o `ui-review.cjs` **testa** que o resumo não aparece antes da resposta.
- **[s2] Erro de fila e erro de ação são canais separados.** Com um `erro` só, "não consegui assumir o atendimento" aparecia como se a lista inteira tivesse caído.
- **[s2] `PainelDocumentacao.tsx` é código morto.** Nada o importa (confirmado em todo o repositório) — é uma versão anterior de `CentralDocumentacao`. **Não refatore esse arquivo**; a decisão de apagá-lo é do usuário.
- **[s2] `cn` dos primitivos (`Basicos.tsx`) NÃO resolve conflito de Tailwind** — é um `join` simples, e o autor original registrou que queria evitar dependência nova. Só que `tailwind-merge` **já é dependência** e `src/lib/utils.ts` exporta um `cn` com `twMerge` que **ninguém usa**. Consequência: `className` passado a um primitivo pode não sobrescrever a classe base (ex.: `min-h-10` contra `min-h-[42px]`). Foi contornado com valores explícitos em `ListaCasos`. **Trocar para o `cn` de `utils.ts` é a correção certa, mas muda aparência em componentes sem screenshot — faça com verificação visual, não às cegas.**
- **Não copiar estilos da prévia de petição para a UI.** O documento exportado tem identidade própria, configurável pelo escritório.
- **Dashboard não repete a sidebar.** Atalhos frequentes: entrevista, casos, documentação e leitura avulsa.

---

## 9. Cuidados / não quebrar

- **Nenhum backend, schema, API, dependência de produção ou regra de autorização foi alterado** em nenhuma das duas sessões.
- `BotaoProcesso` distingue pendência, processamento e falha. **Não** substituir a semântica por um `disabled` genérico.
- Credenciais de portal recém-criado ficam **só em memória**; não persistir nem colocar em fixtures reais.
- Chamadas Jitsi/WebSocket, transcrição, intervalos de presença e assinatura devem permanecer nos handlers atuais.
- Na Central de Documentação: **não alterar** o heartbeat de 30 s, o polling de 5 s, a convocação ou o `assumir`. A rotina `carregar` é reutilizada pelo botão "Tentar agora" — mantenha-a idempotente.
- Propostas de IA exigem confirmação. Acento visual não significa aprovação automática.
- **[s2] `EditorRoteiro` guarda rascunho e `aoFechar` descarta sem perguntar.** Por isso Esc **não** foi ligado ali. Não ligue antes de existir confirmação de descarte.
- **[s2] Os modais de roteiro rolam pelo fundo** (`items-start overflow-y-auto` no backdrop). Não colocar `max-h` + `overflow-y-auto` no painel: cria dois scrollers aninhados.
- Sem `JWT_SECRET`, o proxy local libera `/home` por comportamento preexistente. **Não** alterar configuração de segurança para teste visual.
- A CSP de produção bloqueia conexão a `localhost:8100` sem origem correspondente. O script usa `bypassCSP` **somente** no navegador de teste e intercepta todas as APIs; a política da aplicação não foi relaxada.
- **Windows PowerShell** pode converter Unicode em `?` ao enviar script para Python. Use `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)` antes do pipe, ou escreva o patch em arquivo e rode `python arquivo.py`. **[s2]** O Git Bash também engasga com heredoc contendo certo texto acentuado — escrever o script em arquivo e executá-lo foi o caminho confiável.
- Git avisa conversão LF/CRLF em quase todo arquivo tocado. É ruído do `autocrlf`, não mudança de conteúdo — `git diff --numstat` confirma 1–3 linhas nos arquivos de troca simples.
- **Não houve deploy, commit ou envio a serviço externo.** O diff Git estava limpo antes da sessão 1.

### Bugs conhecidos / em aberto
- Nenhum erro de execução nos caminhos cobertos (`pageerror` vazio em todas as rodadas).
- `CABECALHO.entrevista` (`home.model.ts`) é dado morto desde que o título foi para `TriagemEntrevista`.
- `PainelDocumentacao.tsx` órfão (ver §8).

---

## 10. Validação

Executado a partir de `frontend/`, salvo indicação. **Estado ao fim da sessão 2: tudo abaixo passando.**

| Comando | Resultado |
|---|---|
| `npm ci --no-audit --no-fund` | sucesso (lockfile) |
| `npm run typecheck` | **passou** |
| `npm run build` | **passou** (Next 16.2.12; inclui TypeScript e geração de rotas) |
| `node --test src/lib/atalhoDeCaso.teste.mjs src/lib/transcricao.teste.mjs` | **passou** — 2 arquivos, 2 testes, 0 falhas |
| `node scripts/ui-review.cjs` | **passou** — ver cobertura abaixo |
| `npm run lint` | **indisponível** — `Missing script: lint`. Não foi apresentado como aprovado. |
| `git diff --check` | passou |

### Cobertura do `ui-review.cjs` (Edge headless / Playwright)
- Sem transbordo horizontal em 1440 / 1024 / 768 / 390 px, e em 390 px na Central de Documentação.
- Casos: busca sem acentos, zero resultados e recuperação, limpar filtros.
- **[s2]** Casos no celular: o cadastro começa fechado, a lista aparece, abrir leva o foco ao primeiro campo, fechar devolve a lista ao topo.
- **[s2]** Central de Documentação: falha inicial **não** mostra o resumo; "Tentar agora" recupera; filtro "Chamando equipe" esconde quem não chamou; retrato claro, escuro, sem-dados e móvel.
- **[s2]** Entrevista guiada: `h1` de nível 1 presente; só **um** módulo com `aria-current="page"`.
- **[s2]** Nove módulos migrados: `h1` único e correto, sem quebra com a API em 503.
- Tema sincronizado e persistido após reload; foco contido na gaveta; Escape fecha; busca de módulo.
- Sem erros de execução (`pageerror`) em nenhum caminho.

**Limites — leia antes de confiar:** todos os dados são fixtures. **Não** foram testados upload real, criação/exclusão real, sessão real, chamada, transcrição ou serviços de IA. Screenshots em `%TEMP%/forense-ui-review/`.

### Reproduzir (PowerShell, Edge instalado)

```powershell
# Terminal 1, em frontend:
npm run build
npm run start -- --hostname 127.0.0.1 --port 3100

# Terminal 2, em frontend:
npm install --prefix "$env:TEMP/forense-ui-tools" playwright --no-audit --no-fund
$env:PLAYWRIGHT_PATH = Join-Path $env:TEMP 'forense-ui-tools/node_modules/playwright'
node scripts/ui-review.cjs
```

A instalação do Playwright é temporária e fora do projeto. `UI_REVIEW_URL` aponta para outra URL local. **Não executar contra produção.**

---

## 11. PROMPT PARA O PRÓXIMO AGENTE

```
Leia UI_REFACTOR_HANDOFF.md na raiz do projeto e frontend/AGENTS.md antes de qualquer coisa.
Depois olhe rapidamente os arquivos já alterados (git diff --stat) para entender o que existe.

Preserve o design system Navy + Gold já implementado: tokens de globals.css, o primitivo
CabecalhoPagina, Basicos.tsx (Botao/Campo/Cartao/Selo/Aviso/Esqueleto) e o hook
useFocoContido. NÃO recomece o redesign e NÃO desfaça as decisões da seção 8 —
principalmente a correção de @layer base, a separação --acao / --acao-texto, e a topbar
que não repete o título da página. Consulte os HTMLs de referência na pasta pai apenas
como moodboard; não importe código deles.

Execute a NEXT ACTION da seção 7: refatorar a entrevista, começando por
EntrevistaComChamada.tsx e depois Roteiro.tsx, usando TriagemEntrevista.tsx como
referência do padrão já migrado. Em seguida siga a fila P0 → P1 → P2 da seção 6.

Implemente de verdade, não apenas sugira. Preserve APIs, permissões, autenticação,
atendimento, transcrição, chamadas e regras de negócio — a seção 9 lista o que não pode
quebrar. Rode npm run build, npm run typecheck e node scripts/ui-review.cjs
periodicamente (receita na seção 10), e amplie o script com fixtures das telas que
você tocar. Atualize este UI_REFACTOR_HANDOFF.md conforme avançar, marcando o que
concluiu e registrando novas decisões e limites de validação.
```
