# Agente geral — o chat fora do caso

Tela nova, alcançada pelo item **Agente** da barra lateral, no grupo *Atendimento* — ao
lado da Carteira, porque a pergunta que ela responde é a de **antes** de saber qual caso
abrir. Um chat com histórico de conversas.

Este documento existe principalmente por causa da última seção: uma parte do que a tela
aceita perguntar **não tem quem responda ainda**, e o que faltaria está escrito lá com
rota, entrada e saída.

## Onde tudo mora

| Camada | Arquivo | O quê |
|---|---|---|
| Decisão | `app/agente/conversa_geral.py` | Para onde vai cada pergunta, e o glossário do sistema. Puro: sem banco, sem rede, sem modelo |
| Análise | `app/agente/analista.py` | O modelo que investiga com ferramentas e responde — com o guardrail de lastro |
| Consultas | `app/agente/ferramentas.py` | O que o analista pode medir, e o que cada medição comprova |
| Execução | `app/agente/conversas.py` | Executa a decisão, fala com o agente e guarda a transcrição |
| Rotas | `app/agente/rotas.py` (`/api/agente/conversas*`) | HTTP |
| Persistência | `app/armazenamento.py` + `app/banco.py` | `dbo.acervo_conversas` e `dbo.acervo_conversa_mensagens` |
| Rede (tela) | `frontend/src/lib/conversas.ts` | Tradução do formato do backend |
| Tela | `frontend/src/components/AgenteGeral.tsx` | Histórico, conversa, campo |
| Comum às duas telas | `frontend/src/components/RespostaDoAgente.tsx` | Lastro da resposta e cartão de proposta |

O painel do agente dentro do caso (`AjudanteDoCaso.tsx`) mora no **dossiê**
(`components/admin/Dossie.tsx`), como coluna à direita a partir de `lg`: recolhido vira um
trilho de 52 px, e o dossiê volta à largura inteira. O caso não sai da tela quando se fala
com o agente — antes isso era uma aba que o substituía, e a citação da resposta apontava
para algo que o advogado não estava mais vendo. É também por isso que cada fato do dossiê
leva `id="fato-<id>"`: é a âncora que o botão "ver no dossiê" procura.

O painel não mudou de propósito. O que ele tinha de comum com esta tela — o mapa de naturezas, o bloco "em que a
resposta se apoia", o cartão de proposta — saiu dele para `RespostaDoAgente.tsx`. Isso não
é economia de linhas: se as duas telas divergirem sobre como um fato **alegado** aparece, o
guardrail do backend deixa de valer naquela que ficou para trás, e o advogado passa a ler
relato e prova com o mesmo peso.

## As quatro naturezas de resposta

O roteamento é **determinístico** e acontece no servidor. Nenhum modelo participa da
decisão — ela precisa ser a mesma amanhã e para qualquer tela que venha depois desta.

| Natureza | Quando | O que a tela mostra |
|---|---|---|
| `CASO` | A pergunta cita um caso, ou a conversa já está sobre um | A resposta do agente jurídico, com o lastro (afirmações com a natureza de cada uma) e as lacunas |
| `SISTEMA` | A pergunta é sobre como o produto funciona | O verbete do glossário, com o selo **Sobre o sistema** e a nota de que é texto do próprio sistema, não consulta ao acervo |
| `ESCOLHA` | A pergunta cita mais de um caso | A lista dos casos citados, cada um distinguível, como botões |
| `ACERVO` | A pergunta atravessa vários casos | Que ainda não sabe responder, e o que falta para saber |

Precedências, e o motivo de cada uma:

1. **o caso citado na pergunta vence o caso da conversa** — "e o caso do João Souza?" muda
   de assunto no meio da conversa, em vez de responder sobre a cliente anterior;
2. **o caso da conversa vence o glossário** — numa conversa já colada a um caso, "quais
   fatos alegados existem?" tem de listar os fatos daquele caso, não explicar o conceito.
   Quem quer a explicação genérica abre outra conversa, ou solta o caso na barra do alto;
3. **a citação mais específica vence** — o acervo tem "Guilherme Nunes" ao lado de
   "Guilherme"; sem isso, perguntar pelo nome completo traria os homônimos de primeiro
   nome junto.

### Como um caso é reconhecido

Pelo identificador, pelo nome completo do cliente, ou por dois pedaços seguidos dele
("Maria Silva" para "Maria Silva Santos"). **Um primeiro nome sozinho não basta** — com
três Marias no acervo, escolher uma seria sorteio, e a resposta viria sobre o caso errado
com toda a confiança do mundo. A exceção é o cliente cadastrado com um nome só, que
acontece bastante: aí o token é tudo o que existe daquele nome.

Quando mais de um caso é citado, a resposta pergunta qual — e cada candidato leva
categoria e data de abertura. Dois processos do mesmo cliente é situação corriqueira; se
categoria e data também coincidirem, entra o identificador curto. Botão que não distingue é
clique no escuro.

### O glossário

`GLOSSARIO`, em `conversa_geral.py`: doze verbetes escritos à mão, com os termos que fazem
a pergunta cair em cada um. Os termos são deliberadamente específicos — **é melhor não
reconhecer a pergunta e dizer isso do que reconhecer a errada** e explicar outra coisa com
ar de certeza. O casamento respeita limite de palavra: sem isso, "comprovante de
residência" dispararia o verbete de fato *provado*.

Ao acrescentar um verbete, confira que o texto é verdade sobre o sistema como ele está
hoje. Este é o único lugar do produto onde uma resposta não vem de dado apurado — o selo na
tela existe por isso, e a exatidão do texto é a única coisa que sustenta o selo.

## O analista

`ACERVO` deixou de ser recusa. A pergunta que não é de um caso, não é do glossário e não é
ambígua vai para o **analista** (`analista.py`): um modelo com um catálogo de consultas
(`ferramentas.py`) e liberdade para escolher quais usar, em que ordem e quantas vezes.

Ele decide o caminho. O que não se negocia é a origem do número.

### As sete consultas

| Ferramenta | O que mede | O que comprova (`refs`) |
|---|---|---|
| `panorama_do_escritorio` | Funil, parados, ciclo, categorias, movimento — os números da tela Panorama | `panorama`, `caso:<id>` |
| `listar_casos` | Casos por nome, categoria, estágio ou dias parados | `caso:<id>` |
| `dossie_do_caso` | Cadastro, checklist, contrato, entrevistas, fatos, pendências, petições | `caso:<id>`, `fato:<id>` |
| `documentos_do_caso` | O que o cliente entregou e o que o OCR leu | `documento:<id>` |
| `entrevistas_do_caso` | Resumo do atendimento e, sob demanda, a transcrição | `entrevista:<id>` |
| `jurimetria_do_acervo` | Como o foro decide a matéria | `jurimetria` |
| `glossario_do_sistema` | O que um termo do produto significa | `sistema:<verbete>` |

**Ler é ler.** `dossie_do_caso` chama `dossie.montar(recuperar=False)` de propósito: abrir
o dossiê na TELA recria o caso no agente jurídico quando ele sumiu de lá — é o que o
advogado quer ao clicar. Aqui não. Uma pergunta pode abrir dez casos, e uma consulta que
escreve no outro sistema transformaria "quantos casos estão parados?" numa sincronização
em massa que ninguém pediu. Isso foi descoberto na primeira execução real, olhando o log.

### Duas fases

1. **investigação** — o modelo chama ferramenta, lê o resultado, chama outra (até seis
   rodadas). Saída livre;
2. **redação** — uma segunda chamada escreve no formato fechado: afirmação, natureza e
   referências.

Misturar as duas numa só produz o pior dos dois mundos: ou o JSON aparece no meio da
investigação (e ele para de consultar cedo), ou a prosa aparece no fim (e o guardrail não
tem o que conferir).

### O guardrail

`PROVEN_FACT` e `STATISTICAL_PATTERN` **exigem** `refs` que alguma ferramenta tenha
devolvido — "63 casos estão parados" soa idêntico esteja certo ou inventado. Sem lastro, a
afirmação é descartada e o advogado é avisado de que foi. Quando **nada** sobra, a
resposta inteira é retida: entregar o texto com o número que o guardrail acabou de
reprovar anularia o guardrail.

`INFERENCE`, `HYPOTHESIS` e `RECOMMENDATION` passam sem referência, de propósito. São
leitura, não medição, e a tela já as mostra com selo próprio. Exigir lastro delas é o erro
que este repositório cometeu três vezes: reprovar a resposta certa por excesso de zelo, e
ensinar o advogado a ignorar o aviso.

Testes em `tests/test_analista.py`, com o modelo substituído por um dublê — com o modelo
de verdade o teste mediria o humor dele, não a regra.

### O caminho aparece na tela

Cada resposta carrega as consultas que a produziram, e a tela as mostra em "Como cheguei
nisso". Não é enfeite de transparência: uma leitura crítica do acervo é indistinguível de
um palpite bem escrito, e é essa lista que permite conferir.

## O atalho `#`

Digitar `#` no campo abre a lista de clientes; cada letra estreita a busca; `↑↓` navega e
`Enter` escolhe. O que vai para o servidor é o **identificador do caso**, não o nome — é o
que faz a pergunta chegar ao caso certo mesmo com homônimo (o acervo tem 24 "Maria
Santos"), grafia diferente ou nome incompleto. A escolha explícita vence o roteador, como
o clique na lista de desambiguação.

A lógica vive em `frontend/src/lib/atalhoDeCaso.ts`, fora do componente, porque precisa
casar com a normalização do servidor (`conversa_geral.normalizar`): se as duas divergirem,
a lista oferece um caso que o roteador depois não reconhece. Testes:

```
node --experimental-strip-types src/lib/atalhoDeCaso.teste.mjs
```

## O que ainda não existe

**Do lado do `ia-juridica` continua não havendo rota de acervo.** O chat de lá é
`POST /api/v1/cases/{case_id}/chat` — por caso, sempre. Quem responde sobre o escritório
inteiro é o analista deste lado, medindo com as ferramentas acima.

O que ele NÃO alcança está declarado, e cada consulta devolve isso junto do dado
(`nao_medido`): valor de causa, prazo processual, honorários e responsável pelo caso não
existem em lugar nenhum deste sistema. Perguntado sobre eles, o analista diz que não sabe
— foi verificado ao vivo.

A rota abaixo continua fazendo sentido para o dia em que o **estado jurídico** de todos os
casos (fatos, classificação, pendências do playbook) precisar ser lido de uma vez: hoje o
analista abre um dossiê por vez, o que resolve dez casos e não resolveria duzentos.

### A rota que faltaria

Do lado do `ia-juridica` (repositório separado — nada disto foi escrito lá):

```
POST /api/v1/portfolio/chat
```

**Entrada**

```jsonc
{
  "message": "Quais casos estão parados esperando documento?",
  "conversation_id": "conversation_…",   // opcional, para continuar o fio
  "filters": {                            // opcional
    "status": ["DRAFT", "ACTIVE"],
    "blocking_only": true,
    "idle_days_min": 7
  }
}
```

O escopo é o escritório do token — o mesmo `organization_id` que já delimita todas as
demais rotas. Os filtros espelham o que a Carteira usa hoje (`lib/useCarteira.ts`), para
que "casos parados" signifique a mesma coisa nas duas telas.

**Saída** — a mesma forma do chat por caso, mais um bloco de casos:

```jsonc
{
  "conversation_id": "conversation_…",
  "message": {
    "id": "message_…",
    "role": "ASSISTANT",
    "content": "Três casos estão bloqueados por documento indispensável…",
    "citations": [],
    "payload": {
      "assertions": [
        { "statement": "…", "nature": "PROVEN_FACT", "refs": ["case_…"] }
      ],
      "gaps": [],
      "confidence": 0.9
    },
    "created_at": "2026-08-25T14:20:00Z"
  },
  "cases": [
    {
      "case_id": "case_…",
      "reference": "2026-0142",
      "title": "…",
      "blocking_issues": ["PPP", "CAT"]
    }
  ],
  "proposals": []
}
```

Três exigências que não são detalhe:

- **`refs` das afirmações aponta para casos** (`case_…`), e não para fatos. É o que permite
  a tela levar do texto da resposta ao dossiê correspondente;
- **o guardrail de lastro vale igual.** Uma resposta sobre o acervo que não consiga ancorar
  suas afirmações tem de ser reprovada do mesmo jeito que a resposta sobre um caso é hoje —
  contagem sem lastro é a falácia mais fácil de produzir numa pergunta de agregação;
- **a natureza continua obrigatória** em cada afirmação. "Três casos estão bloqueados" é
  `PROVEN_FACT`; "provavelmente o cliente não vai enviar" não é resposta.

### O que muda deste lado quando ela existir

Pouco, de propósito:

1. `conversa_geral.rotear` passa a devolver `ACERVO` como destino **respondível**, em vez
   de recusa;
2. `conversas._do_acervo` chama a rota nova em vez de devolver `TEXTO_ACERVO`;
3. `AgenteGeral.tsx` ganha o bloco de casos citados na resposta (o desenho já o tem: linha
   com referência, cliente e selo da pendência).

O histórico, a busca, o agrupamento por dia e as demais naturezas não mudam.

## Banco

Duas tabelas novas, criadas pelo mesmo DDL idempotente das demais (`app/banco.py`,
`inicializar_schema()`):

- **`dbo.acervo_conversas`** — `id`, `titulo`, `resumo`, `usuario`, `caso_id`,
  `conversa_ref`, `criado_em`, `atualizado_em`;
- **`dbo.acervo_conversa_mensagens`** — `id`, `conversa_id` (cascata), `papel`, `conteudo`,
  `natureza`, `payload` (JSON), `criado_em`.

A conversa é do **Acervo**, e não do agente: ela começa antes de haver caso e pode nunca ter
um. Só ela mistura o que o agente respondeu sobre um caso, o que o glossário explicou e a
recusa honesta — nenhum dos outros lados tem a transcrição inteira, e é ela que a tela
reabre. O `conversa_ref` guarda o `conversation_id` do agente para a segunda pergunta
continuar o mesmo raciocínio; trocar de caso o zera, porque o fio de lá pertence a um caso.

O `usuario` é o `sub` do token (não o nome de usuário, que muda). O histórico é de quem
perguntou: a listagem, a leitura e a exclusão filtram por ele, e conversa de outra pessoa
responde `404` — dizer "existe, mas não é sua" já entrega que ela existe.

## Testes

```
.venv\Scripts\python.exe -m tests.test_conversa_geral   # roteamento e glossário
.venv\Scripts\python.exe -m tests.test_conversas        # tradução da resposta do agente
```

Os dois rodam sem banco e sem rede. O que eles **não** alcançam é a persistência e o HTTP,
e foi ali que os dois defeitos reais apareceram: a coluna `ordem` não existia no banco (a
tabela já tinha sido criada sem ela, e `CREATE TABLE` não alcança tabela que existe — por
isso ela entrou em `COLUNAS_NOVAS`), e um `SELECT` com duas colunas sem apelido devolvia
uma linha com um valor só, porque `banco.Linha` indexa por nome de coluna.

As amostras de `tests/fixtures/` são respostas **reais** do `ia-juridica`, capturadas de um
caso do acervo — e não JSON escrito a partir da leitura do outro código. São duas, de
propósito: uma que o guardrail de lastro do agente **reprovou** (sem afirmações, com as
lacunas explicando o motivo) e uma que passou, com afirmação, natureza e proveniência. O
nome do cliente foi trocado por um fictício antes de entrar no repositório; a estrutura é
a que veio.
