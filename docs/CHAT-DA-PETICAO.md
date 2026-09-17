# Chat da petição — a conversa ao lado da minuta

No Dossiê do caso, a área **Análise e petição** deixou de ser uma página de cartões
parados. Agora ela é uma tela dividida: o **documento à esquerda** e uma **conversa com a
IA à direita**, ancorada, com o histórico salvo por caso.

O que existia antes continua existindo — nenhum botão saiu. O que mudou é que passou a
haver a quem perguntar.

## O problema que isto resolve

A tela mostrava dois quadrados — *Confirmado por documentos* e *Depende de prova ou
confirmação* — e três botões (*Gerar de novo*, *Analisar documentos*, *Gerar esta peça*).
Dava para disparar ação; não dava para **perguntar**. Quem queria entender por que um
ponto estava pendente não tinha a quem perguntar. Quem queria mudar uma linha da peça
tinha de descrever a mudança num campo, sem conversa antes e sem poder pedir a busca que
sustentaria o argumento.

## Onde tudo mora

| Camada | Arquivo | O quê |
|---|---|---|
| Conversa | `app/agente/chat_peticao.py` | O modelo com as ferramentas do dossiê, o fluxo em streaming, as ações e os avisos |
| Ações | `app/agente/peticao_fluxo.py` → `app/peticao_local.py` | Gerar, revisar, aceitar, redigir peça anexa — as mesmas dos botões |
| Web | `app/pesquisa_web.py` | A busca na internet, com as fontes (OpenRouter + plugin `web`) |
| Rotas | `app/agente/rotas.py` (`/api/agente/casos/{caso}/chat-peticao*`) | HTTP, com a resposta em SSE |
| Persistência | `app/armazenamento.py` + `app/banco.py` | `dbo.acervo_conversas` / `dbo.acervo_conversa_mensagens`, coluna `escopo = 'PETICAO'` |
| Rede (tela) | `frontend/src/lib/chatPeticao.ts` | Tradução do formato e leitura do fluxo |
| Tela | `frontend/src/components/admin/ChatPeticao.tsx` | A conversa |
| Tela | `frontend/src/components/admin/FluxoPeticao.tsx` | O documento e a grade de duas colunas |
| Comum | `frontend/src/components/ui/Markdown.tsx` | O markdown que a IA escreve, usado pelo chat e pela pesquisa avulsa |

## A regra que atravessa tudo: ler é livre, escrever não é

O modelo tem dez ferramentas. Seis **leem** (a minuta, a análise, os documentos com OCR, a
entrevista, o histórico de versões e a web) e executam na hora. Quatro **propõem** —
`propor_revisao_da_peticao`, `propor_geracao_da_peticao`, `propor_analise_de_documentos`,
`propor_peca_anexa` — e **não executam nada**: viram um cartão na conversa com o que vai
acontecer escrito e dois botões.

O teste `tests/test_chat_peticao.py` trava essa fronteira: toda ferramenta que altera a
peça se chama `propor_*`, e nenhuma leitura se disfarça de proposta.

Quando a proposta é confirmada, quem executa é `executar_acao`, que chama exatamente as
mesmas funções dos botões. Uma revisão pedida no chat vira **comparação pendente** (antes ×
depois, sobre o documento) — nunca versão nova direto. A versão só nasce quando a
comparação é aceita.

### Rastreabilidade

A revisão nascida no chat vai para o histórico com `origem: "chat"`, além do prompt, do
autor e da data que já iam. É o que permite auditar, meses depois, por que a versão 4 diz o
que diz — documento jurídico não pode ter edição de origem desconhecida.

Pedido feito no chat entra com `generaliza=False`: vale para **este** caso e não instrui as
próximas petições da categoria. Ensinar a IA continua sendo escolha explícita, com a caixa
marcada, no campo de revisão do painel — a conversa é rápida demais para que alguém leia
essa consequência antes de apertar "confirmar".

## O que veio da web tem cara de web

`pesquisar_na_web` é a única ferramenta cujo resultado não sai dos autos. Ela volta com as
fontes, o prompt exige que o modelo cite o link em linha e diga que é da internet, e as
fontes são gravadas no `payload` da mensagem — então sobrevivem ao reload e continuam
visíveis, em bloco próprio, separado do que veio do caso.

## A IA fala sem ser perguntada

Terminou uma ação, ela conta. Vale para as ações confirmadas no chat e para os **botões**:
gerar a petição, salvar, aceitar/descartar a comparação, redigir outra peça e analisar os
documentos disparam `avisarChatDaPeticao(...)`, um evento de janela que o chat escuta e
transforma em mensagem — com a versão nova, o que mudou e o que **continua sem comprovação
documental**.

É mensagem na transcrição, não aviso que some. Depois de uma geração é justamente quando o
advogado mais precisa saber o que ficou frágil.

O evento de janela existe porque quem dispara a análise dos documentos é um painel em outro
galho da árvore (o dossiê), e levar um callback até lá obrigaria a subir estado por três
componentes que nada têm a ver com a conversa. Mesmo padrão da sessão expirada
(`lib/api.ts`).

## Erro é conteúdo, não código HTTP

Falha do modelo, da busca na web ou de uma ação **não** derruba a chamada: vira mensagem de
erro gravada na conversa, com a pergunta original e um botão de *tentar de novo*. Um 502
que apaga da tela a pergunta que o advogado acabou de fazer é pior do que a falha.

## Streaming

A resposta chega em SSE (`text/event-stream`), com quatro eventos: `etapa` (o que está
sendo consultado, em português), `delta` (o texto chegando), `recomeco` (o modelo desistiu
do que começou a escrever para consultar antes — a tela zera o parcial) e `fim` (a mensagem
gravada, com fontes e propostas).

`EventSource` não serve: só faz GET e não leva corpo. É `fetch` com leitura do corpo em
fluxo. O cabeçalho `X-Accel-Buffering: no` é o que impede o nginx da frente de juntar os
pedaços e entregar tudo no fim — sem ele, o fluxo existiria no servidor e não na tela.

## Persistência

Uma conversa por caso e por pessoa, achada pela tríade (dono, caso, escopo). A coluna
`escopo` separa esta transcrição da do agente geral: sem ela, cada caso apareceria no
histórico da Carteira como pergunta avulsa, e apagar essa "conversa" levaria junto o chat
do Dossiê daquele caso.

O reload da página reabre a transcrição inteira. **Limitação conhecida:** a navegação do
sistema não guarda estado na URL, então o F5 volta para a Carteira — o histórico está
salvo, mas é preciso reabrir o caso para vê-lo. O que se perde é a resposta que estava
sendo escrita naquele instante: ela não é gravada antes de terminar.

## Tela estreita

Abaixo de `lg` não há largura para duas colunas. A conversa vira gaveta, chamada por um
botão flutuante, e o documento fica com a página inteira. O componente é **um só**, sempre
montado: dois montariam duas escutas do mesmo evento e a mensagem da IA entraria duplicada
na transcrição.

## O que continua fora do chat

Nada foi removido. O campo de *revisão por prompt* (com a opção de ensinar a IA) e a
*pesquisa na web* avulsa ficaram recolhidos num `<details>` abaixo do documento —
"Ferramentas fora do chat". Os botões de gerar, analisar, redigir outra peça, salvar e
baixar `.docx`/PDF continuam onde estavam, e o histórico de edição também.
