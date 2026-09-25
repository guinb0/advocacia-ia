"""A conferência da petição contra os autos: o que a peça afirma e os documentos não sustentam.

Os trechos defeituosos abaixo são REAIS — saíram da geração do caso-gabarito de
18/09/2026 (acidente típico, estabilidade do art. 118). Cada um é um jeito diferente de
a peça mentir sem que ninguém percebesse: documento que não existe, parcela criada para
fechar a soma, pedido sem valor, tópico contra o próprio cliente, súmula de memória.

Sem banco, sem rede, sem modelo.

    .venv\\Scripts\\python.exe -m tests.test_conferencia_peticao
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import conferencia_peticao as C  # noqa: E402
from app import peticao_local  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


ANEXOS = [
    {"arquivo": "IMG_20250110_101233.jpg", "tipo": "RG (Carteira de Identidade)", "campos": [],
     "texto": "CARTEIRA DE IDENTIDADE REGISTRO GERAL: 34.567.890-1 NOME: RAFAEL MOREIRA LOPES CPF: 529.982.247-25"},
    {"arquivo": "WhatsApp Image 2025-01-10 at 10.15.22.jpeg", "tipo": "", "campos": [],
     "texto": "CARTEIRA DE TRABALHO E PREVIDÊNCIA SOCIAL Data de admissão: 03 de fevereiro de 2019 "
              "30/03/2024 - afastamento B91 - retorno em 16/09/2024 CARTEIRA DE TRABALHO Nº 7654321 SÉRIE 0045-SP "
              "PIS/PASEP: 128.45678.91-2"},
    {"arquivo": "scan_0003.jpg", "tipo": "Recibo de pagamento de salário", "campos": [],
     "texto": "RECIBO DE PAGAMENTO DE SALÁRIO SALÁRIO BASE 2.380,00"},
    {"arquivo": "documento_4.jpg", "tipo": "CAT (Comunicação de Acidente de Trabalho)", "campos": [],
     "texto": "COMUNICAÇÃO DE ACIDENTE DE TRABALHO Nº da CAT: 2024.0314.5567-8/01 Data do acidente: 14/03/2024"},
    {"arquivo": "IMG_4411.jpg", "tipo": "", "campos": [],
     "texto": "CARTA DE CONCESSÃO NB 645.123.987-0 DIB 30/03/2024 DCB 15/09/2024"},
    {"arquivo": "IMG_4412.jpg", "tipo": "TRCT", "campos": [],
     "texto": "TERMO DE RESCISÃO Data de afastamento: 10/12/2024 Homologação em 18/12/2024"},
    {"arquivo": "conta_luz.jpg", "tipo": "", "campos": [],
     "texto": "CPFL PAULISTA - COMPANHIA PAULISTA DE FORÇA E LUZ CONTA DE ENERGIA ELÉTRICA"},
    {"arquivo": "atestado.jpg", "tipo": "Atestado médico", "campos": [], "texto": "ATESTADO MÉDICO CID S62.0"},
]


#: Completude (seção ausente/curta) é aviso da skill, não é o assunto destes testes.
_COMPLETUDE = {"MISSING_SECTION", "FACTS_TOO_SHORT", "GROUNDS_TOO_SHORT"}


def conferir(secoes, fontes_):
    return [v for v in C.conferir(secoes, fontes_) if v.codigo not in _COMPLETUDE]


def fontes(material: str = "") -> C.Fontes:
    return C.Fontes(
        anexos=ANEXOS,
        numerados=[a["arquivo"] for a in ANEXOS],
        entrevista="me mandaram embora em dezembro",
        cadastro="RAFAEL MOREIRA LOPES 529.982.247-25 Rua das Acácias, 145 13050-120",
        material=material,
    )


def codigos(secoes: dict[str, str], material: str = "") -> list[str]:
    return [v.codigo for v in conferir([{"code": k, "content": t} for k, t in secoes.items()], fontes(material))]


# ------------------------------------------------------ 1. documento e anexo

print("\n1. Documento citado e anexo alegado")

checar(
    "DOCUMENTO_INEXISTENTE" in codigos({"PRELIMINARY": "conforme declaração anexa (Documento 09 – declaração)"}),
    "«Documento 09» num caso com oito documentos é barrado",
)
checar(
    "DOCUMENTO_INEXISTENTE" not in codigos({"FACTS": "A CAT foi emitida em 16/03/2024 (Documento 04 – CAT)."}),
    "e o Documento 04, que existe, passa",
)
checar(
    "ANEXO_INEXISTENTE" in codigos({"PRELIMINARY": "O autor é hipossuficiente, conforme declaração de hipossuficiência anexa."}),
    "«declaração de hipossuficiência anexa» sem declaração no caso é barrada",
)
lista = codigos({"EVIDENCE": "juntada de todos os documentos anexos (CTPS, CAT, atestado médico, carta de "
                             "concessão do INSS, TRCT, holerite, conta de luz, RG, declaração de hipossuficiência)"})
checar(lista.count("ANEXO_INEXISTENTE") == 1, "na lista de anexos, só a declaração é barrada (sinônimos reconhecem os outros oito)")
checar(
    "ANEXO_INEXISTENTE" not in codigos({"EVIDENCE": "Requer a juntada dos documentos anexos."}),
    "«documentos anexos» genérico não é acusação de nada",
)

# ------------------------------------------------------------- 2. números

print("\n2. Números e datas")

checar(
    not codigos({"HEADING": "CPF nº 529.982.247-25, CTPS nº 7654321, série 0045-SP, PIS/PASEP nº 128.45678.91-2"}),
    "os números que estão nos documentos passam",
)
checar(
    "NUMERO_SEM_ORIGEM" in codigos({"HEADING": "PIS/PASEP nº 190.12345.67-8"}),
    "um PIS que não está em lugar nenhum é barrado",
)
checar(
    "NUMERO_SEM_ORIGEM" not in codigos({"LEGAL_GROUNDS": "O art. 118 da Lei nº 8.213/91 e a Resolução CNJ nº 345/2020."}),
    "número de norma não é número de documento do cliente",
)
checar(
    "NUMERO_SEM_ORIGEM" not in codigos({"CLAIMS": "a) Indenização no valor de R$ 28.560,00."}),
    "valor em dinheiro não é conferido como número de documento",
)
checar(
    "DATA_SEM_ORIGEM" not in codigos({"LEGAL_GROUNDS": "estabilidade de 15/09/2024 a 15/09/2025"}),
    "15/09/2025 é derivada da DCB (15/09/2024 + 12 meses) e passa",
)
checar(
    "DATA_SEM_ORIGEM" in codigos({"FACTS": "O autor foi admitido em 07/11/2017."}),
    "uma data de admissão inventada é barrada",
)

# --------------------------------------------------------------- 3. valores

print("\n3. Pedidos e valor da causa")

CLAIMS = """Ante o exposto, requer:

a) **Indenização substitutiva** do período de estabilidade, totalizando R$ 28.560,00;

b) **Indenização por danos morais** no valor de R$ 50.000,00;

d) **Horas extras** excedentes à 8ª diária, com reflexos, a serem apuradas em liquidação;

e) **Diferenças salariais por acúmulo de função** no percentual de 30%, a serem apuradas em liquidação;

g) **Honorários advocatícios** nos termos do art. 791-A da CLT, no percentual de 15%;

h) **Juros e correção monetária** na forma da lei;

i) **Gratuidade da justiça**."""
resultado = codigos({"CLAIMS": CLAIMS, "VALUE": "Dá-se à causa o valor de R$ 150.000,00."})
checar(resultado.count("PEDIDO_SEM_VALOR") == 2, "horas extras e acúmulo «a apurar em liquidação» são barrados (art. 840, § 1º)")
checar("VALOR_DA_CAUSA_INCOERENTE" in resultado, "R$ 150.000,00 de causa para R$ 78.560,00 de pedidos é barrado")
checar(
    not codigos({"CLAIMS": "a) Danos morais no valor de R$ 50.000,00;\n\nb) Honorários de 15%.",
                 "VALUE": "Dá-se à causa o valor de R$ 50.000,00."}),
    "honorários sem valor próprio e causa igual à soma passam",
)

# Segunda rodada do caso-gabarito: todos os pedidos com valor, mas «estimado» sem conta.
SEGUNDA = """1. **Indenização por estabilidade acidentária**: salários do período de 10/12/2024 a 15/09/2025, correspondente a 9 meses e 5 dias, no valor de R$ 2.380,00 mensais, totalizando R$ 21.896,67.

2. **Horas extras**: horas excedentes à 8ª diária e 44ª semanal, com adicional de 50%, considerando a jornada das 06h00 às 19h30. Valor estimado: R$ 15.000,00.

3. **Intervalo intrajornada**: período suprimido do intervalo de 1 hora, com adicional de 50%. Valor estimado: R$ 5.000,00.

5. **Dano moral**: indenização no valor de R$ 30.000,00.

9. **FGTS**: Valor estimado: R$ 1.500,00, com base no salário de R$ 2.380,00 e no percentual de 8% ao mês, projetado sobre os 9 meses do período."""
segunda = conferir([{"code": "CLAIMS", "content": SEGUNDA},
                      {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 73.396,67."}], fontes())
sem_criterio = [v.trecho[:25] for v in segunda if v.codigo == "VALOR_SEM_CRITERIO"]
checar(len(sem_criterio) == 2 and all("Horas" in t or "Intervalo" in t for t in sem_criterio),
       "«valor estimado» sem conta (horas extras, intervalo) é barrado; mencionar «horas» e «50%» não é critério")
checar("VALOR_DA_CAUSA_INCOERENTE" not in [v.codigo for v in segunda],
       "a soma usa o valor ANUNCIADO do item (FGTS R$ 1.500), não a base de cálculo (salário R$ 2.380)")
checar(
    not [v for v in conferir([{"code": "CLAIMS", "content": "a) Horas extras: 2 h/dia × 22 dias × 22 meses × R$ 16,23. Valor estimado: R$ 15.711,00."}], fontes())
         if v.codigo == "VALOR_SEM_CRITERIO"],
    "valor com a conta escrita passa",
)

# Terceira rodada: o modelo tentou burlar a regra — conta dentro do [PENDENTE], R$ 0,00
# em pedido sem conteúdo econômico, custas como pedido.
TERCEIRA = """a) A concessão dos benefícios da justiça gratuita, pedido sem repercussão econômica, estimado em R$ 0,00;

b) A citação da Reclamada para apresentar defesa, estimado em R$ 0,00;

f) Pensão mensal no percentual de 50%, valor estimado de R$ 1.190,00 mensais, assim calculado: 50% × R$ 2.380,00 = R$ 1.190,00 mensais;

g) Horas extras, 2 horas por dia útil, no valor estimado de R$ 15.000,00, assim calculado: [PENDENTE: confirmar critério — nº de dias úteis × 2h × valor-hora × 1,5];

k) A condenação da Reclamada ao pagamento das custas processuais, no valor estimado de R$ 2.018,80, assim calculado: 2% sobre o valor da causa."""
terceira = conferir([{"code": "CLAIMS", "content": TERCEIRA},
                       {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 16.190,00."}], fontes())
sem_criterio = [v.trecho[:2] for v in terceira if v.codigo == "VALOR_SEM_CRITERIO"]
checar(sem_criterio == ["g)"], "conta escrita DENTRO do [PENDENTE] não é conta (só as horas extras são barradas)")
checar("VALOR_DA_CAUSA_INCOERENTE" not in [v.codigo for v in terceira],
       "gratuidade/citação com R$ 0,00 e custas ficam fora da soma; pensão soma o valor anunciado, não o salário")

# Quarta rodada: a conta veio escrita — o pedido é o resultado depois do «=».
QUARTA = """a) Indenização do período de estabilidade, no valor estimado de R$ 2.380,00 × 9 meses = R$ 21.420,00;

h) Recolhimento das contribuições previdenciárias, no valor estimado de R$ 2.380,00 × 20% × 13 meses = R$ 6.188,00."""
quarta = [v.codigo for v in conferir([{"code": "CLAIMS", "content": QUARTA},
                                         {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 21.420,00."}], fontes())]
checar(not quarta, "soma o resultado da conta (R$ 21.420), não a base (R$ 2.380); recolhimento previdenciário não é crédito do autor")

# ------------------------------------------------- 4. tópico contra o cliente

print("\n4. Tópico que conclui contra o próprio cliente")

GROUNDS = """**I – DA ESTABILIDADE ACIDENTÁRIA**

A dispensa é nula. O autor faz jus à indenização substitutiva.

**VII – DA MULTA DO ART. 477 DA CLT**

A homologação ocorreu dentro do prazo de 10 dias, não havendo atraso. Não se aplica a multa do art. 477, § 8º, da CLT.

**VIII – DA MULTA DO ART. 467 DA CLT**

As verbas rescisórias foram pagas, não havendo parcelas incontroversas em atraso. Não se aplica a multa do art. 467 da CLT."""
checar(codigos({"LEGAL_GROUNDS": GROUNDS}).count("TOPICO_CONTRA_O_CLIENTE") == 2, "«não se aplica a multa» dos arts. 477 e 467 é barrado")
checar(
    "TOPICO_CONTRA_O_CLIENTE" in codigos({"LEGAL_GROUNDS": "**VII – DA MULTA DO ART. 477 DA CLT**\n\nO art. 477, § 8º, da CLT"
                                          " estabelece multa quando o empregador não efetuar o pagamento das verbas no prazo."
                                          " No caso, não há elementos que indiquem atraso. Assim, não se formula pedido de multa."}),
    "«não se formula pedido» é barrado mesmo com «pagamento» na explicação da lei (escapou na 2ª rodada)",
)
checar(
    "TOPICO_CONTRA_O_CLIENTE" not in codigos({"LEGAL_GROUNDS": "**II – DA PRESCRIÇÃO**\n\nNão se aplica a prescrição bienal, pois a ação é ajuizada no prazo; requer o afastamento da prejudicial."}),
    "tópico que diz «não se aplica» A FAVOR do cliente, e pede, passa",
)

# ------------------------------------------------------------- 5. citações

print("\n5. Súmula de memória")

texto = "nos termos da Súmula 378, II, do TST. A Súmula 6, VI, do TST autoriza o acúmulo."
vs = conferir([{"code": "LEGAL_GROUNDS", "content": texto}], fontes())
nao_verificadas = [v for v in vs if v.codigo == "CITACAO_NAO_VERIFICADA"]
checar(len(nao_verificadas) == 2, "as duas súmulas sem fonte no material são apontadas")
checar(all(not v.bloqueia for v in nao_verificadas), "como aviso — sem catálogo, ninguém pode dizer que estão erradas")
marcadas = C.marcar_citacoes_nao_verificadas([{"code": "LEGAL_GROUNDS", "content": texto}], vs)[0]["content"]
checar(marcadas.count(C.MARCA_NAO_VERIFICADA) == 2, "e cada uma sai carimbada NA PEÇA (o .docx leva o aviso)")
checar("Súmula 378, II, do TST " + C.MARCA_NAO_VERIFICADA in marcadas, "o carimbo vem logo depois da citação completa")
de_novo = C.marcar_citacoes_nao_verificadas([{"code": "LEGAL_GROUNDS", "content": marcadas}], vs)[0]["content"]
checar(de_novo == marcadas, "carimbar de novo não duplica o carimbo")
checar(
    not [v for v in conferir([{"code": "LEGAL_GROUNDS", "content": texto}],
                               fontes("=== LEGISLAÇÃO === Súmula nº 378 do TST: ... Súmula 6 ..."))
         if v.codigo == "CITACAO_NAO_VERIFICADA"],
    "súmula que está no material do acervo passa",
)

# -------------------------------------------------- 6. o formato da tela

print("\n6. O que a tela recebe")

achado = C.como_achados(conferir([{"code": "PRELIMINARY", "content": "(Documento 09 – declaração)"}], fontes()))[0]
checar({"severity", "category", "section", "message", "detail"} <= set(achado), "achado tem os campos de `AchadoRevisao`")
checar(achado["severity"] == "BLOCKING", "documento inexistente retém a peça")
legado = peticao_local._achado_legivel({"critic": "consistency_check", "severity": "info", "code": "PENDING_INFORMATION"})
checar(legado["category"] == "PENDING_INFORMATION" and legado["message"], "achado antigo, sem `category`, ganha category e mensagem (a tela não quebra)")

dados: dict = {}
peticao_local._aplicar_conferencia(dados, [{"code": "FACTS", "content": "x" * 400}], conferir(
    [{"code": "PRELIMINARY", "content": "(Documento 09 – declaração)"}], fontes()))
checar(dados["blocking_findings"] == 1 and dados["review"]["blocking"] == 1, "a peça com violação sai RETIDA (blocking_findings)")

# -------------------------------------- 7. a rodada de correção automática

print("\n7. A rodada de correção")

original = [{"code": "PRELIMINARY", "content": "conforme declaração de hipossuficiência anexa (Documento 09)."}]
corrigida = [{"code": "PRELIMINARY", "content": "[PENDENTE: juntar declaração de hipossuficiência assinada]."}]
pedidos: list[str] = []


def revisor_que_corrige(caso_id, secoes, critica):
    pedidos.append(critica)
    return corrigida, {"alterou": True}


peticao_local._fontes_da_conferencia = lambda caso_id, **k: fontes()  # type: ignore[assignment]
peticao_local._revisar_secoes_via_llm = revisor_que_corrige  # type: ignore[assignment]
secoes, restantes, registro = peticao_local._conferir_contra_os_autos("caso-1", original)
checar(secoes == corrigida and not [v for v in restantes if v.bloqueia], "violação corrigida pelo revisor não retém a peça")
checar(registro["violacoes_iniciais"] and registro["rodada_de_correcao"] and not registro["violacoes_restantes"],
       "e o trace registra o que havia e que foi corrigido")
checar("Documento 08 — atestado.jpg" in pedidos[0] and "Documento 09" in pedidos[0],
       "a crítica ao revisor diz o defeito E lista os únicos documentos que existem")


def revisor_fora_do_ar(caso_id, secoes, critica):
    raise peticao_local.ErroPeticao("O modelo não respondeu — tente de novo.")


peticao_local._revisar_secoes_via_llm = revisor_fora_do_ar  # type: ignore[assignment]
secoes, restantes, registro = peticao_local._conferir_contra_os_autos("caso-1", original)
checar(secoes == original and registro["violacoes_restantes"], "revisor fora do ar: a peça sai como veio, COM as violações — nunca em silêncio")

duas = [original[0], {"code": "FACTS", "content": "O autor foi admitido em 03 de fevereiro de 2019."}]
peticao_local._revisar_secoes_via_llm = revisor_que_corrige  # devolve SÓ a PRELIMINARY  # type: ignore[assignment]
secoes, _, _ = peticao_local._conferir_contra_os_autos("caso-1", duas)
checar([s["code"] for s in secoes] == ["PRELIMINARY", "FACTS"] and secoes[1] == duas[1],
       "seção que o revisor não devolveu continua na peça (a correção não derruba seção)")

pedidos.clear()
peticao_local._revisar_secoes_via_llm = revisor_que_corrige  # type: ignore[assignment]
peticao_local._conferir_contra_os_autos("caso-1", original, corrigir=False)
checar(not pedidos, "edição do advogado (corrigir=False) não é reescrita por cima")

# -------------------------------------------------- 8. o que o prompt manda

print("\n8. O contrato de redação")

checar("ou que você possa verificar" not in peticao_local.CONTRATO_DE_REDACAO, "a brecha «ou que você possa verificar» saiu")
checar("Só cite o que está no material recebido" in peticao_local.CONTRATO_DE_REDACAO, "súmula só com fonte no material")
checar("[PENDENTE: <dado>]" in peticao_local.CONTRATO_DE_REDACAO, "documento ausente vira [PENDENTE: juntar ...]")
checar("PROIBIDO ajustar parcela" in peticao_local.peticao_skill_arquivos.carregar("", "", ""), "parcela para fechar a soma é proibida")
checar(peticao_local._avisos_de_insumo({"precedentes": False, "legislacao": True, "pecas_modelo": False, "orientacao_do_escritorio": True})[0].startswith("Gerada SEM os julgados"),
       "geração sem acervo vira aviso legível na peça")
checar(not peticao_local._avisos_de_insumo({"precedentes": True, "legislacao": True, "pecas_modelo": True, "orientacao_do_escritorio": True}),
       "e com tudo presente, nenhum aviso")


if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
