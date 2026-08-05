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

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ItemChecklist:
    codigo: str
    numero: int
    nome: str
    obrigatorio: bool
    tipo_ocr: str | None = None
    observacao: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


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
        ItemChecklist("DOC.08", 8, "CNIS", False),
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
        ItemChecklist("DOC.08", 8, "CNIS", True),
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
        ItemChecklist("DOC.08", 8, "CNIS", True),
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
        ItemChecklist("DOC.19", 19, "Extrato CNIS (histórico previdenciário)", False),
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


CATEGORIAS: dict[str, Categoria] = {
    ACIDENTE_TRABALHO_CORREIOS.codigo: ACIDENTE_TRABALHO_CORREIOS,
    ACIDENTE_TRABALHO_GERAL.codigo: ACIDENTE_TRABALHO_GERAL,
    DOENCA_OCUPACIONAL.codigo: DOENCA_OCUPACIONAL,
    ASSALTO_CARTEIRO.codigo: ASSALTO_CARTEIRO,
    AUXILIO_ACIDENTE.codigo: AUXILIO_ACIDENTE,
}


def listar() -> list[Categoria]:
    return list(CATEGORIAS.values())


def obter(codigo: str) -> Categoria | None:
    return CATEGORIAS.get(codigo)
