# Nomenclatura padrão

Consulte antes de nomear qualquer arquivo. O nome do arquivo é o que o servidor
lê no protocolo: ele diz o que o documento **é**, não o que se pretende provar
com ele.

**Todo nome de arquivo final vai em CAIXA ALTA** (prefixo `DOCN_` incluído),
com a extensão `.pdf` em minúscula: `DOC1_RG.pdf`,
`DOC7_COMPROVANTE_DE_RESIDENCIA.pdf`. As tabelas abaixo mostram o nome-base do
documento (sem o prefixo `DOCN_`, que é acrescentado na Etapa 5 conforme a
ordem de juntada) — todos já em caixa alta.

## Sumário

1. Regras de formação do nome
2. Documentos pessoais e de representação
3. Trabalhista
4. Previdenciário
5. Médicos e periciais
6. Cível
7. Ordem de organização da pasta
8. Pontos de atenção por área

---

## 1. Regras de formação do nome

- O nome final vai em **caixa alta**: `Comprovante de Residência` →
  `COMPROVANTE_DE_RESIDENCIA.pdf`. No plano JSON (`montar.py`), o campo
  `"nome"` pode ser escrito normalmente (com acentos e espaços) — o script
  normaliza e converte para caixa alta automaticamente.
- Sem acentos, sem espaços (viram `_`), sem barras, sem `nº`.
- **Nada de numeração de origem** (`IMG_2024`, `SCAN01`, `WHATSAPP IMAGE`).
- **Várias vias do mesmo tipo**: acrescente a data no formato ISO ao final —
  `ATESTADO_MEDICO_2024-03-11.pdf`, `ATESTADO_MEDICO_2024-05-02.pdf`. Sem data
  legível, use ordinal: `ATESTADO_MEDICO_1.pdf`, `ATESTADO_MEDICO_2.pdf`, e
  registre a dúvida na entrega.
- **Duplicidade total** (mesma página, mesmo conteúdo): mesmo nome do principal
  acrescido de `(DUPLICADO)` — `RG_(DUPLICADO).pdf`; havendo mais,
  `RG_(DUPLICADO_2).pdf`. Nunca excluir sem autorização expressa.
- **Documento de terceiro** no mesmo lote: acrescente o titular —
  `RG_DEPENDENTE_JOAO.pdf`, `CERTIDAO_NASCIMENTO_FILHA.pdf`.
- **Frente e verso** não geram sufixo: são páginas 1 e 2 do mesmo PDF.

## 2. Documentos pessoais e de representação

| Documento | Nome do arquivo |
|---|---|
| Procuração ad judicia | `PROCURACAO` |
| Substabelecimento | `SUBSTABELECIMENTO` |
| Declaração de hipossuficiência | `DECLARACAO_DE_HIPOSSUFICIENCIA` |
| Contrato de honorários | `CONTRATO_DE_HONORARIOS` |
| RG / CIN | `RG` |
| CPF | `CPF` |
| CNH (quando usada como identidade) | `CNH` |
| Certidão de nascimento | `CERTIDAO_DE_NASCIMENTO` |
| Certidão de casamento | `CERTIDAO_DE_CASAMENTO` |
| Certidão de óbito | `CERTIDAO_DE_OBITO` |
| Comprovante de residência | `COMPROVANTE_DE_RESIDENCIA` |
| Comprovante bancário / dados para depósito | `DADOS_BANCARIOS` |
| Declaração de união estável | `DECLARACAO_DE_UNIAO_ESTAVEL` |

## 3. Trabalhista

| Documento | Nome do arquivo |
|---|---|
| CTPS (páginas de identificação e contrato) | `CTPS` |
| Cartão PIS/PASEP | `PIS` |
| Contrato de trabalho | `CONTRATO_DE_TRABALHO` |
| Contracheques / holerites | `CONTRACHEQUE_AAAA-MM` |
| Cartões de ponto | `CARTOES_DE_PONTO_AAAA-MM` |
| TRCT / termo de rescisão | `TRCT` |
| Aviso prévio | `AVISO_PREVIO` |
| Extrato do FGTS | `EXTRATO_FGTS` |
| Guias de seguro-desemprego | `SEGURO_DESEMPREGO` |
| ACT / CCT | `CCT_AAAA-AAAA` ou `ACT_AAAA-AAAA` |
| Ficha de registro de empregado | `FICHA_DE_REGISTRO` |
| Ficha de evolução funcional | `FICHA_DE_EVOLUCAO_FUNCIONAL` |
| CAT | `CAT` |
| PPP | `PPP` |
| PCMSO | `PCMSO` |
| PGR / PPRA | `PGR` |
| ASO (admissional, periódico, demissional) | `ASO_ADMISSIONAL`, `ASO_PERIODICO`, `ASO_DEMISSIONAL` |
| Comprovante de entrega de EPI | `FICHA_DE_EPI` |
| E-mails, mensagens, prints | `MENSAGENS_AAAA-MM` |
| Boletim de ocorrência | `BOLETIM_DE_OCORRENCIA` |

## 4. Previdenciário

| Documento | Nome do arquivo |
|---|---|
| CNIS | `CNIS` |
| Carta de concessão com memória de cálculo | `CARTA_DE_CONCESSAO` |
| Comunicação de decisão do INSS | `COMUNICACAO_DE_DECISAO_INSS` |
| Indeferimento | `INDEFERIMENTO_INSS` |
| Prorrogação de benefício | `PRORROGACAO_DE_BENEFICIO` |
| Extrato de pagamento de benefício | `EXTRATO_DE_BENEFICIO` |
| Laudo SABI / perícia administrativa | `LAUDO_SABI` |
| Processo administrativo integral | `PROCESSO_ADMINISTRATIVO_INSS` |
| Requerimento (protocolo Meu INSS) | `REQUERIMENTO_INSS` |
| Senha / protocolo de agendamento | `PROTOCOLO_INSS` |

## 5. Médicos e periciais

| Documento | Nome do arquivo |
|---|---|
| Atestado médico | `ATESTADO_MEDICO_AAAA-MM-DD` |
| Laudo médico | `LAUDO_MEDICO_AAAA-MM-DD` |
| Relatório médico | `RELATORIO_MEDICO_AAAA-MM-DD` |
| Receituário | `RECEITUARIO_AAAA-MM-DD` |
| Exame de imagem — o exame | `RAIO_X_AAAA-MM-DD`, `RESSONANCIA_MAGNETICA_AAAA-MM-DD`, `TOMOGRAFIA_AAAA-MM-DD`, `ULTRASSONOGRAFIA_AAAA-MM-DD` |
| Exame de imagem — o laudo | `LAUDO_RAIO_X_AAAA-MM-DD`, `LAUDO_RESSONANCIA_AAAA-MM-DD` |
| Atendimento de emergência / prontuário | `ATENDIMENTO_DE_EMERGENCIA_AAAA-MM-DD` |
| Fisioterapia | `ATENDIMENTOS_FISIOTERAPICOS` |
| Psicologia / psiquiatria | `ATENDIMENTOS_PSICOLOGICOS`, `ATENDIMENTOS_PSIQUIATRICOS` |
| Laudo pericial | `LAUDO_PERICIAL_AAAA-MM-DD` |
| Fotos | `FOTOS_DO_LOCAL_DO_ACIDENTE`, `FOTOS_DO_RECLAMANTE` |

**O exame e o laudo do exame são documentos distintos** — dois PDFs, sempre.

## 6. Cível

| Documento | Nome do arquivo |
|---|---|
| Contrato | `CONTRATO_<OBJETO>` |
| Nota fiscal | `NOTA_FISCAL_AAAA-MM-DD` |
| Orçamento | `ORCAMENTO_<FORNECEDOR>` |
| Comprovante de pagamento | `COMPROVANTE_DE_PAGAMENTO_AAAA-MM-DD` |
| Extrato bancário | `EXTRATO_BANCARIO_AAAA-MM` |
| Negativação (SPC/Serasa) | `EXTRATO_DE_NEGATIVACAO` |
| Notificação extrajudicial | `NOTIFICACAO_EXTRAJUDICIAL` |
| Protocolo de reclamação (SAC, Procon, consumidor.gov) | `RECLAMACAO_<ORGAO>` |
| Laudo de vistoria | `LAUDO_DE_VISTORIA` |

## 7. Ordem de organização da pasta

**Todo arquivo leva o prefixo sequencial `DOCN_`** da ordem de juntada, em
caixa alta — `DOC1_PROCURACAO.pdf`, `DOC7_ATESTADO_MEDICO_2025-05-14.pdf` —,
começando em `DOC1` e sem pular número. A numeração do checklist (`DOC. 10`)
fica **só no relatório**, nunca no nome do arquivo. Duplicado herda o número
do principal: `DOC3_RG_(DUPLICADO).pdf`.

A ordem que gera a numeração:

1. **Documentos pessoais / de qualificação**, nesta sequência: procuração,
   substabelecimento, hipossuficiência e contrato → RG, CPF, comprovante de
   residência, certidões → CTPS, PIS, contracheques, rescisão → CNIS.
2. **Todo o resto em ordem cronológica**, do mais antigo para o mais recente,
   pela data do próprio documento (fato, emissão, atendimento, exame, decisão):
   documentos da empresa (PPP, PCMSO, ASO, EPI, CAT), administrativo do INSS,
   médicos, provas do fato (BO, fotos, mensagens).
3. **Sem data identificável**: no fim, sinalizado na entrega.

Havendo mais de uma via do mesmo tipo, a data entra no nome do arquivo.

## 8. Pontos de atenção por área

**Trabalhista**
- CTPS: só as páginas úteis (identificação, contrato, alterações). Página em
  branco não entra sem autorização.
- Contracheques e cartões de ponto: um PDF por competência, nunca um único PDF
  com o período todo, salvo pedido expresso.
- CCT/ACT: confira a vigência no cabeçalho antes de nomear pelo biênio.

**Previdenciário**
- CNIS costuma vir com vínculos truncados: confira se todas as páginas vieram e
  se a última linha não foi cortada.
- Carta de concessão sem a memória de cálculo é **documento incompleto** —
  vira pendência, não vira arquivo "aceitável".
- Processo administrativo integral: é um documento só, com todas as páginas na
  ordem original do INSS.

**Cível**
- Documento assinado: nunca aplique corte que ampute assinatura, rubrica de
  margem ou reconhecimento de firma. Use `corte: bordas`.
- Nota fiscal e comprovante de pagamento são documentos distintos.

**Todas as áreas**
- Carimbo, marca d'água, rasura e verso translúcido **permanecem**. Sua
  supressão compromete a integridade da prova.
- Documento com data ilegível: não invente a data no nome do arquivo —
  registre como pendência e pergunte.
