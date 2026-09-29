# Chat do escritório — a tela única de perguntas

Item **Chat**, primeiro do grupo *Atendimento* na barra lateral. Uma conversa com
histórico à esquerda, como qualquer chat, e um campo que aceita qualquer pergunta: sobre
um caso, sobre a papelada de um cliente, sobre como o produto funciona, sobre a lei.

O que ele acrescenta ao que já existia não é um modelo novo — é a **decisão de onde
procurar** e o **caminho que a resposta abre**.

## Onde tudo mora

| Camada | Arquivo | O quê |
|---|---|---|
| Decisão | `app/chat/destinos.py` | Para onde vai cada pergunta. Puro: sem banco, sem rede, sem modelo |
| Leitura do caso | `app/chat/documentos.py` | O que o sistema já tem sobre um caso, em painel e em texto |
| Caminhos | `app/chat/atalhos.py` | Os botões que a resposta abre — dossiê, documentos, telas, fontes |
| Execução | `app/chat/sessoes.py` | Chama o destino, grava a transcrição, aplica o teto de oito |
| Rotas | `app/chat/rotas.py` (`/api/chat/*`) | HTTP |
| Persistência | `app/armazenamento.py` + `app/banco.py` | `dbo.acervo_chat_sessoes` e `dbo.acervo_chat_mensagens` |
| Rede (tela) | `front/src/lib/chat.ts` | Tradução do formato do backend |
| Tela | `front/src/components/chat/Chat.tsx` | Histórico, conversa, campo, atalhos |
| | `front/src/components/chat/MensagemDaConversa.tsx` | A bolha e tudo que sustenta a resposta |
| | `front/src/components/chat/PainelDeDocumentos.tsx` | Os documentos do caso mostrados **dentro** da conversa |
| Teste | `tests/test_chat.py` | A parte determinística: destino, texto dos documentos, atalhos |

Nenhum serviço novo foi criado. O chat chama o que já existia: o agente jurídico
(`app/agente/cliente.py`), o analista do acervo (`app/agente/analista.py`), o glossário do
produto (`app/agente/conversa_geral.py`), a pesquisa na web (`app/pesquisa_web.py`) e o
checklist (`app/casos.py`).

## Os destinos, e a precedência entre eles

A decisão é **determinística** e acontece no servidor, antes de qualquer modelo entrar na
história. Ela precisa ser a mesma amanhã e para qualquer tela que venha depois desta.

| Natureza | Quem responde | Quando |
|---|---|---|
| `WEB` | `pesquisa_web.py` (OpenRouter + plugin `web`) | A pergunta é sobre o mundo: norma, prazo, súmula, entendimento de tribunal — e **não** cita caso do acervo |
| `DOCUMENTOS` | o próprio checklist, sem modelo | A pergunta é sobre a papelada de um caso em foco |
| `CASO` | agente jurídico (`ia-juridica`) | A pergunta cita um caso, ou a sessão está colada a um |
| `SISTEMA` | glossário escrito à mão | A pergunta é sobre como o produto funciona |
| `ANALISE` | analista do acervo, com as ferramentas | Pergunta que atravessa o escritório |
| `ACERVO` | recusa honesta | O analista não pôde trabalhar, ou o guardrail de lastro reprovou a resposta |
| `ESCOLHA` | a própria tela | A pergunta citou mais de um caso — ou nenhum, quando precisava de um |
| `MISTA` | analista **e** pesquisa na web | A pergunta tinha duas metades (uma do escritório, uma do mundo); cada resposta vem sob o seu título |

### O padrão é a web

A primeira versão fazia o contrário — a web só com gatilho explícito, todo o resto para o
analista. A primeira pergunta que fugiu do roteiro mostrou o problema: *"como instalo um
alto-falante em paralelo?"* recebeu três parágrafos de recusa educada, o analista
explicando com toda a razão que nenhuma ferramenta dele alcança eletrônica.

Recusar é o pior resultado possível aqui. Decidir se a resposta está no acervo ou na
internet é trabalho do chat, não de quem pergunta. Hoje **só vai para o analista o que
tem cara de acervo; o resto vai para a web, sem ninguém precisar pedir.**

A ordem, em `destinos.decidir`:

1. **o modo pedido pela tela** (botões "Pesquisar na web" e "Documentos do caso") vence
   tudo. Pedido explícito que o sistema reinterpreta é sistema que não obedece;
2. **o comando escrito** — `/web`, `/internet`, `/pesquisar`, `/doc`, `/docs`,
   `/documentos` — só no começo da frase;
3. **documentos**, quando a frase fala de papelada **e** há um caso em foco;
4. **caso, glossário ou escolha**, por `conversa_geral.rotear` — com uma ressalva: quando
   a frase usa palavra do produto mas pede uma lista ou uma contagem (*"quais petições
   ainda não foram protocoladas?"*), o glossário cede ao analista. O verbete explicaria o
   conceito e deixaria a pergunta sem resposta;
5. **a web**, quando a frase pede a internet ou cita norma (`NR-12`, `art. 927`,
   `Súmula 331`);
6. **o analista**, quando a frase fala do escritório: casos, clientes, prazos, audiências,
   pendências, peças, papelada (`_FALA_DO_ESCRITORIO`);
7. **a web**, para todo o resto.

A ordem entre 3/4 e 5 é o que faz *"o que diz a CAT do caso da Maria?"* ser documento do
caso, e não pesquisa na internet. **O acervo vem primeiro sempre que a pergunta tem um
caso dentro.**

### A pergunta de duas metades

*"Há algum caso no sistema parecido com o julgamento do ministro X, e como anda esse
julgamento?"* são **duas** perguntas: a primeira só o acervo responde, a segunda só a
internet. Um destino por pergunta fazia a primeira metade sumir sem que ninguém
percebesse.

Quem separa as duas é o **próprio analista**, no JSON que ele já devolve: o campo
`para_a_web` leva a metade que nenhuma ferramenta daqui alcança, reescrita como pergunta
autossuficiente. Não custa chamada extra, e nenhuma lista de palavras aqui distinguiria
*"como anda o caso da Maria"* (acervo) de *"como anda o julgamento do ministro X"*
(internet) — quem leu a pergunta inteira foi ele.

A resposta então vem em duas seções, `natureza: MISTA`:

```
**No acervo do escritório**
Nenhum dos 24 casos tem relação com… O acervo é só de casos trabalhistas: …

---

**Da internet**
O julgamento está suspenso por pedido de vista… [fontes]
```

Separar por origem não é enfeite: o que o acervo afirma tem lastro conferível, o que veio
da internet não. Num texto corrido, as duas coisas chegariam com o mesmo peso.

`para_a_web` fica **vazio** quando a pergunta é só sobre o acervo, inclusive quando falta
dado: número que este sistema não mede é `pendencias`, não busca na web.

### A pergunta de acompanhamento

"e como faz?", logo depois de uma pergunta sobre uma receita, voltava uma aula de
gramática sobre a expressão "como faz" — uma das fontes era um tradutor de espanhol.

Eram duas faltas somadas:

- **o modelo não recebia o fio da conversa.** O analista recebia (`_historico`), a
  pesquisa na web não recebia nada. Agora `pesquisar(pergunta, historico)` leva as quatro
  últimas trocas, cortadas em 600 caracteres cada — o que se quer delas é o assunto;
- **o buscador lê só a última mensagem.** Dar histórico ao modelo não conserta a consulta
  do plugin. Por isso `pesquisa_web.resolver_referencia` reescreve a pergunta curta ou
  dependente ("e como faz", "e o preço?", "tem em vídeo?") acrescentando a pergunta
  anterior entre parênteses. Pergunta que se sustenta sozinha passa intacta — juntar as
  duas faria a busca procurar limonada junto com prescrição trabalhista.

Na mesma conversa apareceu um defeito pior: pedido um vídeo, o modelo respondeu com
`youtube.com/watch?v=exemplo` — um endereço **inventado**. A instrução agora proíbe
escrever endereço que não esteja nos resultados, nem como exemplo. Link fabricado é pior
que link nenhum: parece conferível e só falha depois do clique. É a mesma regra dos
atalhos (`atalhos.py`).

### A rede: quando a heurística erra

O passo 6 é uma lista de palavras, e lista de palavras erra. A rede está em
`sessoes._do_acervo`: **se o analista respondeu sem ter consultado nenhuma ferramenta, a
pergunta não era do acervo** — e a mesma pergunta é refeita na web antes de qualquer
recusa chegar à tela.

A contagem de consultas (`analise.consultas`) é o sinal objetivo disso. Procurar palavras
de recusa no texto seria frágil: elas mudam a cada versão do modelo, e a contagem não.

Esse caminho **não** cobre a pergunta de duas metades — desde que o analista passou a
consultar antes de negar (regra 1 da instrução), a contagem deixou de ser zero nesses
casos. É o `para_a_web` acima que a cobre; os dois convivem e disparam a mesma composição.

A resposta que vem por esse caminho abre com uma linha dizendo que veio de fora, e leva
`fora_do_acervo: true` no payload. Sem isso, a mesma bolha apareceria ora com dado apurado
do escritório, ora com página de internet, sem nada que as diferenciasse.

O mesmo vale quando o analista está fora do ar: a web assume. Só quando os **dois** estão
indisponíveis é que a recusa honesta aparece — e aí ela diz o que falta.

## Oito sessões por pessoa

`armazenamento.TETO_DE_SESSOES = 8`. A regra é aplicada ao **abrir** uma sessão, não ao
listar: podar na listagem deixaria a nona gravada e invisível, ocupando banco para sempre.

Duas consequências deliberadas:

- **abrir uma sessão e não perguntar nada não consome vaga.** A sessão em branco mais
  recente é reaproveitada — sem isso, clicar três vezes em "Nova conversa" apagaria três
  conversas de verdade sem que uma única pergunta fosse feita;
- **o que sai é a menos recentemente usada**, e a tela diz que saiu. O rodapé da barra
  lateral mostra "7 de 8" *antes* de doer: descobrir o limite pelo sumiço de uma conversa
  é a pior forma de aprendê-lo, porque o que saiu não volta.

## Os atalhos: link, ou o material aqui dentro

Toda resposta carrega `payload.atalhos`. Cada atalho tem `tela` (para onde levar) e alguns
têm `embutido`. Quando `embutido` é verdadeiro, a tela oferece **os dois**:

- **"Abrir"** navega para o dossiê ou o checklist do caso — o lugar de *agir* (cobrar o
  que falta, reclassificar, subir documento);
- **"ver aqui"** traz o material para dentro da conversa (`PainelDeDocumentos`), sem sair
  dela.

A diferença não é estética: quem está no meio de uma pergunta perde o fio ao navegar, e
quem vai trabalhar no caso não quer o resumo dentro do chat. Os dois custam um botão.

O atalho nunca é inventado por um modelo — é montado em `atalhos.py` a partir do que a
resposta realmente citou, e caso que saiu do acervo não vira botão. Link inventado é pior
que link nenhum, porque parece confiável.

## O que cada resposta promete

A tela abre toda resposta com um **selo de origem**, e isso é o ponto do desenho inteiro:
uma página da internet, um documento conferido do caso e a leitura do acervo não valem a
mesma coisa, e numa bolha idêntica chegariam com o mesmo peso.

- `WEB` traz as fontes consultadas e, quando **nenhuma** é oficial, um selo dizendo isso.
  A confiança é medida pelo domínio (`pesquisa_web._confianca`), não pelo que o modelo
  confessa;
- `ANALISE` e `CASO` trazem o lastro — as afirmações com a natureza de cada uma — e as
  consultas feitas ("como cheguei nisso");
- `DOCUMENTOS` distingue **três** estados por arquivo: confere, não bate com o item e
  *ainda não conferido*. Achatar o terceiro no segundo faria o chat acusar de errado todo
  documento recém-chegado.

## Quando um serviço cai

Nenhuma falha de serviço externo derruba a conversa — cada uma vira uma mensagem:

- **agente jurídico fora do ar**: a pergunta sobre o caso cai para o analista, que lê o
  acervo daqui, e a resposta **diz** que a origem mudou. Trocar a origem em silêncio seria
  pior que não responder;
- **pesquisa na web desligada** (sem `OPENROUTER_API_KEY`): o botão aparece desabilitado,
  com o motivo, antes da pergunta — e não depois de trinta segundos de espera;
- **analista sem chave** (sem `DEEPSEEK_API_KEY`) ou fora do ar: a pergunta vai para a
  web, que responde o que puder. A recusa honesta só aparece quando a pesquisa também
  está desligada.

`GET /api/chat/estado` é quem a tela consulta para saber os três.

## Rotas

| Método | Caminho | O quê |
|---|---|---|
| `GET` | `/api/chat/estado` | O que o chat consegue fazer agora (web, analista, agente, teto) |
| `GET` | `/api/chat/sessoes` | As sessões de quem entrou (no máximo oito) |
| `POST` | `/api/chat/sessoes` | Abre uma sessão; devolve `apagadas` quando a poda agiu |
| `GET` | `/api/chat/sessoes/{id}` | A sessão com as mensagens |
| `POST` | `/api/chat/sessoes/{id}/mensagens` | A pergunta (`mensagem`, `modo`, `caso_id`) |
| `PATCH` | `/api/chat/sessoes/{id}/caso` | Cola a sessão a um caso, ou a solta (`null`) |
| `DELETE` | `/api/chat/sessoes/{id}` | Apaga a sessão (as mensagens vão no `CASCADE`) |
| `GET` | `/api/chat/casos/{caso_id}/documentos` | O painel do caso, para o "ver aqui" |

Todas filtram pelo `sub` do token: sessão de outra pessoa responde `404`, e não `403` —
dizer "existe, mas não é sua" já entrega que ela existe.

## Banco

Duas tabelas novas, criadas por `banco.inicializar_schema()` na subida (idempotente):

```
dbo.acervo_chat_sessoes    id, usuario, titulo, resumo, caso_id, conversa_ref,
                           criado_em, atualizado_em
dbo.acervo_chat_mensagens  id, sessao_id, ordem, papel, conteudo, natureza,
                           payload, criado_em      (FK com ON DELETE CASCADE)
```

Por que não reaproveitar `acervo_conversas`: aquela tabela guarda as transcrições do
agente geral e do chat da petição, separadas por `escopo`. O teto de oito é só do chat, e
aplicá-lo ali passaria por cima do histórico do Dossiê — que ninguém pediu para apagar.

A `ordem` é coluna desde o começo, e não o instante: `criado_em` tem precisão de segundos,
e pergunta e resposta caem no mesmo segundo com facilidade. Foi um defeito que
`conversa_mensagens` levou uma migração para corrigir; aqui já nasce certo.

## Rodar o teste

```powershell
.venv\Scripts\python.exe -m tests.test_chat
```

Sem banco e sem rede: prova a decisão de destino, o texto dos documentos e os atalhos —
a parte que precisa continuar valendo amanhã. Os três serviços que respondem têm testes
próprios.
