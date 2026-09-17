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
| Comparação | `frontend/src/lib/diffPeticao.ts` | O que sai (vermelho) e o que entra (verde), por sequência — testado com revisões reais em `diffPeticao.teste.mjs` |

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

## Três erros que só apareceram com pedido de verdade

Dez pedidos de alteração seguidos, numa peça trabalhista real, revisão após revisão. É a
medição que vale para esta tela — quatro dos dez já falhavam, e nenhum deles falhava nos
testes sintéticos.

**1. Dizer que propôs não é propor.** A partir do terceiro pedido, o modelo passou a
imitar as próprias respostas anteriores do histórico ("Registrei o pedido de revisão…")
**sem chamar ferramenta nenhuma**. A mensagem chegava perfeita e o cartão de confirmação
não existia: o advogado esperava um botão que nunca apareceria. O pior erro possível
aqui, porque parece sucesso.

Corrigido em duas camadas: a instrução diz que o botão nasce da CHAMADA, nunca do texto;
e `conversar` cobra a ferramenta quando o texto promete e a chamada não veio
(`prometeu_acao` + `COBRANCA`), uma vez por resposta.

**2. `tool_calls: []` derruba a rodada seguinte.** A mensagem do assistente sem chamadas
ia com a chave vazia. Enquanto ela era sempre a ÚLTIMA da conversa, ninguém notou — a
cobrança do item 1 criou o primeiro caso em que ela volta no histórico, e a API respondeu
**400** em três dos seis pedidos seguintes. Agora a chave só existe quando há chamada, e
o texto do 400 sobe junto do erro em vez de virar "tente de novo".

**3. O verde marcava a palavra errada.** A coluna "Nova versão" reexecutava o diff
invertido e devolvia índices calculados sobre o texto ANTIGO, que o componente aplicava
às palavras do texto NOVO. Em substituição do mesmo tamanho (R$ 40.000,00 → R$ 60.000,00)
as posições coincidiam e ninguém veria; numa inserção, não: o pedido de justiça gratuita
acrescentado marcava **uma** palavra em verde em vez das 144 que entraram. O cálculo é o
mesmo dos dois lados, com os argumentos trocados — só a cor muda.

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

## O que a tela oferece antes de alguém digitar

Quem abre a coluna pela primeira vez não sabe o que pode pedir, e um campo de texto vazio
não ensina. Por isso a conversa vazia mostra **três cartões**, que são pedidos de verdade:

- *Entender a peça* — envia a pergunta pronta ("o que ainda não tem comprovação
  documental, e por quê?");
- *Buscar na web* e *Alterar a petição* — **escrevem o começo da frase no campo** e
  devolvem o cursor. "Busque na web" sem o assunto não é pedido, e mandá-lo pronto
  gastaria uma volta no modelo para receber de volta "sobre o quê?".

Depois que a conversa começa, os três viram atalhos em pílula acima do campo. Há ainda o
link do confronto entrevista × documentos, que vira pergunta com um clique.

Duas coisas de leitura longa: a coluna tem um **botão de alargar** no cabeçalho (quem está
pedindo alterações lê mais a resposta do que a peça, e coluna estreita transforma cada
parágrafo em vinte linhas), e a conversa **não é empurrada para o fim** enquanto alguém
está lendo mais acima — nesse caso aparece um "↓ Ver o que chegou".

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
