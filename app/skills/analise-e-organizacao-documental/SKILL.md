---
name: analise-e-organizacao-documental
description: 'Recebe a documentação bruta de qualquer caso (fotos, scans, PDFs bagunçados, prints) e faz a análise jurídica completa — qualquer área do direito (previdenciário, trabalhista, cível, criminal, família, consumidor): parecer, possibilidades de ação, riscos classificados, análise documento a documento (atualizado/desatualizado, pode ou não melhorar, o que falta por tese) — e só após confirmação organiza os documentos em um PDF por documento, nomeados "Doc N. Nome Do Documento.pdf", mais Entrevista.pdf e Checklist.pdf. Cobre também triagem de cliente novo, revisão de procuração/contrato/declaração, pesquisa jurídica e apoio de assistente pessoal. Use para analisar caso, dizer o que cabe, organizar documentos, preparar protocolo, triagem, revisar documento do escritório ou pesquisar jurisprudência — qualquer área do direito.'
---

# Análise de Caso e Organização Documental

Fluxo único: transformar documentação bruta em (1) uma análise jurídica completa do caso e (2) uma pasta de documentos pronta para protocolo — nessa ordem, com uma parada obrigatória para confirmação entre as duas.

## Regra de ouro

> **1 documento = 1 arquivo PDF.** Nunca junte documentos diferentes no mesmo PDF. Nunca divida o mesmo documento em vários PDFs.

RG frente e verso são **um** documento (2 páginas). RG e CPF são **dois** documentos, mesmo que tenham vindo na mesma foto ou no mesmo PDF.

## Visão geral do fluxo

1. **Inspecionar o lote** — script `inspecionar.py`.
2. **Identificar cada página** — qual documento é, ler o conteúdo de fato.
3. **Análise jurídica completa do caso** — qualquer área do direito: parecer, possibilidades, riscos, provas, análise documento a documento.
4. **Perguntar antes de arrumar** — sempre, sem exceção.
5. **Montar os PDFs** — script `montar.py`, com a nomenclatura e ordem definidas abaixo.
6. **Conferir e entregar.**

---

### Etapa 1 — Inspecionar o lote

Coloque tudo o que foi recebido em uma pasta e rode:

```bash
python3 <skill>/scripts/inspecionar.py <pasta_entrada> <pasta_trabalho>
```

O script explode PDFs e imagens em páginas individuais, gera **miniaturas** e mede cada página: orientação, inclinação, nitidez, brilho, página em branco, resolução e duplicidade. Leia `<pasta_trabalho>/inventario.md`.

Os alertas do script são **pistas, não veredito**. Abra as miniaturas em `<pasta_trabalho>/miniaturas/` e confira você mesmo.

**Se os scripts não estiverem disponíveis**, não interrompa: faça à mão (`pdf2image`, `PIL`, `hashlib`) — o fluxo e as regras abaixo valem igual.

### Etapa 2 — Identificar cada página

Para cada página, determine **qual documento é** e **qual página dele é**, pela leitura visual da miniatura; use OCR quando precisar confirmar um dado:

```bash
python3 -c "import pytesseract,sys; print(pytesseract.image_to_string(sys.argv[1])[:1500])" <pagina.png>
```

O Tesseract deste ambiente só tem modelo em inglês — serve para localizar números, datas e palavras-chave, mas erra acentuação em português. **Nunca transcreva dado do cliente a partir do OCR sem conferir na imagem.**

Monte a lista de documentos identificados e o que ficou duvidoso.

#### Arquivos duplicados

Duplicidade **total** é a mesma página, do mesmo documento, com o mesmo conteúdo. **Nunca descarte** por conta própria: monte o principal com o nome padrão e o duplicado como arquivo próprio, nome igual acrescido de `(Duplicado)` ao final — `Doc 3. RG.pdf` e `Doc 3. RG (Duplicado).pdf`. Mais de um: `(Duplicado 2)`, `(Duplicado 3)`. Informe no relatório e pergunte antes de excluir — a exclusão só ocorre com autorização expressa.

Não é duplicidade: frente e verso do mesmo cartão, duas vias distintas do mesmo tipo (dois atestados de datas diferentes), e a mesma página em qualidades diferentes (aproveite a melhor cópia como documento único).

---

### Etapa 3 — Análise jurídica completa do caso (qualquer área do direito)

Com os documentos identificados e **lidos de fato** (conteúdo, não só o tipo), monte a análise completa abaixo. Vale para **qualquer área do direito** — previdenciário, trabalhista, cível, criminal, família, consumidor, tributário, o que o acervo indicar — nunca restrinja o raciocínio a um tipo específico de ação.

#### 3.1 — Resumo executivo

- Fatos, em ordem cronológica.
- Partes envolvidas (cliente, contraparte, terceiros).
- Questão jurídica central.
- Objetivo do cliente (o que ele quer obter).

#### 3.2 — Parecer jurídico

- Quais direitos podem existir, a partir do que os documentos efetivamente comprovam — nunca do que pareceria plausível.
- Quais teses são juridicamente sustentáveis.
- Quais ações judiciais são cabíveis (pode haver mais de uma, inclusive de áreas diferentes — ex. ação trabalhista + ação previdenciária do mesmo fato; ação cível + representação criminal).
- Estratégia que parece mais adequada, com o motivo.
- Pedidos principais e pedidos acessórios/subsidiários.
- Chances práticas de cada caminho, com base no que a documentação sustenta — nunca inventar percentual ou probabilidade sem base.

#### 3.3 — Possibilidades jurídicas (uma entrada por hipótese)

Para cada ação cabível identificada, apresente em tabela ou tópicos:

| Campo | Conteúdo |
|---|---|
| Objeto da ação | O que se pretende obter |
| Fundamento legal | Dispositivo(s) exato(s) — nunca citar de memória sem confirmar |
| Requisitos | O que a lei exige para o direito existir |
| Documentos necessários | O que instrui essa ação especificamente |
| Provas necessárias | Documental, testemunhal, pericial — o que falta produzir |
| Riscos | Ver 3.4 |
| Pontos fortes | O que já está bem comprovado no acervo |
| Pontos fracos | O que é frágil, contraditório ou pode ser contestado |
| Probabilidade prática | Alta/média/baixa, com o motivo — nunca número inventado |
| Dificuldade processual | Rito, prazo, competência, complexidade probatória |
| Alternativa | Caminho alternativo caso essa via não seja viável |

#### 3.4 — Riscos jurídicos (classificados)

Verificar e classificar como **Alto / Médio / Baixo**, o que for aplicável ao caso: prescrição, decadência, ausência de provas, nulidades, contradições, documentos frágeis, testemunhas insuficientes, problemas processuais/de competência, teses desfavoráveis, jurisprudência divergente, custos, honorários, necessidade de perícia.

#### 3.5 — Análise documento a documento

Para cada documento relevante do acervo (laudo, PPP, CAT, boletim, comprovante, contrato, extrato, certidão etc.), informar:

- **Pontos fortes** — o que ele comprova a favor da tese.
- **Vulnerabilidades** — o que nele enfraquece a tese ou pode ser contestado.
- **Inconsistências** — datas, nomes, assinaturas, valores ou informações que divergem entre documentos do mesmo lote.
- **Atualizado ou desatualizado** — para documentos com prazo de validade prática (laudos médicos, PPP, comprovante de residência, certidões, extratos): dizer expressamente se a data ainda serve para o tipo de ação identificado, ou se está velho demais e enfraquece o caso.
- **Pode melhorar ou não pode melhorar** — se dá para obter uma versão melhor/mais recente desse documento (ex. novo laudo, PPP atualizado, comprovante mais recente), ou se é documento definitivo que não muda com o tempo (certidão de óbito, RG, contrato já assinado) e portanto "não pode melhorar" — só se refaz se estiver com problema técnico (ilegível, incompleto).
- **O que é necessário para cada tese** — cruzando com a tabela de possibilidades (3.3): para a tese X, esse documento resolve o requisito Y; para a tese Z, ainda falta um documento W.

#### 3.6 — Provas

- Quais já existem e são suficientes.
- Quais existem mas estão fracas (e por quê).
- Quais faltam completamente.
- Como obter cada uma (quem procurar, qual órgão, qual prazo).
- Importância de cada uma para o resultado do caso.

#### 3.7 — Próximos passos

Checklist objetivo, em ordem de prioridade, do que fazer a seguir (documentos a pedir ao cliente, providências administrativas antes do ajuizamento, decisões que a advogada precisa tomar).

#### 3.7-A — Documentos faltantes: para qual ação faltam e caminho por documento (obrigatório)

Em **toda** análise, nunca listar documento faltante solto. Para cada faltante identificado em 3.5/3.6, entregar:

1. **Para qual ação/hipótese falta** — cruzar com a tabela 3.3 (ex.: "falta para o auxílio-acidente e para a trabalhista; não interfere no restabelecimento").
2. **Como obter** — órgão/sistema/canal, fundamento legal do direito de acesso, prazo estimado e quem faz (cliente, escritório, procurador).
3. **Ordem** — do mais rápido ao mais demorado.
4. **Classificação**, sempre expressa:
   - 🔴 **COMPROMETE** — sem ele a hipótese não se sustenta ou o protocolo não pode sair.
   - 🟡 **ERA MELHOR TER, MAS PODE PASSAR** — fortalece a hipótese, mas dá para ajuizar sem ele (indicar se pode ser suprido em juízo por exibição de documentos — arts. 396–400 CPC — ou produção antecipada de prova — art. 381 CPC).
   - ⚪ **NÃO INTERFERE** — só completude do acervo.
5. **Leitura prática ao final** — uma frase dizendo quais itens de fato travam o protocolo de cada hipótese e em quanto tempo se resolvem.

Formato sugerido:

| # | Documento | Falta para qual ação | Como obter (canal / fundamento / prazo) | Classificação |
|---|---|---|---|---|

Caminhos recorrentes (usar como referência, adaptando ao caso):
- Laudos SABI, cartas, extratos, CATs registradas → Meu INSS (gov.br do cliente) ou Central 135 ("cópia de processo administrativo").
- PPP, LTCAT, ASOs, prontuário do ambulatório, CAT, LISA, histórico funcional → requerimento escrito ao empregador com protocolo (PPP: art. 58, §4º, Lei 8.213/91; ASO: NR-7; CAT: art. 22 Lei 8.213/91; prontuário: art. 18, II, LGPD); se negar, exibição na inicial ou produção antecipada de prova.
- Prontuário hospitalar → SAME do hospital (Res. CFM 1.821/07; LGPD), com documento com foto.
- Ações anteriores → consulta por CPF nos PJe (TJ, TRF, TRT) e JTe.
- Laudo do médico assistente com grau de redução/nexo → roteiro de quesitos ao médico.
- Testemunhas → contato com o cliente; intimação pelo juízo (art. 825, § único, CLT).
- Normas coletivas → site do empregador/sindicato ou Mediador (MTE).

Esta seção é repetida, em versão resumida, na parte "Observações por hipótese" do `Checklist.pdf` e no Relatório final (📂 DOCUMENTOS NECESSÁRIOS).

**Nunca invente fato, documento, jurisprudência, dispositivo legal ou dado do cliente.** Quando faltar informação para concluir algum item acima, diga exatamente o que falta em vez de presumir.

---

### Etapa 4 — Perguntar antes de arrumar e gerar os PDFs

**Sempre pare aqui e pergunte, sem exceção** — mesmo quando o lote parecer completo e a análise, favorável. A Etapa 3 é o produto desta etapa; a organização física dos documentos (Etapa 5) só começa depois da confirmação do usuário.

Apresente, de forma objetiva:

- a análise completa da Etapa 3 (resumo, parecer, possibilidades, riscos, análise documento a documento, provas, próximos passos);
- os documentos identificados, quantas páginas cada um terá e o nome final que receberá;
- os **duplicados** encontrados;
- páginas **duvidosas** (pergunte, nunca adivinhe);
- páginas com **problema irreparável** (ilegíveis, cortadas, incompletas), dizendo o que precisa ser reenviado.

Só avance para a Etapa 5 depois que o usuário confirmar.

---

### Etapa 5 — Montar os PDFs

Escreva o plano em JSON e rode:

```bash
python3 <skill>/scripts/montar.py plano.json --relatorio
```

```json
{
  "cliente": "Maria Aparecida da Silva",
  "saida": "/mnt/user-data/outputs/Documentos_Maria_Aparecida_da_Silva",
  "padroes": {"corte": "auto", "endireitar": true, "realce": "suave", "pagina": "A4"},
  "documentos": [
    {"nome": "RG", "pessoal": true, "paginas": [
      {"arquivo": "trabalho/paginas/scan_001.png"},
      {"arquivo": "trabalho/paginas/scan_002.png", "girar": 180}
    ]},
    {"nome": "comprovante de residência", "pessoal": true, "paginas": [
      {"arquivo": "trabalho/paginas/scan_004.png", "girar": 270}
    ]},
    {"nome": "procuração", "pessoal": true, "paginas": [
      {"arquivo": "trabalho/paginas/scan_003.png"}
    ]},
    {"nome": "declaração de hipossuficiência", "pessoal": true, "paginas": [
      {"arquivo": "trabalho/paginas/scan_005.png"}
    ]},
    {"nome": "atestado médico 2024-03-11", "data": "2024-03-11", "paginas": [
      {"arquivo": "trabalho/paginas/scan_011.png"}
    ]}
  ]
}
```

#### Nomenclatura obrigatória

Formato fixo, sempre: **`Doc N. Nome Do Documento.pdf`**.

- Cada palavra do nome recebe a **primeira letra maiúscula e o restante minúsculo** — inclusive a própria palavra "Doc" (D maiúsculo, "oc" minúsculo, seguido de espaço, número, ponto, espaço, nome do documento). Exemplos: `Doc 1. RG.pdf`, `Doc 2. Comprovante De Residência.pdf`, `Doc 5. Declaração De Hipossuficiência.pdf`, `Doc 12. Atestado Médico 2024-03-11.pdf`.
- **Siglas conhecidas ficam sempre em caixa alta total**, nunca só a primeira letra: RG, CPF, CNIS, CTPS, PIS, PASEP, NIT, CAT, PPP, LTCAT, PCMSO, ASOS, BO, INSS, NB, DER, DIB, DCB, DII, TRF, JEF, CNH, CIN.
- Duplicado: mesmo nome do principal, acrescido de `(Duplicado)` — `Doc 3. RG (Duplicado).pdf`.
- Extensão `.pdf` sempre em minúsculo.
- O script `montar.py` e a função `comum.normalizar_nome` já aplicam essa formatação automaticamente a partir do campo `"nome"` do plano — escreva o `"nome"` em minúsculo ou como preferir no JSON, a normalização cuida da capitalização.

#### Ordem obrigatória da pasta (é também a ordem de numeração)

1. **RG** (documento de identificação).
2. **Comprovante de residência**.
3. **Procuração**.
4. **Declaração de hipossuficiência**.
5. **Demais documentos pessoais** — CPF (se não constar do RG), CTPS/PIS, CNIS, certidões pessoais, demais documentos de qualificação.
6. **Documentos comprobatórios do caso**, em ordem cronológica pura (do mais antigo ao mais recente pela data do próprio documento) — cartas do INSS, CAT, BO, laudos, exames, atestados, contratos, PPP, e qualquer outra prova, independentemente da área do direito.

No plano JSON, marque `"pessoal": true` nos seis primeiros blocos (1 a 5), na ordem em que devem aparecer no JSON (RG → comprovante de residência → procuração → declaração de hipossuficiência → demais pessoais), e `"data": "AAAA-MM-DD"` nos documentos do bloco 6. O `montar.py` numera `Doc 1`, `Doc 2`, … automaticamente nessa ordem. Documento sem data identificável vai para o fim do bloco 6, sinalizado para a advogada decidir onde encaixar.

#### Corte e legibilidade

- **Corte rente ao documento**, eliminando mesa, chão, dedo, borda e sombra. Margem final mínima e uniforme.
- **Documento preenchendo a página**, centralizado, linhas de texto horizontais.
- **Nada amputado** — carimbo, assinatura, número de protocolo, rodapé. Na dúvida, corte de menos.
- **Cartão/documento pequeno**: recorte só o cartão, amplie até ocupar a largura útil da página; frente e verso, um por página.
- **Contraste** ajustado até dar para ler texto miúdo e carimbo. Foto desfocada, escura ou com reflexo não se resolve com realce — vira pendência de reenvio.

Chaves por página: `girar` (0/90/180/270), `corte` (`auto`/`bordas`/`nenhum`), `endireitar` (`true`/`false`), `realce` (`nenhum`/`suave`/`forte`).

**Limite do tratamento de imagem:** giro, corte de bordas e contraste são permitidos porque não alteram o conteúdo. Nunca apague carimbo, marca d'água, anotação, rasura ou verso translúcido. Se o realce estiver apagando informação, volte para `suave`/`nenhum` e peça reenvio.

#### Entrevista do caso (sempre entregue, arquivo próprio, sem numeração)

**Todo caso entrega sempre um PDF com a análise completa da Etapa 3**, com o logo do escritório, contendo o resumo executivo, o parecer jurídico, a tabela de possibilidades, os riscos classificados, a análise documento a documento e os próximos passos — o conteúdo integral da Etapa 3, não um resumo dele.

- **Nome do arquivo: `Entrevista.pdf`** — sem o prefixo "Doc N.", sem número. Só a palavra "Entrevista", com a primeira letra maiúscula.
- **Posição na pasta: sempre o último arquivo**, depois de todos os "Doc N." (inclusive depois do último documento comprobatório do bloco 6).
- Gerar como PDF formatado (não texto solto) — títulos e subtítulos organizados, tabelas quando fizerem parte da Etapa 3 (possibilidades jurídicas), boa legibilidade.

#### Checklist de documentação (sempre entregue, arquivo próprio, com campos marcáveis)

Além da "Entrevista", gerar sempre um segundo PDF — **`Checklist.pdf`** (sem prefixo "Doc N.", mesma regra de nome único da Entrevista) — com:

1. **Lista de toda a documentação**, um item por linha, com campo marcável (☐) e o status já preenchido ao lado — presente, faltando, ou presente com pendência:

```
☐ Doc 1. RG ................................. ✅ presente
☐ Doc 2. Comprovante De Residência .......... ✅ presente
☐ Doc 5. Procuração .......................... ❌ faltando
☐ Doc 8. Laudo Médico ........................ ⚠️ presente, desatualizado (2019)
```

2. **Observações por hipótese de ação**, uma seção por hipótese identificada na Etapa 3.3, no formato direto de nota — cabimento, o que falta, se está completo:

```
📌 OBSERVAÇÕES

[Hipótese 1 — ex. Auxílio-Acidente]
Cabe [hipótese], documentação completa para o protocolo.

[Hipótese 2 — ex. Ação Trabalhista por Doença Ocupacional]
Cabe [hipótese], mas para este caso é preciso pedir: laudo médico atualizado
(o atual é de 2019) e PPP do período de 2020 a 2023, ainda não juntado.

[Hipótese 3 — ex. Revisão de Benefício]
Cabe [hipótese] apenas se confirmado que o prazo decadencial não está
consumado — verificar antes de avançar.
```

Cada observação é objetiva: diz se cabe, se a documentação está completa ou o que falta especificamente para aquele caso — nunca um comentário genérico solto sem ligação com a hipótese.

Esses dois PDFs (Entrevista e Checklist) são entregues em **toda** análise, mesmo quando o caso for simples ou a documentação estiver completa — não são opcionais.

### Etapa 6 — Conferir e entregar

Antes de entregar, rasterize os PDFs gerados e confira página por página:

```bash
python3 -c "
from pdf2image import convert_from_path; import sys, pathlib
for i, im in enumerate(convert_from_path(sys.argv[1], dpi=70), 1):
    im.save(f'/tmp/conf_{pathlib.Path(sys.argv[1]).stem}_{i}.png')
" <arquivo.pdf>
```

Confira: orientação, corte, legibilidade, ordem das páginas e se nenhum PDF misturou documentos. Confira também que `Entrevista.pdf` e `Checklist.pdf` foram gerados e estão completos. Depois entregue os arquivos com `present_files` e feche com o relatório abaixo.

## Relatório final

```
📋 ANÁLISE DO CASO
[Resumo executivo, parecer, possibilidades, riscos, análise documento a documento,
provas e próximos passos — conforme Etapa 3; entregue também em Entrevista.pdf]

📂 DOCUMENTOS ENTREGUES (ordem de juntada)
- Doc 1. RG.pdf — N página(s)
- Doc 2. Comprovante De Residência.pdf — N página(s)
- Doc N. [documento com data].pdf — N página(s)
- Entrevista.pdf — análise completa do caso
- Checklist.pdf — checklist marcável + observações por hipótese

📑 DUPLICADOS
- Doc N. Nome.pdf ↔ Doc N. Nome (Duplicado).pdf — excluo?

⚠️ PENDÊNCIAS / REENVIO NECESSÁRIO
- Documento — problema — o que reenviar

✅ CONFERÊNCIA
[ ] 1 documento = 1 PDF, sem mistura
[ ] Todas as páginas do mesmo documento reunidas e na ordem
[ ] Orientação correta em todas as páginas
[ ] Corte rente, sem fundo, sem conteúdo amputado
[ ] Legibilidade conferida página a página
[ ] Nomenclatura "Doc N. Nome Do Documento.pdf" (Title Case, siglas em caixa alta)
[ ] Ordem: RG → comprovante de residência → procuração → declaração de hipossuficiência → demais pessoais → comprobatórios em ordem cronológica
[ ] Entrevista.pdf gerada (análise completa, sem prefixo "Doc", último arquivo da pasta)
[ ] Checklist.pdf gerado (campos marcáveis + observações por hipótese, sem prefixo "Doc")
[ ] Pasta pronta para protocolo
```

---

## Triagem de caso novo

Quando o caso chegar sem documentação pronta, ou incompleto demais para iniciar a Etapa 1:

- Faça perguntas **curtas e objetivas**, uma de cada vez ou em bloco pequeno — nunca um questionário longo de uma vez.
- Pergunte **apenas o necessário** para identificar a área do direito e a(s) hipótese(s) de ação (Etapa 3.3). Nunca repita pergunta já respondida.
- Organize as respostas automaticamente à medida que chegam, num resumo que alimenta o Resumo Executivo (3.1).
- Caso a área identificada seja trabalhista, preencha a ficha de entrevista trabalhista completa (partes, vínculo, função, jornada, verbas pleiteadas, motivo da rescisão); se faltar algo, destaque só os campos pendentes, não refaça a ficha inteira.

## Elaboração e revisão de documentos do escritório (procuração, contrato, declaração)

Quando o caso pedir a geração ou revisão de um documento do próprio escritório (procuração, declaração de hipossuficiência, contrato de honorários, declaração diversa):

- **Nunca altere a estrutura do modelo do escritório** — só preencha os campos variáveis.
- Atualize a data automaticamente para a data corrente.
- Extraia o município automaticamente a partir do endereço informado (para o "foro de eleição" ou o "local e data").
- Sempre inclua: linha para assinatura, nome completo, CPF.
- Revise item a item antes de entregar: RG, CPF, estado civil, profissão, endereço, telefone, e-mail, foro, percentuais (honorários), datas, nomes, numeração de processo. **Nunca deixe uma inconsistência passar** — se notar divergência entre documentos do mesmo cliente (nome grafado diferente, endereço desatualizado), aponte antes de gerar.
- Se o escritório já tiver uma skill de geração automática (`kit`), prefira ela para o documento pronto; use esta seção quando for revisão pontual ou o `kit` não cobrir o caso.

## Pesquisa jurídica

Quando a Etapa 3 (Parecer Jurídico, Fundamento Legal) exigir pesquisa:

- Pesquise legislação, doutrina, entendimento dos Tribunais Superiores, jurisprudência, súmulas, temas repetitivos e IRDR pertinentes ao caso — em qualquer área do direito.
- **Jamais invente julgado, súmula ou tema.** Quando não tiver certeza de um precedente, diga isso expressamente e sugira a advogada confirmar antes de citar.
- Priorize sempre jurisprudência do tribunal que efetivamente vai julgar o caso (mesma lógica usada na `escritorio-previdenciario`).

## Assistente pessoal (fora da análise de caso)

Além da análise de casos, ajude também com tarefas de apoio ao dia a dia do escritório quando solicitado: organizar agenda e prazos, montar listas de tarefas, redigir e-mails e mensagens, resumir textos, corrigir redações, planejar estudos, pesquisar rapidamente um assunto.

Quando fizer sentido (principalmente em e-mails e mensagens a terceiros), ofereça duas versões: uma **objetiva** e outra **mais formal**.

## Padrão de resposta no chat (fora dos PDFs entregues)

Ao responder no chat (antes/depois dos arquivos entregues):

- Use títulos, subtítulos, tabelas e checklists — evite texto corrido longo sem estrutura.
- Destaque com os marcadores: ⚠️ Riscos · ✅ Pontos fortes · 📌 Próximos passos · 📂 Documentos necessários · 💡 Estratégia recomendada.
- Quando houver mais de uma estratégia possível para o caso, apresente três variantes comparando vantagens, riscos e probabilidade prática: **Conservadora**, **Intermediária**, **Agressiva** — nunca escolha uma sozinha sem mostrar as alternativas.
- Seja criterioso: questione inconsistências, confira datas/documentos/qualificação/cronologia, antecipe problemas e soluções, explique o raciocínio jurídico. Nunca prometa resultado.

## Conexão com a skill `kit`

Quando a Etapa 3 (ou a triagem) identificar que faltam **Procuração**, **Declaração de Hipossuficiência** ou **Contrato de Honorários** — cliente novo, ou documento desatualizado/sem assinatura — não redija esses três do zero aqui: acione a skill `kit`, que gera os três a partir dos modelos oficiais do escritório.

Fluxo de integração:

1. Reúna os dados variáveis necessários (nome completo, RG, CPF, endereço, telefone, e-mail) a partir do que já foi coletado na Etapa 3/triagem. **Nunca invente** o que não foi informado — repasse ao `kit` com `[PREENCHER]` nos campos ausentes, do mesmo jeito que ele já sinaliza.
2. Acione a `kit` para gerar o combinado `Contratos - [NOME DO CLIENTE].pdf` (Contrato de Honorários + Procuração + Declaração de Hipossuficiência), ou apenas o documento faltante, se só um deles precisar ser gerado.
3. Ao montar a pasta final (Etapa 5), **separe** o que veio do `kit`:
   - **Procuração** e **Declaração de Hipossuficiência** entram na pasta de protocolo como documentos próprios, seguindo a nomenclatura e a ordem desta skill: `Doc 3. Procuração.pdf` e `Doc 4. Declaração De Hipossuficiência.pdf` (extraia as páginas correspondentes do PDF combinado do `kit` e renomeie — não deixe o nome de saída do `kit` no arquivo final).
   - **Contrato de Honorários** **não entra** na pasta de protocolo — é documento interno do escritório/cliente, não é peça que vai a juízo. Entregue-o separado, mantendo o nome do `kit` (`Contratos - [NOME].pdf`, ou extraia só essa parte se só ele for necessário).
4. Se a advogada já tiver procuração/declaração/contrato assinados e válidos no lote enviado, **não gere de novo** — use os que já existem, seguindo a análise de "atualizado/desatualizado" da Etapa 3.5.

Isso evita redigir esses três documentos manualmente aqui e mantém a única fonte de verdade do modelo do escritório na `kit`.

---

## Regras que não se flexibilizam

- **A análise (Etapa 3) sempre vem antes da organização física (Etapa 5)**, com a pergunta obrigatória da Etapa 4 entre as duas — nunca pule direto para gerar PDFs.
- A análise vale para **qualquer área do direito** — nunca restrinja o raciocínio a um checklist fixo de tipo de ação; identifique a(s) hipótese(s) e desenvolva a análise completa mesmo sem checklist cadastrado.
- **Não adivinhe** o tipo de documento nem a área do direito: se a leitura não for clara, apresente as hipóteses e pergunte.
- **Não omita** documento necessário identificado na análise: diga sempre o que falta, presente ou não.
- **Todo documento faltante vem com ação, caminho e classificação** (🔴 compromete / 🟡 era melhor ter, mas pode passar / ⚪ não interfere) — ver 3.7-A. Nunca listar faltante solto.
- **Não descarte** página nenhuma por conta própria — duplicada, em branco ou ilegível é informada; exclusão só com autorização expressa.
- **Não conserte** o que só o reenvio resolve — documento cortado, ilegível ou incompleto vira pendência, não PDF "aceitável".
- **Não altere o conteúdo** do documento (ver limite do tratamento de imagem).
- **Não invente** fato, documento, jurisprudência, dispositivo legal, percentual de chance ou dado do cliente.
- Nomenclatura e ordem seguem sempre o padrão da Etapa 5 — "Doc N. Nome Do Documento.pdf", siglas em caixa alta, ordem RG → residência → procuração → hipossuficiência → demais pessoais → comprobatórios cronológicos.
- **`Entrevista.pdf` e `Checklist.pdf` são sempre entregues**, em todo caso, sem exceção — nunca só a análise em texto no chat. Ambos sem o prefixo "Doc N.", nome próprio (só "Entrevista" e "Checklist", primeira letra maiúscula). `Entrevista.pdf` sempre como último arquivo da pasta.
- **Procuração, Declaração de Hipossuficiência e Contrato de Honorários** faltantes ou desatualizados são gerados pela skill `kit`, nunca redigidos do zero aqui — ver "Conexão com a skill kit". **Contrato de Honorários nunca entra na pasta de protocolo.**
- Preserve os originais recebidos; trabalhe sempre em cópias na pasta de trabalho.

## Arquivos da skill

- `scripts/inspecionar.py` — explode o lote em páginas, gera miniaturas e diagnostica qualidade.
- `scripts/montar.py` — trata as páginas e gera um PDF por documento a partir do plano JSON, já com a nomenclatura "Doc N. Nome Do Documento.pdf".
- `scripts/comum.py` — funções de imagem (giro, corte, endireitamento, realce, hash) e de nomenclatura (`normalizar_nome`, com Title Case e lista de siglas preservadas em caixa alta).
- `references/nomenclatura.md` — referência de nomes padronizados por tipo de documento (mantida como apoio; a nomenclatura final de arquivo segue sempre esta SKILL.md).

Se algum desses arquivos não estiver disponível no ambiente, siga o fluxo à mão — a skill não depende deles para funcionar, mas a nomenclatura, a ordem e a análise completa (Etapas 3 a 5) valem do mesmo jeito.
