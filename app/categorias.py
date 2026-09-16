"""Categorias de processo e o checklist de documentos de cada uma.

Fontes: os arquivos de checklist em `docs/`, fornecidos pelo escritório, e os
checklists textuais recebidos para categorias sem `.docx`. Nos documentos
originais os obrigatórios estão em vermelho (#EE0000); aqui isso virou o campo
`obrigatorio`.

`tipo_ocr` liga o item do checklist ao classificador de `extractors.py`: quando
preenchido, o sistema consegue conferir sozinho se o arquivo enviado é mesmo o
documento pedido. `None` significa que ainda não há classificador para aquele
tipo — o documento é aceito, mas a conferência fica por conta do usuário.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

#: Código sentinela do documento que chegou SEM destino, à espera de triagem.
#:
#: Não pertence a checklist nenhum de propósito: é `itens_atendidos` vazio que o
#: mantém fora de todos os itens da tela, e este código serve só para a coluna
#: `item_codigo`, que é obrigatória no banco. Mora aqui, e não em
#: `app/roteamento.py`, porque `armazenamento` precisa dele e não pode importar
#: o roteamento sem fechar um ciclo.
ITEM_TRIAGEM = "TRIAGEM"


@dataclass(frozen=True)
class ItemChecklist:
    codigo: str
    numero: int
    nome: str
    obrigatorio: bool
    tipo_ocr: str | None = None
    observacao: str = ""
    #: Código do tipo no glossário (`app/tipos_documento.py`), quando o item não tem
    #: classificador. Com `tipo_ocr` preenchido o tipo já é ele — ver `tipo_documento`.
    tipo: str | None = None
    #: Item que não está no checklist do escritório: entrou porque alguém marcou este
    #: tipo de caso no glossário (ver `_com_itens_do_glossario`).
    do_glossario: bool = False

    @property
    def tipo_documento(self) -> str | None:
        """O tipo do glossário que este item pede.

        Os códigos do classificador são os mesmos do glossário, então um item com
        `tipo_ocr` não precisa repetir o tipo.
        """
        return self.tipo or self.tipo_ocr

    def to_dict(self) -> dict:
        dados = asdict(self)
        dados["tipo_documento"] = self.tipo_documento
        return dados


@dataclass(frozen=True)
class Categoria:
    codigo: str
    nome: str
    descricao: str
    itens: tuple[ItemChecklist, ...]

    @property
    def obrigatorios(self) -> tuple[ItemChecklist, ...]:
        return tuple(i for i in self.itens if i.obrigatorio)

    def to_dict(self) -> dict:
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "descricao": self.descricao,
            "total_documentos": len(self.itens),
            "total_obrigatorios": len(self.obrigatorios),
            "itens": [i.to_dict() for i in self.itens],
        }


ACIDENTE_TRABALHO_CORREIOS = Categoria(
    codigo="acidente_trabalho_correios",
    nome="Acidente do Trabalho (Correios)",
    descricao=(
        "Ação por acidente do trabalho contra os Correios. Os 14 documentos "
        "obrigatórios precisam ser entregues; os demais reforçam a instrução do caso."
    ),
    itens=(
        ItemChecklist("DOC.01", 1, "Procuração", True),
        ItemChecklist("DOC.02", 2, "Declaração de hipossuficiência", True),
        ItemChecklist("DOC.03", 3, "RG", True, tipo_ocr="rg"),
        ItemChecklist("DOC.04", 4, "CPF", True, tipo_ocr="cpf"),
        ItemChecklist("DOC.05", 5, "Comprovante de residência", True, tipo_ocr="comprovante_residencia"),
        ItemChecklist("DOC.06", 6, "CTPS e PIS", True, tipo_ocr="ctps"),
        ItemChecklist("DOC.07", 7, "Contracheque do último mês trabalhado", True),
        ItemChecklist("DOC.08", 8, "CNIS", False, tipo_ocr="cnis"),
        ItemChecklist("DOC.09", 9, "Ficha de evolução funcional", False),
        ItemChecklist("DOC.10", 10, "CAT (Comunicação de Acidente de Trabalho)", True),
        ItemChecklist("DOC.11", 11, "Boletim de ocorrência", False),
        ItemChecklist("DOC.12", 12, "Atendimento de emergência", False),
        ItemChecklist("DOC.13", 13, "Atestados médicos", True),
        ItemChecklist("DOC.14", 14, "Laudos médicos", True),
        ItemChecklist("DOC.15", 15, "Relatórios médicos", False),
        ItemChecklist("DOC.16", 16, "Raio X", False),
        ItemChecklist("DOC.17", 17, "Laudo médico do raio X", False),
        ItemChecklist("DOC.18", 18, "Ressonância magnética", False),
        ItemChecklist("DOC.19", 19, "Laudo médico da ressonância magnética", False),
        ItemChecklist("DOC.20", 20, "Receituário médico", False),
        ItemChecklist("DOC.21", 21, "Atendimentos fisioterápicos", False),
        ItemChecklist("DOC.22", 22, "Atendimentos psicológicos e psiquiátricos", False),
        ItemChecklist("DOC.23", 23, "Comunicação de decisão do INSS — concessão de benefício", True),
        ItemChecklist("DOC.24", 24, "Carta de concessão com memória de cálculo", True),
        ItemChecklist("DOC.25", 25, "Prorrogação de benefício do INSS", True),
        ItemChecklist("DOC.26", 26, "Laudos SABI/INSS", False),
        ItemChecklist("DOC.27", 27, "Processo integral do INSS", True),
        ItemChecklist("DOC.28", 28, "ASOs (Atestados de Saúde Ocupacional)", False),
        ItemChecklist("DOC.29", 29, "Laudo pericial atualizado", False),
        ItemChecklist("DOC.30", 30, "Fotos do local do acidente", False),
        ItemChecklist("DOC.31", 31, "Fotos do reclamante", False),
        ItemChecklist("DOC.32", 32, "PPP (Perfil Profissiográfico Previdenciário)", False),
        ItemChecklist("DOC.33", 33, "PCMSO", False),
    ),
)


ACIDENTE_TRABALHO_GERAL = Categoria(
    codigo="acidente_trabalho_geral",
    nome="Ações de Acidente de Trabalho Geral",
    descricao=(
        "Ação de acidente do trabalho para qualquer profissão. Os itens destacados "
        "como imprescindíveis no checklist do escritório são obrigatórios; os demais "
        "servem para reforçar a prova do caso quando existirem."
    ),
    itens=(
        ItemChecklist("DOC.01", 1, "Procuração", True),
        ItemChecklist("DOC.02", 2, "Declaração de hipossuficiência", True),
        ItemChecklist("DOC.03", 3, "RG", True, tipo_ocr="rg"),
        ItemChecklist("DOC.04", 4, "CPF", True, tipo_ocr="cpf"),
        ItemChecklist("DOC.05", 5, "Comprovante de residência", True, tipo_ocr="comprovante_residencia"),
        ItemChecklist("DOC.06", 6, "CTPS e PIS", True, tipo_ocr="ctps"),
        ItemChecklist("DOC.07", 7, "Contracheque do último mês trabalhado", True),
        ItemChecklist("DOC.08", 8, "CNIS", True, tipo_ocr="cnis"),
        ItemChecklist("DOC.09", 9, "Ficha funcional e de evolução funcional", True),
        ItemChecklist("DOC.10", 10, "CAT (Comunicação de Acidente de Trabalho)", True),
        ItemChecklist("DOC.11", 11, "Boletim de ocorrência, quando houver", False),
        ItemChecklist("DOC.12", 12, "Ficha de atendimento de emergência / pronto-socorro / UPA / hospital", True),
        ItemChecklist("DOC.13", 13, "Atestados médicos", True),
        ItemChecklist("DOC.14", 14, "Laudos médicos", True),
        ItemChecklist("DOC.15", 15, "Relatórios médicos", True),
        ItemChecklist("DOC.16", 16, "Exames de imagem (raio X, tomografia, ressonância, ultrassom etc.)", True),
        ItemChecklist("DOC.17", 17, "Laudos dos exames de imagem", True),
        ItemChecklist("DOC.18", 18, "Receituários médicos", False),
        ItemChecklist("DOC.19", 19, "Comprovantes de tratamento (fisioterapia, terapia ocupacional, psicologia, psiquiatria, fonoaudiologia e outros)", False),
        ItemChecklist("DOC.20", 20, "Comunicação de decisão do INSS (concessão, indeferimento, cessação ou prorrogação de benefício)", True),
        ItemChecklist("DOC.21", 21, "Carta de concessão com memória de cálculo", True),
        ItemChecklist("DOC.22", 22, "Histórico de benefícios", True),
        ItemChecklist("DOC.23", 23, "Laudos SABI do INSS e laudos periciais", True),
        ItemChecklist("DOC.24", 24, "Processo administrativo integral do INSS", True),
        ItemChecklist("DOC.25", 25, "ASOs (admissional, periódico, retorno ao trabalho, mudança de função e demissional)", True),
        ItemChecklist("DOC.26", 26, "PPP (Perfil Profissiográfico Previdenciário)", False),
        ItemChecklist("DOC.27", 27, "PCMSO, PGR, LTCAT, PPRA, mapas de risco e documentos aplicáveis", False),
        ItemChecklist("DOC.28", 28, "Fotos e vídeos do local do acidente, máquinas, ferramentas, veículos, posto de trabalho ou condições ambientais", False),
        ItemChecklist("DOC.29", 29, "Comprovantes de despesas médicas, farmacêuticas, hospitalares e de reabilitação", False),
        ItemChecklist("DOC.30", 30, "Documentos sobre jornada, escalas, ponto, excesso de labor, acúmulo de funções ou sobrecarga", False),
        ItemChecklist("DOC.31", 31, "Documentos sobre exposição a risco e agentes insalubres, perigosos, biológicos, químicos, físicos ou ergonômicos", False),
        ItemChecklist("DOC.32", 32, "Nomes, telefones e endereços de testemunhas", False),
        ItemChecklist("DOC.33", 33, "Contrato de trabalho, aditivos, regulamentos internos e normas empresariais aplicáveis", False),
        ItemChecklist("DOC.34", 34, "TRCT, chave de conectividade, extrato do FGTS e documentos rescisórios, se houver dispensa", False),
        ItemChecklist("DOC.35", 35, "Laudo pericial particular atualizado, quando houver", False),
    ),
)


DOENCA_OCUPACIONAL = Categoria(
    codigo="doenca_ocupacional",
    nome="Doença Ocupacional",
    descricao=(
        "Ação relacionada a doença causada ou agravada pelas condições de trabalho. "
        "Os documentos destacados como imprescindíveis no checklist do escritório "
        "são obrigatórios; os demais complementam a prova do vínculo, do nexo causal "
        "e dos danos sofridos."
    ),
    itens=(
        ItemChecklist("DOC.01", 1, "Procuração", True),
        ItemChecklist("DOC.02", 2, "Declaração de hipossuficiência", True),
        ItemChecklist("DOC.03", 3, "RG", True, tipo_ocr="rg"),
        ItemChecklist("DOC.04", 4, "CPF", True, tipo_ocr="cpf"),
        ItemChecklist(
            "DOC.05",
            5,
            "Comprovante de residência atualizado (conta de água, luz ou telefone)",
            True,
            tipo_ocr="comprovante_residencia",
        ),
        ItemChecklist(
            "DOC.06",
            6,
            "Carteira de Trabalho e Previdência Social – CTPS (física ou digital) e PIS",
            True,
            tipo_ocr="ctps",
        ),
        ItemChecklist(
            "DOC.07",
            7,
            "Contracheques (holerites) – último mês trabalhado e, se possível, os 3 a 6 meses anteriores",
            True,
        ),
        ItemChecklist("DOC.08", 8, "CNIS", True, tipo_ocr="cnis"),
        ItemChecklist("DOC.09", 9, "CAT – Comunicação de Acidente de Trabalho", True),
        ItemChecklist("DOC.10", 10, "Contrato de trabalho e aditivos (se houver)", False),
        ItemChecklist(
            "DOC.11",
            11,
            "Ficha de registro, ficha funcional, alterações de cargo, função e salário",
            False,
        ),
        ItemChecklist(
            "DOC.12",
            12,
            "Termo de Rescisão do Contrato de Trabalho – TRCT e comprovantes de pagamento das verbas rescisórias (se aplicável)",
            False,
        ),
        ItemChecklist("DOC.13", 13, "Extrato do FGTS e chave de conectividade", False),
        ItemChecklist(
            "DOC.14",
            14,
            "Relatórios médicos de acompanhamento e evolução clínica",
            False,
        ),
        ItemChecklist("DOC.15", 15, "Atestados médicos", True),
        ItemChecklist(
            "DOC.16",
            16,
            "Exames de imagem (raio X, tomografia, ressonância magnética, ultrassom), laboratoriais",
            True,
        ),
        ItemChecklist("DOC.17", 17, "Laudos dos exames de imagem e laboratoriais", True),
        ItemChecklist(
            "DOC.18",
            18,
            "Receituários médicos – comprovantes de medicamentos prescritos",
            False,
        ),
        ItemChecklist(
            "DOC.19",
            19,
            "Laudo médico detalhado, indicando o diagnóstico da doença com o Código Internacional de Doenças – CID e, se possível, a relação com as atividades laborais",
            True,
        ),
        ItemChecklist(
            "DOC.20",
            20,
            "Comprovantes de tratamento – fisioterapia, terapia ocupacional, psicologia, psiquiatria, fonoaudiologia, entre outros",
            False,
        ),
        ItemChecklist(
            "DOC.21",
            21,
            "Prontuários médicos – cópia do prontuário hospitalar ou da clínica onde realizou tratamentos, detalhando a evolução do quadro clínico e os procedimentos realizados",
            True,
        ),
        ItemChecklist("DOC.22", 22, "Laudo pericial particular atualizado", True),
        ItemChecklist("DOC.23", 23, "Comunicação de decisão do INSS", True),
        ItemChecklist("DOC.24", 24, "Carta de concessão com memória de cálculo", True),
        ItemChecklist(
            "DOC.25",
            25,
            "Prorrogação ou cessação de benefício do INSS",
            False,
        ),
        ItemChecklist(
            "DOC.26",
            26,
            "Histórico de benefícios e extratos previdenciários",
            True,
        ),
        ItemChecklist(
            "DOC.27",
            27,
            "Laudos periciais do INSS, inclusive laudos SABI",
            True,
        ),
        ItemChecklist("DOC.28", 28, "Processo administrativo integral do INSS", False),
        ItemChecklist(
            "DOC.29",
            29,
            "PPP – Perfil Profissiográfico Previdenciário",
            True,
        ),
        ItemChecklist(
            "DOC.30",
            30,
            "ASOs – admissional, periódico, mudança de função, retorno ao trabalho e demissional",
            True,
        ),
        ItemChecklist(
            "DOC.31",
            31,
            "PCMSO – Programa de Controle Médico de Saúde Ocupacional, incluindo relatórios anuais",
            True,
        ),
        ItemChecklist("DOC.32", 32, "PGR/LTCAT/PPRA", True),
        ItemChecklist(
            "DOC.33",
            33,
            "Controle de ponto, escalas de trabalho e registros de horas extras",
            False,
        ),
        ItemChecklist(
            "DOC.34",
            34,
            "Documentos que comprovem acúmulo de funções, sobrecarga, metas abusivas",
            False,
        ),
        ItemChecklist(
            "DOC.35",
            35,
            "Fotos e vídeos do posto de trabalho, máquinas, ferramentas ou ambiente, demonstrando condições inadequadas ou ausência de proteção",
            False,
        ),
        ItemChecklist(
            "DOC.36",
            36,
            "Nomes completos, telefones e endereços de testemunhas que presenciaram as condições de trabalho ou a evolução do quadro de saúde do reclamante",
            False,
        ),
        ItemChecklist(
            "DOC.37",
            37,
            "Recibos e notas fiscais – comprovantes de gastos com medicamentos, fisioterapia, consultas, exames e outros tratamentos relacionados à doença, para fins de reembolso ou dano material",
            False,
        ),
    ),
)


ASSALTO_CARTEIRO = Categoria(
    codigo="assalto_carteiro",
    nome="Assalto a Carteiro",
    descricao=(
        "Ação relacionada a assalto sofrido por carteiro durante o trabalho. "
        "Os documentos destacados como imprescindíveis no checklist do escritório "
        "são obrigatórios; os demais complementam a prova do fato, dos danos à saúde "
        "e dos reflexos previdenciários."
    ),
    itens=(
        ItemChecklist("DOC.01", 1, "Procuração", True),
        ItemChecklist("DOC.02", 2, "Declaração de hipossuficiência", True),
        ItemChecklist("DOC.03", 3, "RG", True, tipo_ocr="rg"),
        ItemChecklist("DOC.04", 4, "CPF", True, tipo_ocr="cpf"),
        ItemChecklist(
            "DOC.05",
            5,
            "Comprovante de residência",
            True,
            tipo_ocr="comprovante_residencia",
        ),
        ItemChecklist("DOC.06", 6, "Contracheque atual", True),
        ItemChecklist(
            "DOC.07",
            7,
            "Carteira de Trabalho (CTPS) e PIS",
            True,
            tipo_ocr="ctps",
        ),
        ItemChecklist(
            "DOC.08",
            8,
            "CAT – Comunicação de Acidente de Trabalho, caso tenha sido emitida",
            True,
        ),
        ItemChecklist("DOC.09", 9, "Boletim de ocorrência", True),
        ItemChecklist("DOC.10", 10, "Atestados médicos", False),
        ItemChecklist(
            "DOC.11",
            11,
            "Prontuário hospitalar/internação, caso tenha havido",
            False,
        ),
        ItemChecklist("DOC.12", 12, "Laudos médicos", True),
        ItemChecklist("DOC.13", 13, "Receitas médicas", False),
        ItemChecklist(
            "DOC.14",
            14,
            "Carta de concessão de benefício do INSS",
            True,
        ),
        ItemChecklist(
            "DOC.15",
            15,
            "Perícias médicas do INSS, caso tenha realizado mais de uma",
            False,
        ),
        ItemChecklist(
            "DOC.16",
            16,
            "Resultado das perícias médicas do INSS",
            False,
        ),
        # O checklist original não possui DOC.17; a numeração salta para DOC.18.
        ItemChecklist(
            "DOC.18",
            18,
            "Notas fiscais de medicamentos, tratamentos e demais despesas relacionadas",
            False,
        ),
        ItemChecklist("DOC.19", 19, "Extrato CNIS (histórico previdenciário)", False, tipo_ocr="cnis"),
        ItemChecklist("DOC.20", 20, "Manual da empresa", False),
    ),
)


AUXILIO_ACIDENTE = Categoria(
    codigo="auxilio_acidente",
    nome="Auxílio-Acidente",
    descricao=(
        "Pedido de auxílio-acidente. Documentos condicionais, como contracheque, "
        "prontuário e decisões ou perícias do INSS, devem ser enviados quando "
        "existirem no caso concreto."
    ),
    itens=(
        ItemChecklist(
            "DOC.01",
            1,
            "Documento de identificação (RG ou CNH; CPF, se necessário)",
            True,
            observacao=(
                "Envie RG ou CNH. Se o CPF não constar na CNH, envie também o CPF."
            ),
        ),
        ItemChecklist(
            "DOC.02",
            2,
            "Comprovante de residência atualizado",
            True,
            tipo_ocr="comprovante_residencia",
            observacao=(
                "Preferencialmente dos últimos 90 dias: conta de água, energia, "
                "internet ou telefone, boleto de condomínio ou outro documento que "
                "comprove o endereço."
            ),
        ),
        ItemChecklist(
            "DOC.03",
            3,
            "Último contracheque (se estiver trabalhando)",
            False,
            observacao="Caso esteja empregado, envie o contracheque mais recente.",
        ),
        ItemChecklist(
            "DOC.04",
            4,
            "Laudos e exames médicos relacionados à doença ou lesão",
            True,
            observacao=(
                "Envie todos os exames disponíveis, como radiografias (raio X), "
                "ressonância magnética, tomografia, ultrassonografia, "
                "eletroneuromiografia, exames laboratoriais e outros que comprovem "
                "a condição de saúde."
            ),
        ),
        ItemChecklist(
            "DOC.05",
            5,
            "Atestados e relatórios médicos",
            True,
            observacao=(
                "Envie todos os documentos médicos, especialmente os que informem "
                "diagnóstico e CID, início da doença, limitações, tratamentos, "
                "necessidade de afastamento, incapacidade profissional e tempo "
                "estimado de recuperação."
            ),
        ),
        ItemChecklist(
            "DOC.06",
            6,
            "Receitas médicas",
            False,
            observacao=(
                "Envie todas as receitas dos medicamentos utilizados, principalmente "
                "as mais recentes."
            ),
        ),
        ItemChecklist(
            "DOC.07",
            7,
            "Prontuário médico completo",
            False,
            observacao=(
                "Se houve atendimento em hospital, UPA, posto de saúde ou clínica, "
                "solicite ao local uma cópia completa do histórico de atendimentos."
            ),
        ),
        ItemChecklist(
            "DOC.08",
            8,
            "Processo administrativo completo do INSS",
            False,
            observacao=(
                "Se já houve pedido de benefício, acesse o benefício ou requerimento "
                "no Meu INSS e baixe todos os documentos disponíveis em PDF. Se não "
                "localizar, solicite uma cópia completa diretamente ao INSS."
            ),
        ),
        ItemChecklist(
            "DOC.09",
            9,
            "Carta de indeferimento do INSS (se o benefício foi negado)",
            False,
            observacao=(
                "Envie a carta que informa o motivo da negativa; ela pode ser baixada "
                "pelo Meu INSS."
            ),
        ),
        ItemChecklist(
            "DOC.10",
            10,
            "Extrato do CNIS",
            True,
            tipo_ocr="cnis",
            observacao=(
                "No Meu INSS, acesse “Extrato de Contribuição (CNIS)” e baixe o PDF "
                "com o histórico de vínculos, contribuições e remunerações."
            ),
        ),
        ItemChecklist(
            "DOC.11",
            11,
            "Laudo da perícia do INSS (se houver)",
            False,
            observacao=(
                "No Meu INSS, acesse o benefício ou requerimento, procure “Resultado "
                "da Perícia” ou “Documentos” e baixe o laudo. Se não encontrar, "
                "solicite uma cópia diretamente ao INSS."
            ),
        ),
    ),
)


# ------------------------------------------------ o tipo de cada item no glossário
#
# Um mapa por categoria, e não um `tipo=` em cada linha acima: os itens seguem
# conferidos contra o .docx do escritório (`tests/test_categorias.py`), e o vínculo
# com o glossário é outra decisão, que se revisa melhor lida de uma vez. Itens com
# `tipo_ocr` ficam de fora — o código do classificador já é o tipo.
#
# Vários itens podem apontar para o mesmo tipo (raio X e ressonância são exames de
# imagem). O contrário não: cada item pede um tipo só.


def _tipificar(categoria: Categoria, tipos: dict[str, str]) -> Categoria:
    """A mesma categoria, com o tipo do glossário em cada item."""
    sobrando = set(tipos) - {item.codigo for item in categoria.itens}
    if sobrando:
        raise ValueError(
            f"Itens inexistentes no mapa de tipos de {categoria.codigo}: {sorted(sobrando)}"
        )
    return replace(
        categoria,
        itens=tuple(
            replace(item, tipo=tipos.get(item.codigo, item.tipo)) for item in categoria.itens
        ),
    )


ACIDENTE_TRABALHO_CORREIOS = _tipificar(
    ACIDENTE_TRABALHO_CORREIOS,
    {
        "DOC.01": "procuracao",
        "DOC.02": "declaracao_hipossuficiencia",
        "DOC.07": "contracheque",
        "DOC.08": "cnis",
        "DOC.09": "ficha_funcional",
        "DOC.10": "cat",
        "DOC.11": "boletim_ocorrencia",
        "DOC.12": "atendimento_emergencia",
        "DOC.13": "atestado_medico",
        "DOC.14": "laudo_medico",
        "DOC.15": "relatorio_medico",
        "DOC.16": "exame_imagem",
        "DOC.17": "laudo_exame",
        "DOC.18": "exame_imagem",
        "DOC.19": "laudo_exame",
        "DOC.20": "receituario",
        "DOC.21": "comprovante_tratamento",
        "DOC.22": "comprovante_tratamento",
        "DOC.23": "decisao_inss",
        "DOC.24": "carta_concessao",
        "DOC.25": "decisao_inss",
        "DOC.26": "laudo_pericial_inss",
        "DOC.27": "processo_inss",
        "DOC.28": "aso",
        "DOC.29": "laudo_pericial_particular",
        "DOC.30": "fotos",
        "DOC.31": "fotos",
        "DOC.32": "ppp",
        "DOC.33": "programa_ocupacional",
    },
)

ACIDENTE_TRABALHO_GERAL = _tipificar(
    ACIDENTE_TRABALHO_GERAL,
    {
        "DOC.01": "procuracao",
        "DOC.02": "declaracao_hipossuficiencia",
        "DOC.07": "contracheque",
        "DOC.08": "cnis",
        "DOC.09": "ficha_funcional",
        "DOC.10": "cat",
        "DOC.11": "boletim_ocorrencia",
        "DOC.12": "atendimento_emergencia",
        "DOC.13": "atestado_medico",
        "DOC.14": "laudo_medico",
        "DOC.15": "relatorio_medico",
        "DOC.16": "exame_imagem",
        "DOC.17": "laudo_exame",
        "DOC.18": "receituario",
        "DOC.19": "comprovante_tratamento",
        "DOC.20": "decisao_inss",
        "DOC.21": "carta_concessao",
        "DOC.22": "historico_beneficios",
        "DOC.23": "laudo_pericial_inss",
        "DOC.24": "processo_inss",
        "DOC.25": "aso",
        "DOC.26": "ppp",
        "DOC.27": "programa_ocupacional",
        "DOC.28": "fotos",
        "DOC.29": "comprovante_despesas",
        "DOC.30": "controle_jornada",
        "DOC.31": "prova_condicoes_trabalho",
        "DOC.32": "testemunhas",
        "DOC.33": "contrato_trabalho",
        "DOC.34": "documentos_rescisorios",
        "DOC.35": "laudo_pericial_particular",
    },
)

DOENCA_OCUPACIONAL = _tipificar(
    DOENCA_OCUPACIONAL,
    {
        "DOC.01": "procuracao",
        "DOC.02": "declaracao_hipossuficiencia",
        "DOC.07": "contracheque",
        "DOC.08": "cnis",
        "DOC.09": "cat",
        "DOC.10": "contrato_trabalho",
        "DOC.11": "ficha_funcional",
        "DOC.12": "documentos_rescisorios",
        "DOC.13": "extrato_fgts",
        "DOC.14": "relatorio_medico",
        "DOC.15": "atestado_medico",
        "DOC.16": "exame_imagem",
        "DOC.17": "laudo_exame",
        "DOC.18": "receituario",
        "DOC.19": "laudo_medico",
        "DOC.20": "comprovante_tratamento",
        "DOC.21": "prontuario",
        "DOC.22": "laudo_pericial_particular",
        "DOC.23": "decisao_inss",
        "DOC.24": "carta_concessao",
        "DOC.25": "decisao_inss",
        "DOC.26": "historico_beneficios",
        "DOC.27": "laudo_pericial_inss",
        "DOC.28": "processo_inss",
        "DOC.29": "ppp",
        "DOC.30": "aso",
        "DOC.31": "programa_ocupacional",
        "DOC.32": "programa_ocupacional",
        "DOC.33": "controle_jornada",
        "DOC.34": "prova_condicoes_trabalho",
        "DOC.35": "fotos",
        "DOC.36": "testemunhas",
        "DOC.37": "comprovante_despesas",
    },
)

ASSALTO_CARTEIRO = _tipificar(
    ASSALTO_CARTEIRO,
    {
        "DOC.01": "procuracao",
        "DOC.02": "declaracao_hipossuficiencia",
        "DOC.06": "contracheque",
        "DOC.08": "cat",
        "DOC.09": "boletim_ocorrencia",
        "DOC.10": "atestado_medico",
        "DOC.11": "prontuario",
        "DOC.12": "laudo_medico",
        "DOC.13": "receituario",
        "DOC.14": "carta_concessao",
        "DOC.15": "laudo_pericial_inss",
        "DOC.16": "laudo_pericial_inss",
        "DOC.18": "comprovante_despesas",
        "DOC.19": "cnis",
        "DOC.20": "regulamento_empresa",
    },
)

AUXILIO_ACIDENTE = _tipificar(
    AUXILIO_ACIDENTE,
    {
        # "RG ou CNH": o item pede identidade, e é como RG que ele entra no glossário.
        # Uma CNH enviada aqui continua reconhecida como CNH pelo classificador.
        "DOC.01": "rg",
        "DOC.03": "contracheque",
        "DOC.04": "laudo_medico",
        "DOC.05": "atestado_medico",
        "DOC.06": "receituario",
        "DOC.07": "prontuario",
        "DOC.08": "processo_inss",
        "DOC.09": "decisao_inss",
        "DOC.10": "cnis",
        "DOC.11": "laudo_pericial_inss",
    },
)


CATEGORIAS: dict[str, Categoria] = {
    ACIDENTE_TRABALHO_CORREIOS.codigo: ACIDENTE_TRABALHO_CORREIOS,
    ACIDENTE_TRABALHO_GERAL.codigo: ACIDENTE_TRABALHO_GERAL,
    DOENCA_OCUPACIONAL.codigo: DOENCA_OCUPACIONAL,
    ASSALTO_CARTEIRO.codigo: ASSALTO_CARTEIRO,
    AUXILIO_ACIDENTE.codigo: AUXILIO_ACIDENTE,
}

# O escritório tem casos reais nestas quatro categorias. `ASSALTO_CARTEIRO`
# continua no catálogo para abrir eventual caso histórico, mas não aparece na
# criação de novos casos enquanto não houver nenhum caso dessa ação.
_CATEGORIAS_ATIVAS = (
    ACIDENTE_TRABALHO_CORREIOS.codigo,
    ACIDENTE_TRABALHO_GERAL.codigo,
    DOENCA_OCUPACIONAL.codigo,
    AUXILIO_ACIDENTE.codigo,
)


# -------------------------------------------- itens acrescentados pelo glossário
#
# O checklist acima é o do escritório, conferido contra o .docx. Um tipo criado depois
# no glossário não estava em nenhum deles e, por isso, não era pedido em caso nenhum:
# quem o cria marca em que tipos de caso ele deve aparecer, e `obter` e `listar` o
# acrescentam ao fim do checklist. `CATEGORIAS` continua só com o fixo — é contra ele
# que os testes conferem o .docx.

#: Prefixo do código dos itens acrescentados. O código do item fica gravado em cada
#: entrega (`entregas.item_codigo`); derivá-lo do código do tipo, que não muda, é o que
#: mantém o documento no mesmo item quando outros tipos são marcados ou desmarcados.
PREFIXO_ITEM_GLOSSARIO = "GLOS."


def codigo_item_do_glossario(tipo_codigo: str) -> str:
    return f"{PREFIXO_ITEM_GLOSSARIO}{tipo_codigo}"


def _com_itens_do_glossario(categoria: Categoria) -> Categoria:
    """A categoria com os tipos marcados no glossário no fim do checklist.

    Entram como opcionais: marcar um tipo de caso não pode, sozinho, deixar incompletos
    os casos que já estavam completos. Tipo que o checklist fixo já pede não ganha um
    segundo item — as entregas se dividiriam entre os dois.
    """
    # Import tardio: `tipos_documento` importa este módulo.
    from . import tipos_documento

    marcados = tipos_documento.tipos_marcados(categoria.codigo)
    if not marcados:
        return categoria
    ja_pedidos = {item.tipo_documento for item in categoria.itens}
    numero = max((item.numero for item in categoria.itens), default=0)
    novos: list[ItemChecklist] = []
    for tipo in marcados:
        if tipo["codigo"] in ja_pedidos:
            continue
        ja_pedidos.add(tipo["codigo"])
        numero += 1
        novos.append(
            ItemChecklist(
                codigo_item_do_glossario(tipo["codigo"]),
                numero,
                tipo["nome"],
                False,
                observacao=tipo["descricao"],
                tipo=tipo["codigo"],
                do_glossario=True,
            )
        )
    return replace(categoria, itens=categoria.itens + tuple(novos)) if novos else categoria


def listar() -> list[Categoria]:
    return [_com_itens_do_glossario(CATEGORIAS[codigo]) for codigo in _CATEGORIAS_ATIVAS]


def obter(codigo: str) -> Categoria | None:
    categoria = CATEGORIAS.get(codigo)
    return _com_itens_do_glossario(categoria) if categoria else None
