"""Tradução do checklist do escritório para o vocabulário jurídico do agente.

Os dois lados nomeiam a mesma pasta de papéis de formas diferentes, e por bons motivos: o
Acervo numera o que o cliente precisa entregar (`DOC.09 — CAT`), porque é isso que vai no
e-mail e no portal; o agente nomeia o que o playbook exige (`DOCUMENT.CAT`), porque é isso
que decide se a peça pode ser escrita.

Sem esta tabela, o caso ficava com dezesseis pendências indispensáveis abertas **para
sempre**: o classificador de imagem do OCR reconhece nove tipos (RG, CPF, CTPS…), e CAT,
CNIS, PPP, ASO e laudo pericial não estão entre eles. A petição nunca era liberada mesmo com
todos os papéis entregues — o sistema simplesmente não tinha como saber que chegaram.

A tabela é escrita à mão e por categoria de propósito. "Laudos médicos" e "laudo pericial
particular" parecem a mesma coisa e valem coisas diferentes no processo; deixar um
casamento aproximado por semelhança de texto daria por satisfeito um requisito que não foi
atendido — que é exatamente o erro que o checklist existe para impedir.

Item sem correspondência (procuração, declaração de hipossuficiência, fotos, testemunhas)
fica de fora: são documentos do escritório, não exigências do playbook.
"""

from __future__ import annotations

__all__ = ["kind_do_item"]

#: `(categoria, código do item)` → código do vocabulário de `legal/`.
_MAPA: dict[str, dict[str, str]] = {
    "doenca_ocupacional": {
        "DOC.03": "DOCUMENT.ID",
        "DOC.04": "DOCUMENT.CPF",
        "DOC.05": "DOCUMENT.PROOF_OF_ADDRESS",
        "DOC.06": "DOCUMENT.CTPS",
        "DOC.07": "DOCUMENT.PAYSLIP",
        "DOC.08": "DOCUMENT.CNIS",
        "DOC.09": "DOCUMENT.CAT",
        "DOC.14": "DOCUMENT.MEDICAL_REPORT",
        "DOC.15": "DOCUMENT.MEDICAL_CERTIFICATE",
        "DOC.16": "DOCUMENT.IMAGING_EXAM",
        "DOC.17": "DOCUMENT.IMAGING_REPORT",
        # O laudo com CID é o relatório médico que sustenta o diagnóstico.
        "DOC.19": "DOCUMENT.MEDICAL_REPORT",
        "DOC.21": "DOCUMENT.MEDICAL_CHART",
        "DOC.22": "DOCUMENT.PRIVATE_EXPERT_REPORT",
        "DOC.23": "DOCUMENT.INSS_DECISION",
        "DOC.24": "DOCUMENT.INSS_DECISION",
        "DOC.27": "DOCUMENT.INSS_EXPERT_REPORT",
        "DOC.28": "DOCUMENT.INSS_ADMINISTRATIVE_FILE",
        "DOC.29": "DOCUMENT.PPP",
        "DOC.30": "DOCUMENT.ASO",
        # PCMSO e PGR/LTCAT são os programas de saúde e risco da empresa.
        "DOC.31": "DOCUMENT.OCCUPATIONAL_PROGRAM",
        "DOC.32": "DOCUMENT.OCCUPATIONAL_PROGRAM",
    },
    # Espelha `legal/checklists/labor/acidente_trabalho_correios.yaml` do agente (o
    # `document_kind` de cada item), tirando DOC.01 e DOC.02 pela mesma razão das
    # outras duas categorias: o playbook (`legal/playbooks/labor/acidente_trabalho_
    # correios.yaml`, `required_documents`) não exige procuração nem declaração de
    # hipossuficiência — são documentos do escritório, não exigência da peça.
    "acidente_trabalho_correios": {
        "DOC.03": "DOCUMENT.ID",
        "DOC.04": "DOCUMENT.CPF",
        "DOC.05": "DOCUMENT.PROOF_OF_ADDRESS",
        "DOC.06": "DOCUMENT.CTPS",
        "DOC.07": "DOCUMENT.PAYSLIP",
        "DOC.08": "DOCUMENT.CNIS",
        "DOC.09": "DOCUMENT.PERSONNEL_RECORD",
        "DOC.10": "DOCUMENT.CAT",
        "DOC.11": "DOCUMENT.POLICE_REPORT",
        "DOC.12": "DOCUMENT.EMERGENCY_CARE_RECORD",
        "DOC.13": "DOCUMENT.MEDICAL_CERTIFICATE",
        "DOC.14": "DOCUMENT.MEDICAL_REPORT",
        "DOC.15": "DOCUMENT.MEDICAL_FOLLOW_UP",
        "DOC.16": "DOCUMENT.IMAGING_EXAM",
        "DOC.17": "DOCUMENT.IMAGING_REPORT",
        "DOC.18": "DOCUMENT.IMAGING_EXAM",
        "DOC.19": "DOCUMENT.IMAGING_REPORT",
        "DOC.20": "DOCUMENT.PRESCRIPTION",
        "DOC.21": "DOCUMENT.TREATMENT_RECORD",
        "DOC.22": "DOCUMENT.TREATMENT_RECORD",
        "DOC.23": "DOCUMENT.INSS_DECISION",
        "DOC.24": "DOCUMENT.INSS_GRANT_LETTER",
        "DOC.25": "DOCUMENT.INSS_BENEFIT_EXTENSION",
        "DOC.26": "DOCUMENT.INSS_EXPERT_REPORT",
        "DOC.27": "DOCUMENT.INSS_ADMINISTRATIVE_FILE",
        "DOC.28": "DOCUMENT.ASO",
        "DOC.29": "DOCUMENT.PRIVATE_EXPERT_REPORT",
        "DOC.30": "DOCUMENT.ACCIDENT_SCENE_MEDIA",
        "DOC.32": "DOCUMENT.PPP",
        "DOC.33": "DOCUMENT.OCCUPATIONAL_PROGRAM",
    },
    "acidente_trabalho_geral": {
        "DOC.03": "DOCUMENT.ID",
        "DOC.04": "DOCUMENT.CPF",
        "DOC.05": "DOCUMENT.PROOF_OF_ADDRESS",
        "DOC.06": "DOCUMENT.CTPS",
        "DOC.07": "DOCUMENT.PAYSLIP",
        "DOC.08": "DOCUMENT.CNIS",
        "DOC.10": "DOCUMENT.CAT",
        "DOC.12": "DOCUMENT.MEDICAL_CHART",
        "DOC.13": "DOCUMENT.MEDICAL_CERTIFICATE",
        "DOC.14": "DOCUMENT.MEDICAL_REPORT",
        "DOC.15": "DOCUMENT.MEDICAL_REPORT",
        "DOC.16": "DOCUMENT.IMAGING_EXAM",
        "DOC.17": "DOCUMENT.IMAGING_REPORT",
        "DOC.20": "DOCUMENT.INSS_DECISION",
        "DOC.21": "DOCUMENT.INSS_DECISION",
        "DOC.23": "DOCUMENT.INSS_EXPERT_REPORT",
        "DOC.24": "DOCUMENT.INSS_ADMINISTRATIVE_FILE",
        "DOC.25": "DOCUMENT.ASO",
        "DOC.26": "DOCUMENT.PPP",
        "DOC.27": "DOCUMENT.OCCUPATIONAL_PROGRAM",
    },
}


def kind_do_item(categoria: str, codigo: str) -> str | None:
    """O código jurídico do item entregue, ou `None` quando ele não é exigência do playbook."""
    return _MAPA.get(categoria, {}).get(codigo)
