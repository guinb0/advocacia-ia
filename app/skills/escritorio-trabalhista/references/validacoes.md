# Validações da peça (declarativas — a skill decide o que conferir)

O motor de conferência (`app/conferencia_peticao.py`) não conhece direito material nem
estratégia de escritório: ele só executa os tipos de regra abaixo (`item`, `soma_coerente`,
`topico_sem_pedido`, `padrao_proibido`, `citacao_sem_fonte`, `tamanho_minimo`, `secao_obrigatoria`) sobre as seções da peça. O que
conferir, com que critério e com que mensagem é escrito AQUI. Sem este arquivo, não há
validação jurídica — só as checagens genéricas do motor (documento citado que não existe,
anexo alegado que não existe, número/data sem origem nos autos, marcador de pendência quebrado).

`secao` / `secoes` usam o PAPEL da seção (`code` devolvido pelo redator), como metadado.

Parâmetros `qualificacao` (campos que a abertura da peça exige, conforme `estrutura_peca.md` item 2) e `estrutura` (endereçamento) são lidos pelo `petition_linter`.

Em síntese, o que estas regras exigem do redator: pedido de PAGAMENTO com valor e critério
(art. 840, § 1º, da CLT); pedido declaratório/procedimental/probatório SEM valor; valor da
causa igual à soma dos pedidos; nenhum tópico que conclua contra o cliente; nenhum capítulo
que exponha fragilidade do próprio caso; súmula/OJ/tema só se estiver no material.

```validacao
{
 "parametros": {
  "contexto_normativo": "(lei|decreto|resolu|ato|portaria|instru|emenda|provis|\\bnr\\b|s[uú]mula|\\boj\\b|tema|art\\.?|artigo|par[aá]grafo|inciso|precedente|processo|recurso|cnj|csjt|tst|trt|stf|stj)[^\\n]{0,25}$",
  "sinonimos_de_documento": [
   [
    "ctps",
    "carteira de trabalho"
   ],
   [
    "rg",
    "identidade",
    "registro geral"
   ],
   [
    "pis",
    "nis",
    "pasep"
   ],
   [
    "cnh",
    "habilitacao"
   ],
   [
    "trct",
    "termo de rescisao",
    "rescisao"
   ],
   [
    "cat",
    "comunicacao de acidente"
   ],
   [
    "aso",
    "atestado de saude ocupacional"
   ],
   [
    "holerite",
    "contracheque",
    "recibo de pagamento",
    "demonstrativo de pagamento"
   ],
   [
    "comprovante de residencia",
    "comprovante de endereco",
    "conta de luz",
    "conta de energia",
    "conta de agua"
   ],
   [
    "carta de concessao",
    "comunicacao de decisao",
    "concessao do beneficio"
   ],
   [
    "cnis",
    "cadastro nacional de informacoes sociais",
    "extrato previdenciario"
   ]
  ],
  "qualificacao": {
   "exigida": true,
   "secao": "HEADING",
   "campos": {
    "autor": [
     "nome",
     "nacionalidade",
     "estado_civil",
     "profissao",
     "rg",
     "cpf",
     "endereco"
    ],
    "reu": [
     "nome",
     "cnpj",
     "endereco"
    ]
   }
  },
  "estrutura": {
   "enderecamento_regex": "ju[íi]zo|vara do trabalho",
   "blocos_unicos": [
    "enderecamento",
    "titulo_acao",
    "objeto"
   ],
   "titulo_da_acao_regex": "^reclama[cç][aã]o trabalhista"
  },
  "bases_de_calculo": {
   "liquido": "sal[áa]rio l[íi]quido|remunera[çc][ãa]o l[íi]quida|valor l[íi]quido",
   "bruto": "sal[áa]rio bruto|remunera[çc][ãa]o bruta",
   "minimo": "sal[áa]rios?[- ]m[íi]nimos?",
   "ultima_remuneracao": "[úu]ltim[oa] (?:sal[áa]rio|remunera[çc][ãa]o)"
  },
  "funcoes_de_conteudo": {
   "comunicacoes_processuais": "intima[cç][õo]es|publica[cç][õo]es|notifica[cç][õo]es|exclusivamente (?:ao|em nome d[oa]s?) advogad|sob pena de nulidade",
   "justica_gratuita": "justi[cç]a gratuita|hipossufici|art\\. 790",
   "competencia": "compet[êe]ncia|art\\. 651|foro",
   "provas": "prova (?:testemunhal|documental|pericial)|oitiva|depoimento pessoal|rol de testemunhas|exibi[cç][ãa]o de documentos",
   "requerimentos_processuais": "cita[cç][ãa]o|rito (?:ordin[áa]rio|sumar[ií]ssimo)|julgamento antecipado|audi[êe]ncia|revelia",
   "honorarios": "honor[áa]rios",
   "juros_correcao": "juros de mora|corre[cç][ãa]o monet[áa]ria|IPCA|taxa selic"
  }
 },
 "regras": [
  {
   "id": "valor_inventado_em_pedido_sem_conteudo_economico",
   "tipo": "item",
   "secao": "CLAIMS",
   "separador_de_itens": "\\n\\s*(?:\\*\\*)?\\s*(?=[a-z]\\)|\\d{1,2}[.)]\\s)",
   "inicio_de_item": "(?:[a-z]\\)|\\d{1,2}[.)])",
   "ignorar_item": "valor da causa|d[aá]-se [àa] causa",
   "quando": [
    {
     "em": "cabeca",
     "casa": "100%\\s*digital|telepresencial|reconhe[çc]|declar[ao]|oitiva|testemunha|per[ií]cia|responsabilidade (?:objetiva|subjetiva)|gratuidade|justi[çc]a gratuita|cita[çc][ãa]o|produ[çc][ãa]o de|provas? admitid|intima|notifica|exib"
    },
    {
     "em": "item",
     "casa": "(?:valor|custo)s?\\s+estimad|estimad[oa]\\s+(?:em|de)\\s+R\\$|atribui-se valor"
    }
   ],
   "codigo": "VALOR_INVENTADO_EM_PEDIDO_SEM_CONTEUDO_ECONOMICO",
   "mensagem": "Pedido declaratório, procedimental ou probatório com valor estimado sem base em documento — valor inventado.",
   "correcao": "Retire o valor e o critério deste pedido: pedido sem conteúdo econômico não leva valor, e o valor da causa considera só os pedidos de pagamento.",
   "bloqueia": true
  },
  {
   "id": "valor_sem_criterio",
   "tipo": "item",
   "secao": "CLAIMS",
   "separador_de_itens": "\\n\\s*(?:\\*\\*)?\\s*(?=[a-z]\\)|\\d{1,2}[.)]\\s)",
   "inicio_de_item": "(?:[a-z]\\)|\\d{1,2}[.)])",
   "ignorar_item": "valor da causa|d[aá]-se [àa] causa",
   "quando": [
    {
     "em": "cabeca",
     "nao_casa": "100%\\s*digital|telepresencial|reconhe[çc]|declar[ao]|oitiva|testemunha|per[ií]cia|responsabilidade objetiva|responsabilidade subjetiva|gratuidade|justi[çc]a gratuita|cita[çc][ãa]o|produ[çc][ãa]o de|provas? admitid|intima|notifica|exib|custas|honor[aá]rio|juros|corre[çc][ãa]o monet|proced[eê]ncia|recolhimento|contribui[çc][õo]es previdenci"
    },
    {
     "em": "item",
     "casa": "R\\$\\s*[\\d.]+,\\d{2}"
    },
    {
     "em": "item",
     "nao_casa": "dano[s]? mora|danos? est[ée]tic|arbitr"
    },
    {
     "em": "item_sem_pendente",
     "nao_casa": "\\d\\s*[×x*]\\s*[\\dR]|[×x*]\\s*\\d|=\\s*R\\$|\\b\\d+\\s*meses\\b.{0,160}(?:mensa|por m[êe]s|ao m[êe]s|/m[êe]s)|(?:mensa|por m[êe]s|ao m[êe]s|/m[êe]s).{0,160}\\b\\d+\\s*meses\\b"
    }
   ],
   "pendente": "\\[PENDENTE[^\\]]*\\]",
   "codigo": "VALOR_SEM_CRITERIO",
   "mensagem": "Valor estimado sem critério: a peça não mostra de onde saiu o número.",
   "correcao": "Escreva ao lado do valor a conta que o gera a partir dos dados dos documentos (ex.: horas/dia × dias × meses × valor-hora × adicional). Faça a conta com premissas EXPLÍCITAS — salário e período tirados dos documentos, jornada tirada do relato (dita «conforme relato») — e escreva cada premissa. Nunca um número redondo sem conta, nem [PENDENTE] no lugar da conta.",
   "bloqueia": true
  },
  {
   "id": "pedido_sem_valor",
   "tipo": "item",
   "secao": "CLAIMS",
   "separador_de_itens": "\\n\\s*(?:\\*\\*)?\\s*(?=[a-z]\\)|\\d{1,2}[.)]\\s)",
   "inicio_de_item": "(?:[a-z]\\)|\\d{1,2}[.)])",
   "ignorar_item": "valor da causa|d[aá]-se [àa] causa",
   "quando": [
    {
     "em": "cabeca",
     "nao_casa": "100%\\s*digital|telepresencial|reconhe[çc]|declar[ao]|oitiva|testemunha|per[ií]cia|responsabilidade objetiva|responsabilidade subjetiva|gratuidade|justi[çc]a gratuita|cita[çc][ãa]o|produ[çc][ãa]o de|provas? admitid|intima|notifica|exib|custas|honor[aá]rio|juros|corre[çc][ãa]o monet|proced[eê]ncia|recolhimento|contribui[çc][õo]es previdenci"
    },
    {
     "em": "cabeca",
     "nao_casa": "honor[aá]rio|juros|corre[çc][ãa]o monet|gratuidade|justi[çc]a gratuita|exib|notifica|cita[çc][ãa]o|proced[eê]ncia|produ[çc][ãa]o de prova|intima|expedi[çc][ãa]o de of[ií]cio|anota[çc][ãa]o|reintegra|100%\\s*digital|telepresencial|reconhe[çc]|declar[ao]|oitiva|testemunha|per[ií]cia|responsabilidade objetiva|responsabilidade subjetiva|recebimento|processamento|rito\\b"
    },
    {
     "em": "item",
     "nao_casa": "R\\$\\s*[\\d.]+,\\d{2}"
    },
    {
     "em": "item",
     "nao_casa": "\\[PENDENTE:[^\\]]*valor"
    }
   ],
   "codigo": "PEDIDO_SEM_VALOR",
   "mensagem": "Pedido sem valor: o art. 840, § 1º, da CLT exige pedido certo, determinado e com indicação do valor — sem isso o pedido pode ser extinto sem resolução do mérito.",
   "correcao": "Se o pedido é de PAGAMENTO e os documentos trazem os dados, dê um valor ESTIMADO com o critério escrito ao lado (ex.: nº de horas × valor-hora × meses). Se o valor depende de documento que NÃO está nos autos, NÃO estime nem invente custo, base ou critério: escreva [PENDENTE: valor a apurar com <documento>] e mantenha o pedido. Pedido declaratório, procedimental ou probatório não leva valor. Faça a conta com premissas EXPLÍCITAS — salário e período tirados dos documentos, jornada tirada do relato (dita «conforme relato») — e escreva cada premissa. Nunca um número redondo sem conta, nem [PENDENTE] no lugar da conta.",
   "bloqueia": true
  },
  {
   "id": "valor_da_causa_coerente",
   "tipo": "soma_coerente",
   "secao": "CLAIMS",
   "separador_de_itens": "\\n\\s*(?:\\*\\*)?\\s*(?=[a-z]\\)|\\d{1,2}[.)]\\s)",
   "inicio_de_item": "(?:[a-z]\\)|\\d{1,2}[.)])",
   "ignorar_item": "valor da causa|d[aá]-se [àa] causa",
   "excluir_cabeca": "100%\\s*digital|telepresencial|reconhe[çc]|declar[ao]|oitiva|testemunha|per[ií]cia|responsabilidade objetiva|responsabilidade subjetiva|gratuidade|justi[çc]a gratuita|cita[çc][ãa]o|produ[çc][ãa]o de|provas? admitid|intima|notifica|exib|custas|honor[aá]rio|juros|corre[çc][ãa]o monet|proced[eê]ncia|recolhimento|contribui[çc][õo]es previdenci",
   "valor": "R\\$\\s*([\\d.]+,\\d{2})",
   "resultado": "=\\s*R\\$\\s*([\\d.]+,\\d{2})",
   "anunciado": "(?:totaliz\\w*|valor estimado(?:\\s+de)?|estimad[oa] em|no valor de|valor de|total de|montante de)\\s*:?\\s*R\\$\\s*([\\d.]+,\\d{2})",
   "total_em": "VALUE",
   "codigo": "VALOR_DA_CAUSA_INCOERENTE",
   "mensagem": "O valor da causa ({total}) não bate com a soma dos valores dos pedidos ({soma}).",
   "correcao": "O valor da causa é a soma dos valores dados na seção de pedidos. Não crie parcela nova só para arredondar o total — ajuste o total à soma.",
   "bloqueia": true
  },
  {
   "id": "topico_contra_o_cliente",
   "tipo": "topico_sem_pedido",
   "secoes": [
    "PRELIMINARY",
    "LEGAL_GROUNDS",
    "CLAIMS"
   ],
   "divisor": "\\n(?=\\s*\\*\\*[IVXLC]+\\s*[–—-]|\\s*[IVXLC]+\\s*[–—-]\\s)",
   "conclui": "n[ãa]o se aplica|n[ãa]o h[áa] (?:atraso|parcela|direito|diferen|elementos? que indique)|n[ãa]o (?:faz|fazem) jus|[ée] indevid[oa]|n[ãa]o se (?:formula|deduz|pleiteia) (?:o )?pedido",
   "pede": "\\brequer|\\bpleite|faz jus|s[ãa]o devid|[ée] devid|condena[çr]|deferi",
   "codigo": "TOPICO_CONTRA_O_CLIENTE",
   "mensagem": "Este tópico conclui que o cliente NÃO tem direito a algo — isso não pertence à petição inicial dele.",
   "correcao": "Retire o tópico inteiro da peça. Se a observação importa, ela vai para a análise (observações ao advogado), nunca para o texto que será protocolado.",
   "bloqueia": true
  },
  {
   "id": "topico_de_fragilidade",
   "tipo": "padrao_proibido",
   "secoes": [
    "PRELIMINARY",
    "FACTS",
    "LEGAL_GROUNDS"
   ],
   "regex": "^\\s*(?:\\*\\*)?[IVXLC]+(?:\\.\\d+)*\\s*[–—-]\\s*(?:DA|DAS|DO|DOS)\\s+(?:DIVERG[ÊE]NCIA|INCONSIST[ÊE]NCIA|CONTRADI[ÇC]|FRAGILIDADE|LACUNA)",
   "multilinha": true,
   "codigo": "TOPICO_DE_FRAGILIDADE",
   "mensagem": "Este capítulo aponta divergência ou fragilidade do próprio caso — o que enfraquece o cliente e não pertence à petição inicial.",
   "correcao": "Retire o capítulo inteiro. Se a observação importa ao advogado, ela vai para as observações da análise, nunca para o texto que será protocolado.",
   "bloqueia": true
  },
  {
   "id": "citacao_de_precedente_sem_fonte",
   "tipo": "citacao_sem_fonte",
   "regex": "\\b(s[úu]mula(?:\\s+vinculante)?|orienta[çc][ãa]o\\s+jurisprudencial|\\bOJ|tema)\\s*(?:n[ºo°.]*\\s*)?(\\d{1,4})",
   "equivalentes": {
    "orien": [
     "orientacao",
     "oj"
    ],
    "oj": [
     "oj",
     "orientacao"
    ]
   },
   "codigo": "CITACAO_NAO_VERIFICADA",
   "mensagem": "«{citacao}» foi citada de memória: não está no material do acervo recebido nesta geração, e o acervo ainda não tem catálogo de súmulas para conferir.",
   "correcao": "Substitua por precedente que esteja NO MATERIAL recebido (blocos JULGADOS, LEGISLAÇÃO ou a skill) e explique por que se aplica; se não houver, REMOVA a citação e mantenha só a norma. Nunca deixe marcador no texto.",
   "bloqueia": true
  },
  {
   "id": "secoes_obrigatorias",
   "tipo": "secao_obrigatoria",
   "secoes": [
    "HEADING",
    "FACTS",
    "LEGAL_GROUNDS",
    "CLAIMS",
    "CLOSING"
   ],
   "codigo": "MISSING_SECTION",
   "mensagem": "Seção obrigatória sem texto.",
   "correcao": "Redija a seção conforme a skill.",
   "bloqueia": false
  },
  {
   "id": "fatos_curtos",
   "tipo": "tamanho_minimo",
   "secoes": [
    "FACTS"
   ],
   "minimo_chars": 280,
   "codigo": "FACTS_TOO_SHORT",
   "mensagem": "Os fatos estão curtos demais para sustentar os pedidos.",
   "correcao": "Desenvolva a narrativa cronológica com os fatos e provas do caso.",
   "bloqueia": false
  },
  {
   "id": "direito_curto",
   "tipo": "tamanho_minimo",
   "secoes": [
    "LEGAL_GROUNDS"
   ],
   "minimo_chars": 350,
   "codigo": "GROUNDS_TOO_SHORT",
   "mensagem": "A fundamentação jurídica está curta demais.",
   "correcao": "Desenvolva cada tese: norma, fato, prova, subsunção e consequência.",
   "bloqueia": false
  },
  {
   "id": "placeholders_proibidos",
   "tipo": "padrao_proibido",
   "secoes": "*",
   "regex": "\\[(?:PESQUISAR|CONFERIR|INFORMA[ÇC][ÃA]O A CONFIRMAR)[^\\]]*\\]",
   "codigo": "PLACEHOLDER_NO_TEXTO",
   "mensagem": "Marcador de pesquisa/confirmação no corpo da peça: o texto final não pode conter marcadores.",
   "correcao": "Resolva com o material recebido (julgados, legislação, skill, documentos). Se não houver fonte, remova a afirmação ou reescreva sem citar precedente. Dado do caso ausente vira [PENDENTE: <dado>] curto, uma vez, apenas se a skill o permitir.",
   "bloqueia": true
  },
  {
   "id": "citacao_literal_sem_fonte",
   "tipo": "citacao_literal_sem_fonte",
   "secoes": "*",
   "regex": "[“\"]([^”\"\n]{50,900})[”\"]",
   "minimo_chars": 40,
   "codigo": "CITACAO_LITERAL_SEM_FONTE",
   "mensagem": "Trecho entre aspas que não consta literalmente do material recebido (documentos, entrevista, julgados, legislação ou skill).",
   "correcao": "Se o trecho é de julgado, lei ou documento, copie-o EXATAMENTE do material; se não estiver lá, tire as aspas e parafraseie o que o material realmente diz, ou remova a citação. Nunca aspas em texto que você não leu no material.",
   "bloqueia": true
  },
  {
   "id": "transcricao_deve_ir_em_bloco",
   "tipo": "padrao_proibido",
   "secoes": "*",
   "multilinha": true,
   "regex": "^(?!\\s*>)[^\n]*[“\"][^”\"\n]{220,}[”\"]",
   "codigo": "TRANSCRICAO_FORA_DE_BLOCO",
   "mensagem": "Transcrição longa (ementa, tese, trecho de julgado ou de lei) entre aspas no meio do parágrafo: pela skill (formatacao.md) ela vai em bloco `>` próprio.",
   "correcao": "Mova a transcrição para um bloco `>` separado, com a identificação (tribunal, órgão, número, relator, data) entre parênteses ao final do bloco; deixe no parágrafo só a apresentação e, depois do bloco, a aplicação ao caso.",
   "bloqueia": false
  },
  {
   "id": "ausencia_documental_nao_e_prova_de_ausencia",
   "tipo": "afirmacao_categorica_sem_qualificador",
   "secoes": "*",
   "regex": "(?:aus[êe]ncia|inexist[êe]ncia|falta)\\s+de\\s+(?:qualquer\\s+|nenhum[ao]?\\s+)?[^.\\n]{0,70}?(?:confirma|comprova|demonstra|evidencia|revela)|(?:reclamada|empregador[a]?)\\s+n[ãa]o\\s+(?:adotou|possu[ií]a|manteve|providenciou|dispunha|ofereceu|forneceu)",
   "qualificadores": "n[ãa]o consta|n[ãa]o h[áa]\\s+(?:nos autos|prova|registro|documento)|nos autos|alega|cabe(?:ndo)?\\s+[àa]\\s+reclamada|[ôo]nus|art\\.\\s*818|at[ée] o momento|segundo o relato",
   "janela": 220,
   "codigo": "AUSENCIA_DOCUMENTAL_COMO_PROVA",
   "mensagem": "A peça usa a falta de documento como prova de que algo não existe/não foi feito (ausência de prova ≠ prova de ausência).",
   "correcao": "Reescreva como ALEGAÇÃO ancorada: «não consta dos documentos juntados… cabendo à reclamada, que detém a prova, demonstrar (art. 818, § 1º, CLT)» — nunca como fato comprovado.",
   "bloqueia": true
  }
 ]
}
```
