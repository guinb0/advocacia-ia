"""Códigos de readiness do agente traduzidos para quem lê a tela.

O agente responde em código estável (`FACT_MISSING:PERSON.CPF`) de propósito: código não
muda de texto entre versões e serve para o programa decidir. Quem precisa de frase é o
advogado — e "o caso não está pronto" sem dizer o quê é a pior resposta possível, porque
não indica o que fazer em seguida.

Um código desconhecido não é escondido: aparece como está. Preferimos a tela mostrar
`FACT_MISSING:PERSON.PIS` a mostrar "há uma pendência" e deixar o escritório adivinhando.
"""

from __future__ import annotations

__all__ = ["explicar", "explicar_todos"]

#: Tipo de fato no vocabulário do escritório. Mesmo mapa do painel de fatos do dossiê.
_FATOS: dict[str, str] = {
    "PERSON.NAME": "o nome do cliente",
    "PERSON.CPF": "o CPF do cliente",
    "PERSON.RG": "o RG do cliente",
    "PERSON.PIS": "o PIS/PASEP",
    "PERSON.BIRTH_DATE": "a data de nascimento",
    "PERSON.ADDRESS": "o endereço do cliente",
    "EMPLOYMENT.RELATIONSHIP": "o vínculo de emprego",
    "EMPLOYMENT.ADMISSION_DATE": "a data de admissão",
    "EMPLOYMENT.TERMINATION_DATE": "a data de saída",
    "EMPLOYMENT.MONTHLY_SALARY": "o salário",
    "EMPLOYMENT.WORK_SCHEDULE": "a jornada",
    "EMPLOYMENT.LEAVE": "o afastamento",
    "SOCIAL_SECURITY.INSS_BENEFIT": "o benefício do INSS",
}

_CAMPOS_DA_PARTE: dict[str, str] = {
    "name": "o nome",
    "document": "o CPF/CNPJ",
}


def explicar(codigo: str) -> str:
    """Uma frase que diz o que fazer, a partir do código do agente."""
    prefixo, _, resto = codigo.partition(":")

    if prefixo == "CASE_NOT_CLASSIFIED":
        return "O caso ainda não foi classificado. Rode a análise antes de pedir a peça."
    if prefixo == "FACT_MISSING":
        return f"Falta {_fato(resto)}: nenhum documento entregou esse dado."
    if prefixo == "FACT_ONLY_ALLEGED":
        return (
            f"Só o relato do cliente sustenta {_fato(resto)}. Junte o documento que comprova "
            "— a peça não afirma o que ninguém conferiu."
        )
    if prefixo == "FACT_UNUSABLE":
        return f"{_fato(resto).capitalize()} está superado ou foi rejeitado — reveja os fatos."
    if prefixo == "PARTIES_MISSING":
        return "O caso não tem partes cadastradas."
    if prefixo == "PARTY_FIELD_MISSING":
        campo = _CAMPOS_DA_PARTE.get(resto, resto)
        return (
            f"Uma das partes está sem {campo}. Envie o documento que traz esse dado "
            "ou complete a qualificação."
        )
    if prefixo == "CHECKLIST_BLOCKING":
        return f"O checklist tem uma pendência indispensável em aberto ({resto})."
    if prefixo == "CONTRADICTION_OPEN":
        return (
            "Há divergência relevante entre as fontes ainda em aberto. "
            "Decida no painel de divergências antes de gerar a peça."
        )
    return codigo


def explicar_todos(codigos: list[str] | tuple[str, ...]) -> list[str]:
    """Mantém a ordem e não repete: dois fatos faltando são duas linhas, não uma lista."""
    vistos: list[str] = []
    for codigo in codigos:
        frase = explicar(codigo)
        if frase not in vistos:
            vistos.append(frase)
    return vistos


def _fato(tipo: str) -> str:
    return _FATOS.get(tipo, f"o dado {tipo}")
