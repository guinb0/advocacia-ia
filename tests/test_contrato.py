"""Preenchimento do contrato de honorários sobre o modelo oficial.

O que pode dar errado aqui é mais grave que uma tela feia: um contrato com
cláusula alterada, um campo trocado na qualificação, ou um .docx que o Word
recusa depois de gerado. Os três estão cobertos.

Rodar: .venv\\Scripts\\python.exe -m tests.test_contrato
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

from app import contrato

W = contrato.W

ENTREVISTA = {
    "nome": "Maria Aparecida da Silva",
    "nacionalidade": "brasileira",
    "estado_civil": "Casado(a)",
    "profissao": "Carteira",
    "cpf": "111.444.777-35",
    "rg": "1234567",
    "rg_orgao": "SSP",
    "rg_uf": "PA",
    "endereco": "Avenida Governador José Malcher, nº 100, Nazaré, Belém/PA, CEP 66055-240",
    "telefone": "(91) 98888-7777",
    "email": "maria@exemplo.com",
    "municipio": "Belém",
    "uf": "PA",
}


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def paragrafos_do_docx(dados: bytes) -> list[str]:
    partes = []
    with zipfile.ZipFile(io.BytesIO(dados)) as zf:
        for nome in sorted(zf.namelist()):
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nome):
                raiz = ET.fromstring(zf.read(nome))
                for p in raiz.iter(f"{W}p"):
                    partes.append("".join(t.text or "" for t in p.iter(f"{W}t")))
    return partes


def texto_do_docx(dados: bytes) -> str:
    """Todo o texto do documento, cabeçalhos e rodapés inclusive."""
    partes = []
    with zipfile.ZipFile(io.BytesIO(dados)) as zf:
        for nome in zf.namelist():
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nome):
                raiz = ET.fromstring(zf.read(nome))
                partes.append("".join(t.text or "" for t in raiz.iter(f"{W}t")))
    return "\n".join(partes)


def modelo_falso() -> bytes:
    """Um .docx mínimo com o marcador PARTIDO entre nós de texto.

    É o caso que o modelo real não tem hoje e vai ter no dia em que alguém
    editar o arquivo no Word: uma correção ortográfica no meio de "[CPF]" basta
    para o Word repartir o texto em dois nós, e um `str.replace` ingênuo passa
    reto sem trocar nada — o contrato sairia com o colchete no lugar do CPF.
    """
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Contratante: </w:t></w:r>"
        "<w:r><w:t>[nome da </w:t></w:r><w:r><w:t>pessoa]</w:t></w:r>"
        "<w:r><w:t>, inscrito no CPF </w:t></w:r>"
        "<w:r><w:t>[CP</w:t></w:r><w:r><w:t>F]</w:t></w:r>"
        "<w:r><w:t>, e-mail [e-mail].</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w") as zf:
        zf.writestr("word/document.xml", doc)
        zf.writestr("[Content_Types].xml", "<Types/>")
    return destino.getvalue()


def main_teste() -> int:
    falhas = 0
    tmp = contrato.BASE / "tmp"
    tmp.mkdir(exist_ok=True)

    # --- marcador partido entre nós --------------------------------------
    caminho_falso = tmp / "modelo-de-teste.docx"
    caminho_falso.write_bytes(modelo_falso())

    # --- barreira de identificação --------------------------------------
    # O bloqueio acontece antes de abrir/preencher o modelo. Assim não existe
    # caminho alternativo (download, dossiê ou assinatura) que produza um DOCX
    # sem os dois dados que identificam inequivocamente o contratante.
    invalidos = (
        ({"CPF": "111.444.777-35"}, "nome ausente"),
        ({"nome da pessoa": "Maria", "CPF": "111.444.777-35"}, "nome incompleto"),
        ({"nome da pessoa": "A B", "CPF": "111.444.777-35"}, "nome só com iniciais"),
        ({"nome da pessoa": "M. S.", "CPF": "111.444.777-35"}, "iniciais pontuadas"),
        ({"nome da pessoa": "Maria de", "CPF": "111.444.777-35"}, "nome sem sobrenome"),
        ({"nome da pessoa": "Maria 123A", "CPF": "111.444.777-35"}, "nome com algarismos"),
        ({"nome da pessoa": ["Maria", "Silva"], "CPF": "111.444.777-35"}, "nome em lista"),
        ({"nome da pessoa": "Maria Aparecida"}, "CPF ausente"),
        ({"nome da pessoa": "Maria Aparecida", "CPF": "111.111.111-11"}, "CPF inválido"),
        ({"nome da pessoa": "Maria Aparecida", "CPF": "111x444x777x35"}, "CPF com letras"),
        ({"nome da pessoa": "Maria Aparecida", "CPF": ["111444", "77735"]}, "CPF em lista"),
    )
    for valores_invalidos, descricao in invalidos:
        try:
            contrato.preencher(valores_invalidos, caminho_falso)
        except contrato.DadosObrigatoriosContrato as exc:
            falhas += not checar(
                "Contrato não gerado" in str(exc),
                f"{descricao} bloqueia a geração antes de criar o arquivo",
            )
        else:
            falhas += not checar(False, f"{descricao} bloqueia a geração")

    for nome_valido in ("Ana Li", "Maria da Silva", "Ana D'Ávila", "Maria Souza-Silva"):
        try:
            contrato.normalizar_respostas({"nome": nome_valido, "cpf": "11144477735"})
        except contrato.DadosObrigatoriosContrato:
            falhas += not checar(False, f"nome completo legítimo é aceito ({nome_valido})")
        else:
            falhas += not checar(True, f"nome completo legítimo é aceito ({nome_valido})")

    cpf_largo = contrato.normalizar_respostas(
        {"nome": "Maria da Silva", "cpf": "１１１４４４７７７３５"}
    )["cpf"]
    falhas += not checar(
        cpf_largo == "111.444.777-35",
        "dígitos de largura cheia são normalizados para o CPF ASCII canônico",
    )

    docx, faltando = contrato.preencher(
        {"nome da pessoa": "  Maria   Aparecida  ", "CPF": "11144477735"}, caminho_falso
    )
    texto = texto_do_docx(docx)

    falhas += not checar(
        "Contratante: Maria Aparecida, inscrito no CPF 111.444.777-35" in texto,
        f"marcador repartido entre nós é preenchido ({texto.strip()!r})",
    )
    falhas += not checar(
        "[e-mail]" in texto,
        "campo sem resposta continua à vista — em branco passaria despercebido",
    )
    falhas += not checar(faltando == ["e mail"], f"o que faltou é informado ({faltando})")

    docx_literal, faltando_literal = contrato.preencher(
        {
            "nome da pessoa": "Maria Aparecida",
            "CPF": "111.444.777-35",
            "e-mail": "[e-mail]",
        },
        caminho_falso,
    )
    falhas += not checar(
        texto_do_docx(docx_literal).count("[e-mail]") == 1 and not faltando_literal,
        "texto parecido com marcador é inserido uma vez, sem reprocessamento",
    )

    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        corpo = zf.read("word/document.xml").decode()
    # `<w:b />` com espaço: é assim que o ElementTree fecha elemento vazio.
    falhas += not checar(
        re.search(r"<w:b\s*/>", corpo) is not None,
        "a formatação em volta do marcador é preservada (negrito segue lá)",
    )

    # --- o modelo oficial -------------------------------------------------
    # Ele não está no repositório: traz tabela de honorários, CNPJ e as OAB do
    # escritório, e o repositório é público (ver .gitignore). Sem o arquivo, o
    # que dá para testar é o mecanismo de preenchimento — que é o que acabou de
    # rodar acima, com um .docx sintético. O resto avisa e para por aqui.
    try:
        modelo = contrato.caminho_modelo()
        achou_modelo = True
    except contrato.ErroContrato as exc:
        print(f"\n  (pulado) {exc}")
        print("  Ponha o CONTRATO*.docx do escritório em docs/ para cobrir o resto.")
        print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
        caminho_falso.unlink(missing_ok=True)
        return 1 if falhas else 0

    original = texto_do_docx(modelo.read_bytes())
    docx, faltando = contrato.gerar(ENTREVISTA, quando=date(2026, 8, 12))
    saida = texto_do_docx(docx)

    falhas += not checar(achou_modelo, f"modelo oficial encontrado ({modelo.name})")

    sem_cidade_no_endereco = {
        **ENTREVISTA,
        "endereco": "Avenida Principal, nº 100, Centro, CEP 66055-240",
    }
    falhas += not checar(
        contrato.valores_da_entrevista(sem_cidade_no_endereco)["Município"] == "Belém/PA",
        "município e UF da identificação entram mesmo sem cidade no endereço",
    )

    for esperado, onde in (
        ("Maria Aparecida da Silva", "nome"),
        ("111.444.777-35", "CPF"),
        ("1234567", "número do RG"),
        ("SSP/PA", "órgão expedidor"),
        ("maria@exemplo.com", "e-mail"),
        ("12 de agosto de 2026", "data por extenso"),
        ("Belém/PA", "município deduzido do endereço"),
    ):
        falhas += not checar(esperado in saida, f"{onde} entra no contrato")

    falhas += not checar(
        "[nome da pessoa]" not in saida and "[CPF]" not in saida,
        "nenhum marcador preenchido sobra no documento",
    )

    falhas += not checar(
        "RG nº 1234567, expedido por SSP/PA" in saida,
        "número e órgão do RG entram cada um no seu lugar",
    )

    # No bloco de assinatura o CPF é rótulo solto, sem colchete: preenchendo só
    # os marcadores, o contrato saía com "CPF:" vazio embaixo da assinatura —
    # que é exatamente onde o cartório e a parte contrária olham.
    falhas += not checar(
        "CPF: 111.444.777-35" in saida,
        "o CPF entra também na linha de assinatura, onde o modelo só tem o rótulo",
    )
    falhas += not checar(
        saida.count("111.444.777-35") >= 2,
        "o CPF aparece nos dois lugares: qualificação e assinatura",
    )

    # Rede de segurança: tudo digitado na caixa do número mesmo assim se separa.
    juntos = {**ENTREVISTA, "rg": "1234567 SSP/PA", "rg_orgao": "", "rg_uf": ""}
    saida_juntos = texto_do_docx(contrato.gerar(juntos)[0])
    falhas += not checar(
        "RG nº 1234567, expedido por SSP/PA" in saida_juntos,
        "número e órgão digitados juntos ainda são separados",
    )

    # A qualificação é uma frase corrida: o estado civil entra em minúscula,
    # como "brasileira, casado(a), carteira" — do jeito que se lê numa petição,
    # não do jeito que se lê num botão.
    falhas += not checar(
        "brasileira, casado(a)," in saida,
        "o estado civil entra na frase em minúscula",
    )

    # --- as cláusulas não podem ter mudado -------------------------------
    # É o ponto mais sério: percentual, foro e OAB têm efeito jurídico. O
    # programa preenche lacuna, não redige contrato.
    for clausula in (
        "30% (trinta por cento) sobre o valor bruto auferido no processo",
        "art. 791-A da CLT",
        "foro da Circunscrição Judiciária de Brasília/DF",
        "OAB/DF nº 47.465",
        "42.093.792/0001-36",
    ):
        falhas += not checar(clausula in saida, f"cláusula preservada: {clausula[:42]}…")

    marcadores = set(contrato._MARCADOR.findall(original))
    sobrando = {m for m in contrato._MARCADOR.findall(saida)}
    falhas += not checar(
        sobrando <= marcadores,
        f"nenhum colchete novo apareceu no documento gerado ({sobrando - marcadores})",
    )

    # Parágrafo que não tinha marcador nenhum tem de sair igualzinho — é o que
    # separa "preencher lacuna" de "reescrever contrato".
    antes = paragrafos_do_docx(modelo.read_bytes())
    depois = set(paragrafos_do_docx(docx))
    sem_marcador = [p for p in antes if p.strip() and not contrato._MARCADOR.search(p)]
    alterados = [p for p in sem_marcador if p not in depois]
    falhas += not checar(
        not alterados,
        f"os {len(sem_marcador)} parágrafos sem marcador saem intactos"
        + (f" (mexeram em {len(alterados)}: {alterados[:1]})" if alterados else ""),
    )

    # --- o arquivo continua abrível --------------------------------------
    # Reserializar XML renomeia prefixo de namespace, e o `mc:Ignorable` cita
    # prefixo pelo nome: errando isso, o Word acusa arquivo corrompido.
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        falhas += not checar(zf.testzip() is None, "o zip gerado é íntegro")
        nomes = set(zf.namelist())
        with zipfile.ZipFile(modelo) as zorig:
            falhas += not checar(
                nomes == set(zorig.namelist()),
                "nenhuma parte do pacote se perdeu (estilos, fontes, imagens do timbre)",
            )
        documento = zf.read("word/document.xml").decode("utf-8")

    falhas += not checar(
        documento.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'),
        "a declaração XML é a que o Word escreve",
    )
    falhas += not checar(
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"' in documento,
        "o prefixo w: sobreviveu à reescrita — sem ele o Word recusa o arquivo",
    )
    ignoraveis = re.search(r'mc:Ignorable="([^"]*)"', documento)
    if ignoraveis:
        declarados = set(re.findall(r"xmlns:(\w+)=", documento))
        citados = set(ignoraveis.group(1).split())
        falhas += not checar(
            citados <= declarados,
            f"todo prefixo citado em mc:Ignorable segue declarado (faltando: {citados - declarados})",
        )

    # --- mapeamento entrevista x modelo ----------------------------------
    pedidos = set(contrato.marcadores_do_modelo())
    sabidos = {contrato._chave(f"[{k}]") for k in contrato.valores_da_entrevista({})}
    falhas += not checar(
        pedidos <= sabidos,
        f"a entrevista sabe responder todo campo do modelo (sem origem: {pedidos - sabidos})",
    )

    caminho_falso.unlink(missing_ok=True)
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
