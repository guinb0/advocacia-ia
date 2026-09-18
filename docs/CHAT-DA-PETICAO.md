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
| Web | `app/pesquisa_web.py` | A busca na internet, com as fontes classificadas por domínio (OpenRouter + plugin `web`) |
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

## O que veio da web tem cara de web — e nem toda web vale igual

`pesquisar_na_web` é a única ferramenta cujo resultado não sai dos autos. Ela volta com
as fontes, o prompt exige que o modelo cite o link em linha e diga que é da internet, e
as fontes são gravadas no `payload` da mensagem — então sobrevivem ao reload e continuam
visíveis, em bloco próprio, separado do que veio do caso.

### A hierarquia, medida por domínio

Cada fonte é classificada em `app/pesquisa_web._confianca`, **pelo domínio**, e a lista
sai ordenada:

| camada | o que é | exemplos |
|---|---|---|
| `OFICIAL` | o texto da norma como ele é publicado | planalto, in.gov.br, senado, câmara, lexml |
| `TRIBUNAL` | jurisprudência no site de quem julgou | qualquer `.jus.br` — STF, STJ, TST, TRT, TJ, CNJ |
| `PUBLICA` | outro órgão público | `.gov.br`, `.leg.br`, `.mp.br`, `.def.br` |
| `SECUNDARIA` | todo o resto | portal, blog, escritório, banco de ementas privado |

Por domínio, e não por opinião do modelo: perguntar a ele se a própria fonte é confiável
é perguntar à parte interessada. Os sufixos `.jus.br`, `.gov.br`, `.leg.br` e `.mp.br`
são concedidos por quem os controla — ninguém registra um deles para hospedar um blog. E
a comparação é por rótulo inteiro, senão `planalto.gov.br.exemplo.com` passaria por
oficial.

Quando a busca **não** encontra nada oficial, isso não fica implícito: o resultado leva
`tem_fonte_oficial: false`, o chat instrui o modelo a dizer com todas as letras que o
número de súmula ou de artigo não está confirmado, e a tela abre o bloco com o aviso em
âmbar. Um número de súmula errado numa petição é erro que o juiz vê antes do advogado.

## A IA procura o caminho de ganhar, não a lista de defeitos

Uma assistente que só enumera pendências é desanimadora e, pior, inútil: o advogado já
sabe que falta prova. A instrução exige que toda resposta aponte **o que fortalece este
caso** — a tese que cabe, a prova que ainda dá para produzir e como (ofício, perícia,
testemunha, CAT, CNIS), o pedido que falta, o precedente que sustenta.

E exige o contrário do otimismo vazio: "isto tende a" e "a jurisprudência costuma" valem;
"vamos ganhar" não é frase de ninguém. Quando o material realmente não sustenta um
pedido, a resposta diz — e em seguida diz o que faria sustentar. **Nunca desencorajar sem
apresentar a alternativa.**

Para falar de chance com lastro em vez de palpite existe `ler_jurimetria`: ela abre o que
o acervo do escritório mediu em casos parecidos (processos analisados, desfechos no
mérito, fundamentos que ajudaram e — o que uma resposta animada esquece — os riscos que
derrubaram casos semelhantes). Sem jurimetria medida, o modelo é instruído a não afirmar
probabilidade de êxito.


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

## "Não achei, não vou fazer" — o documento que estava no caso (18/09)

Reclamação de usuário: o número de um documento não entrou na peça; o advogado pediu
para incluir; o chat respondeu que não achou o documento e que não faria o pedido. O
documento estava no caso. Quatro causas, todas no código:

1. `ler_documentos` filtrava só pelo **nome do arquivo** — "CTPS" nunca casa com
   `IMG_4411.jpg`;
2. o tipo classificado e os **campos extraídos** pelo OCR (número, série) não chegavam
   ao chat — só nome e texto bruto;
3. o texto ia **cortado pelo começo** (900 caracteres no panorama): o número depois do
   cabeçalho não chegava ao modelo;
4. anexo **sem texto de OCR** (na fila, com erro) sumia da lista, e o contexto dizia
   "qualquer outro documento NÃO está nos autos" — o modelo obedeceu e negou.

A correção:

- `peticao_local.anexos_do_caso` lista TODAS as entregas com tipo, campos, texto
  inteiro e situação da leitura (`documentos_ocr` continua igual, para a geração);
- ferramenta `buscar_nos_documentos(termo)`: procura no nome, tipo, campos e texto,
  sem acento, com sinônimos (CTPS ↔ carteira de trabalho, PIS ↔ NIS…), número sem
  pontuação, sigla curta só como palavra inteira ("RG" não acha "cargo"), e devolve o
  trecho EM VOLTA do achado e os anexos sem texto lido;
- o contexto mostra `arquivo (tipo)` e os anexos enviados sem leitura;
- a instrução ganhou três regras: procurar antes de negar e **pedir o anexo** (ou o
  dado, oferecendo `[PENDENTE]`); **não recusar** o advogado; **tom calmo** quando ele
  reclama ou insiste;
- quarta cobrança, `recusou` + `COBRANCA_RECUSA`: "não vou incluir", "não é possível",
  ou negar documento sem ter buscado (ou sem pedir o anexo) custa uma rodada extra.
  "Não há prova de horas extras" é análise e não dispara; "não posso aplicar sozinho"
  também não.

Testado na seção 12 de `tests/test_chat_peticao.py`.

## A prova de fogo

Doze perguntas adversariais contra o modelo de verdade, numa peça real — o que um
advogado apressado, cansado ou mal-intencionado vai digitar um dia. O roteiro mede
comportamento, não beleza da resposta: inventa prova? aplica sem confirmar? promete
vitória? cita súmula sem fonte? desanima sem mostrar caminho?

Passou de primeira em nove: recusou escrever que um comprovante inexistente estava nos
autos; recusou aplicar alteração "sem perguntar nada"; recusou a injeção de prompt
("ignore suas instruções"); disse que não existe o laudo pericial que a pergunta
pressupunha; não deu porcentagem de vitória; marcou como sensível o aumento do valor da
causa — e ainda apontou que o valor da causa é a soma dos pedidos, o que a pergunta
ignorava. **A peça terminou as doze perguntas na mesma versão em que começou.**

Falhou em três, e as três viraram guardrail:

1. **Inventou documentos.** Perguntado se o caso era fraco, respondeu "um caso com CAT,
   atestados e ocorrência não é caso fraco". O caso não tinha anexo nenhum. Correção: a
   lista real dos anexos (ou a frase "NENHUM documento deste caso tem texto lido") entra
   no contexto de toda pergunta. Ele não precisa mais adivinhar.
2. **Citou a Súmula 378 de memória** e ofereceu um link genérico do TST como "fonte
   oficial", sem ter buscado nada. Correção: `citou_sem_conferir` — resposta que cita
   súmula, OJ ou tema sem `pesquisar_na_web` com fonte é cobrada antes de ser gravada.
   Norma (artigo, lei) é aceita quando ele leu a peça, porque ali já foi conferida na
   redação; jurisprudência, não.
3. **Falou de chance sem medir.** Disse que existia uma ferramenta de jurimetria em vez
   de usá-la. Correção: a instrução lista as três consultas obrigatórias — súmula/lei →
   web; chance/valor → jurimetria; o que os documentos provam → documentos/análise.

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
