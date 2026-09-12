"""A análise dos documentos não deixa passar achado sem citação conferida.

O achado vai virar peça processual. Quem revisa depois não estava na conversa
nem leu o documento — para essa pessoa, "CID F43.1" inventado e "CID F43.1"
verdadeiro são indistinguíveis. Por isso a citação é conferida contra o texto do
documento APONTADO, e não contra o conjunto: citação que existe em outro anexo é
atribuição errada de prova, que é tão grave quanto invenção.

Nada aqui chama modelo: o `_chamar_modelo` é trocado por um que devolve o JSON
que se quer testar.

Rodar: .venv\Scripts\python.exe -m tests.test_analise_documentos
"""

from __future__ import annotations

from app import analise_documentos as ad


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


LAUDO = "Paciente em acompanhamento. Diagnóstico: CID F43.1 — estresse pós-traumático."
CNIS = "Vinculo EMPRESA X. Afastamento de 12/03/2026 a 27/03/2026 por auxilio-doenca."

DOCUMENTOS = [
    {"id": "e1", "arquivo": "laudo.pdf", "texto": LAUDO},
    {"id": "e2", "arquivo": "cnis.png", "texto": CNIS},
]


def instalar(resposta: dict, documentos: list[dict] | None = None) -> list[str]:
    """Troca o modelo e devolve a lista onde as mensagens enviadas ficam."""
    enviadas: list[str] = []

    def falso(mensagem: str) -> dict:
        enviadas.append(mensagem)
        return resposta

    ad._chamar_modelo = falso  # type: ignore[assignment]
    escolhidos = list(documentos) if documentos is not None else list(DOCUMENTOS)
    ad._documentos_do_caso = lambda _id: escolhidos  # type: ignore[assignment]
    ad._fatos_conhecidos = lambda _id: ["Ficou afastado pelo INSS?: não"]  # type: ignore[assignment]
    # `analisar` cacheia por `atualizado_em` do caso; aqui não há banco, e cada
    # cenário troca o modelo por outro — sem limpar, o 2º cenário receberia o
    # resultado cacheado do 1º e o mock novo nunca seria chamado.
    ad.armazenamento.obter_caso = lambda _id: {"atualizado_em": "teste"}  # type: ignore[assignment]
    ad._analisar_cacheado.limpar_cache()  # type: ignore[attr-defined]
    return enviadas


def cenario_citacao_conferida() -> int:
    falhas = 0
    instalar(
        {
            "achados": [
                # Verdadeiro: a citação está no laudo.
                {"informacao": "Diagnóstico de estresse pós-traumático",
                 "documento": "laudo.pdf", "citacao": "CID F43.1",
                 "relevancia": "sustenta o nexo", "contradiz": False},
                # Inventado: ninguém escreveu isso em documento nenhum.
                {"informacao": "Incapacidade permanente",
                 "documento": "laudo.pdf", "citacao": "incapacidade total e permanente",
                 "relevancia": "aumentaria o pedido", "contradiz": False},
                # Trocado de arquivo: a citação existe, mas no OUTRO documento.
                {"informacao": "Afastamento previdenciário",
                 "documento": "laudo.pdf", "citacao": "Afastamento de 12/03/2026",
                 "relevancia": "prova o afastamento", "contradiz": True},
            ]
        }
    )
    r = ad.analisar("caso-1")
    informacoes = [a["informacao"] for a in r["achados"]]

    falhas += not checar(
        "Diagnóstico de estresse pós-traumático" in informacoes,
        "o achado com citação real passa",
    )
    falhas += not checar(
        "Incapacidade permanente" not in informacoes,
        "o achado inventado NÃO passa",
    )
    falhas += not checar(
        "Afastamento previdenciário" not in informacoes,
        "e o atribuído ao documento errado também não",
    )
    falhas += not checar(
        r["recusados"] == 2, f"as duas recusas são contadas e mostradas ({r['recusados']})"
    )
    return falhas


def cenario_ocr_imperfeito() -> int:
    """Acento e pontuação trocados pelo OCR não podem recusar citação honesta."""
    falhas = 0
    instalar(
        {
            "achados": [
                {"informacao": "Diagnóstico registrado",
                 "documento": "laudo.pdf", "citacao": "CID F43.1 - estresse pos traumatico",
                 "relevancia": "nexo", "contradiz": False},
            ]
        }
    )
    r = ad.analisar("caso-1")
    falhas += not checar(
        len(r["achados"]) == 1,
        "citação sem acento e com hífen diferente ainda confere",
    )
    return falhas


def cenario_o_que_o_modelo_recebe() -> int:
    falhas = 0
    enviadas = instalar({"achados": []})
    ad.analisar("caso-1")
    msg = enviadas[0] if enviadas else ""
    falhas += not checar("laudo.pdf" in msg and "cnis.png" in msg, "os dois documentos vão no prompt")
    falhas += not checar("CID F43.1" in msg, "com o texto lido, não só o nome do arquivo")
    falhas += not checar(
        "Ficou afastado pelo INSS?: não" in msg,
        "e o que a entrevista já registrou, para o modelo não repetir",
    )
    return falhas


def cenario_atribuicao_de_parte() -> int:
    """Cada achado diz de quem é a informação; valor estranho vira 'indefinido'."""
    falhas = 0
    instalar(
        {
            "achados": [
                # Terceiro: o médico que assinou o laudo, com papel descrito.
                {"informacao": "Laudo assinado por psiquiatra",
                 "documento": "laudo.pdf", "citacao": "CID F43.1",
                 "relevancia": "sustenta o nexo", "contradiz": False,
                 "parte": "terceiro", "papel": "médico que assinou o laudo"},
                # Titular, mas o modelo mandou a parte em maiúsculas — normaliza.
                {"informacao": "Vínculo do cliente com a empresa",
                 "documento": "cnis.png", "citacao": "Afastamento de 12/03/2026",
                 "relevancia": "prova o afastamento", "contradiz": False,
                 "parte": "TITULAR", "papel": "reclamante"},
                # Parte inválida: precisa cair em 'indefinido', não vazar o lixo.
                {"informacao": "Vínculo EMPRESA X",
                 "documento": "cnis.png", "citacao": "Vinculo EMPRESA X",
                 "relevancia": "identifica a empregadora", "contradiz": False,
                 "parte": "chute", "papel": ""},
            ]
        }
    )
    r = ad.analisar("caso-1")
    por_info = {a["informacao"]: a for a in r["achados"]}
    falhas += not checar(
        por_info.get("Laudo assinado por psiquiatra", {}).get("parte") == "terceiro"
        and "médico" in por_info.get("Laudo assinado por psiquiatra", {}).get("papel", ""),
        "achado de terceiro guarda a parte e o papel",
    )
    falhas += not checar(
        por_info.get("Vínculo do cliente com a empresa", {}).get("parte") == "titular",
        "parte em maiúsculas é normalizada para 'titular'",
    )
    falhas += not checar(
        por_info.get("Vínculo EMPRESA X", {}).get("parte") == "indefinido",
        "parte fora do vocabulário vira 'indefinido'",
    )
    return falhas


def cenario_gastos() -> int:
    """Gastos: em ordem cronológica, ligados ao documento, com citação conferida."""
    falhas = 0
    instalar(
        {
            "achados": [],
            "gastos": [
                {"valor": "R$ 50,00", "data": "10/06/2025", "descricao": "medicamentos",
                 "documento": "laudo.pdf", "citacao": "CID F43.1"},
                {"valor": "R$ 22,90", "data": "15/03/2025", "descricao": "corrida",
                 "documento": "cnis.png", "citacao": "Afastamento de 12/03/2026"},
                # Citação que não existe no documento: recusada, como nos achados.
                {"valor": "R$ 9,99", "data": "01/01/2020", "descricao": "inventado",
                 "documento": "laudo.pdf", "citacao": "compra que ninguém escreveu"},
            ],
        }
    )
    r = ad.analisar("caso-1")
    g = r["gastos"]
    falhas += not checar(len(g) == 2, "gasto com citação inexistente é recusado")
    falhas += not checar([x["data"] for x in g] == ["15/03/2025", "10/06/2025"], "gastos em ordem cronológica")
    falhas += not checar(g[0]["entrega_id"] == "e2", "gasto ligado ao documento de origem (entrega_id)")
    return falhas


def cenario_orcamento_dos_documentos() -> int:
    """Caso com MUITOS anexos: nenhum tipo de documento pode ficar invisível.

    Medido num caso real (`da5a030b`, 46 anexos, 57 mil caracteres de OCR): o
    montador ia somando documento por documento até estourar 40 mil caracteres e
    aí dava `break`. Ficavam de fora 15 anexos — 8 notas fiscais de farmácia, 7
    comprovantes de transporte, exames e o plano de saúde. Ou seja, justamente os
    papéis que carregam DATA e VALOR: a cronologia e a lista de gastos eram
    montadas sem ver os documentos que as produzem, e nada na tela dizia isso.

    O que este cenário protege:

    1. TODO documento aparece no prompt, mesmo o último da fila.
    2. O corte de cada documento pega o começo E o fim — numa nota fiscal o valor
       total está no pé, e cortar só o começo entrega um gasto sem valor.
    3. Quando ainda assim algo não couber, sai NOMEADO no resultado, para a tela
       poder dizer qual anexo não entrou na leitura.
    """
    falhas = 0

    # 60 documentos de 3 mil caracteres = 180 mil, bem acima do teto.
    muitos = []
    for n in range(60):
        cabeca = f"NOTA FISCAL {n:02d} EMITENTE DROGARIA CENTRAL DATA 1{n % 9}/03/2025 "
        muitos.append(
            {
                "id": f"e{n}",
                "arquivo": f"nota_{n:02d}.pdf",
                "texto": cabeca + ("m" * 2800) + f" VALOR TOTAL R$ {n + 1},50",
            }
        )

    mensagem, fora = ad._montar_mensagem(muitos, [])

    citados = [d["arquivo"] for d in muitos if f"=== {d['arquivo']} ===" in mensagem]
    falhas += not checar(
        len(citados) == 60, f"os 60 anexos entram no prompt (entraram {len(citados)})"
    )
    falhas += not checar(fora == [], f"e nada fica de fora ({len(fora)})")
    falhas += not checar(
        len(mensagem) <= ad.MAX_CARACTERES_TOTAL + 2000,
        f"sem estourar o teto do prompt ({len(mensagem)} caracteres)",
    )
    falhas += not checar(
        "NOTA FISCAL 59" in mensagem and "VALOR TOTAL R$ 60,50" in mensagem,
        "o ÚLTIMO da fila entra com cabeçalho E com o valor do pé",
    )

    # Documento único e gigante: aí o teto por documento é que manda, e ele não
    # pode engolir a janela inteira.
    unico = [{"id": "x", "arquivo": "processo.pdf", "texto": "a" * 500_000}]
    msg_unico, fora_unico = ad._montar_mensagem(unico, [])
    falhas += not checar(
        len(msg_unico) <= ad.MAX_CARACTERES_POR_DOCUMENTO + 500 and not fora_unico,
        f"um PDF gigante é cortado no teto por documento ({len(msg_unico)})",
    )

    # E o que realmente não couber precisa sair com NOME.
    #
    # Chegar a esse ponto exige passar do limite em que nem a fatia mínima cabe
    # para todos — acima de ~128 anexos, com o teto de hoje. Abaixo disso a
    # divisão dá conta e ninguém fica de fora, que é o comportamento desejado.
    demais = [
        {"id": f"g{n}", "arquivo": f"gordo_{n}.pdf", "texto": "z" * 5_000}
        for n in range(200)
    ]
    _, fora_demais = ad._montar_mensagem(demais, [])
    falhas += not checar(
        bool(fora_demais) and all(nome.startswith("gordo_") for nome in fora_demais),
        f"o que não couber sai nomeado, não só contado ({len(fora_demais)} nomes)",
    )
    falhas += not checar(
        len(fora_demais) < len(demais),
        f"mas a maioria ainda entra ({len(demais) - len(fora_demais)} de {len(demais)})",
    )
    return falhas


def cenario_nome_do_arquivo_com_caminho() -> int:
    """Anexo com CAMINHO na chave e nome curto na resposta do modelo.

    O caso real que motivou isto (`da5a030b`): os anexos vêm de pastas, então a
    chave é "HILDEBRANDO_.../04_Notas_Fiscais/Scanner_20250623 (25).pdf", e é o
    caminho que vai no cabeçalho do prompt. O modelo aponta a origem pelo NOME DO
    ARQUIVO — "Scanner_20250623 (25).pdf". A conferência procurava esse texto como
    chave, não achava, e recusava o achado como "atribuição errada".

    O efeito medido: 19 gastos e 13 eventos de cronologia devolvidos pelo modelo,
    TODOS recusados. A tela mostrava "cronologia dos fatos" vazia e a lista de
    gastos vazia, como se 46 documentos não dissessem nada.

    A resolução pelo nome curto só vale quando ele é ÚNICO — é o segundo bloco
    aqui. Dois arquivos com o mesmo nome em pastas diferentes voltam a ser
    recusados, porque escolher um dos dois no chute é exatamente o erro que a
    conferência existe para impedir.
    """
    falhas = 0
    caminho = "HILDEBRANDO/04_Notas_Fiscais/Scanner_20250623 (25).pdf"
    instalar(
        {
            "achados": [
                {"informacao": "Compra de medicamento", "documento": "Scanner_20250623 (25).pdf",
                 "citacao": "TRAMAL 100MG", "relevancia": "gasto com tratamento",
                 "parte": "titular", "papel": "reclamante"}
            ],
            "gastos": [
                {"valor": "R$ 517,30", "data": "05/05/2025", "descricao": "medicamentos",
                 "documento": "Scanner_20250623 (25).pdf", "citacao": "VALOR TOTAL 517,30"}
            ],
            "cronologia": [
                {"data": "05/05/2025", "evento": "Compra de medicamento",
                 "documento": "Scanner_20250623 (25).pdf", "citacao": "05/05/2025"}
            ],
        },
        documentos=[
            {"id": "e9", "arquivo": caminho,
             "texto": "DROGARIA CENTRAL 05/05/2025 TRAMAL 100MG VALOR TOTAL 517,30"}
        ],
    )
    r = ad.analisar("caso-1")

    falhas += not checar(r["recusados"] == 0, f"nada é recusado por causa do caminho ({r['recusados']})")
    falhas += not checar(len(r["achados"]) == 1, f"o achado entra ({len(r['achados'])})")
    falhas += not checar(len(r["gastos"]) == 1, f"o gasto entra ({len(r['gastos'])})")
    falhas += not checar(len(r["cronologia"]) == 1, f"o evento entra ({len(r['cronologia'])})")
    if r["achados"]:
        falhas += not checar(
            r["achados"][0]["documento"] == caminho,
            "e o achado guarda o CAMINHO completo, não o nome curto "
            f"({r['achados'][0]['documento']})",
        )
        falhas += not checar(
            r["achados"][0]["entrega_id"] == "e9", "ligado à entrega certa"
        )

    # Nome curto ambíguo: duas pastas, mesmo arquivo. Aí não se adivinha.
    instalar(
        {
            "achados": [
                {"informacao": "Algo", "documento": "Scanner.pdf", "citacao": "TRAMAL",
                 "relevancia": "x", "parte": "titular", "papel": ""}
            ]
        },
        documentos=[
            {"id": "a1", "arquivo": "PASTA_A/Scanner.pdf", "texto": "TRAMAL 100MG"},
            {"id": "b1", "arquivo": "PASTA_B/Scanner.pdf", "texto": "TRAMAL 100MG"},
        ],
    )
    r2 = ad.analisar("caso-1")
    falhas += not checar(
        len(r2["achados"]) == 0 and r2["recusados"] == 1,
        f"nome repetido em duas pastas é recusado, não chutado ({len(r2['achados'])} achados)",
    )
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("citação é conferida contra o documento apontado", cenario_citacao_conferida),
        ("OCR imperfeito não recusa citação honesta", cenario_ocr_imperfeito),
        ("o que o modelo recebe", cenario_o_que_o_modelo_recebe),
        ("cada achado diz de quem é a informação", cenario_atribuicao_de_parte),
        ("gastos em ordem cronológica, com origem e citação", cenario_gastos),
        ("caso com muitos anexos: nenhum fica invisível", cenario_orcamento_dos_documentos),
        ("anexo em pasta: o modelo aponta pelo nome do arquivo", cenario_nome_do_arquivo_com_caminho),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
