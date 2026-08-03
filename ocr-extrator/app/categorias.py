"""Categorias de processo e o checklist de documentos de cada uma.

Fonte: `docs/CHECK LIST ACIDENTE DO TRABALHO 31.07.26.docx`, fornecido pelo
escritório. No documento original os obrigatórios estão em vermelho (#EE0000);
aqui isso virou o campo `obrigatorio`.

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


CATEGORIAS: dict[str, Categoria] = {
    ACIDENTE_TRABALHO_CORREIOS.codigo: ACIDENTE_TRABALHO_CORREIOS,
}


def listar() -> list[Categoria]:
    return list(CATEGORIAS.values())


def obter(codigo: str) -> Categoria | None:
    return CATEGORIAS.get(codigo)
