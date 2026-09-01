"""O documento acha o próprio item do checklist — inclusive quando vem no campo errado.

O que está sendo medido aqui é a promessa de `app/roteamento.py`: quem envia dá
um palpite (ou nem isso), e é a leitura do documento que decide a que item ele
responde. Três coisas precisam ser verdade ao mesmo tempo:

  - documento no campo errado vai para o campo certo, e o campo errado volta a
    contar como pendente — não como "precisa reenviar";
  - documento que ninguém soube identificar NÃO é chutado num item: fica na
    triagem, com o arquivo guardado, esperando uma pessoa;
  - documento sem campo cadastral (CAT, laudo, contracheque) conta como
    entregue, que é o defeito velho consertado junto — o extrator só conhece
    documento de identidade, e o resto ficava eternamente "a conferir".

Como no `test_uploads_api`, o OCR é falso: o que se mede é o roteamento, não a
leitura. O falso decide o tipo pelo NOME do arquivo, para cada caso de teste
poder dizer que documento está mandando.

Rodar: .venv\\Scripts\\python.exe -m tests.test_roteamento_documentos
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import armazenamento, casos, categorias, main, pipeline, roteamento, valor_documento
from app.celery_app import celery_app

CATEGORIA = categorias.obter("acidente_trabalho_correios")

PDF = b"%PDF-1.7 teste"


def checar(condicao: bool, descricao: str, detalhe: str = "") -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}" + (f" ({detalhe})" if detalhe and not condicao else ""))
    return condicao


# --------------------------------------------------------------- OCR de mentira


def extracao(tipo: str, *, cpf: bool = False, rg: bool = False, texto: bool = True) -> dict:
    """Um resultado de pipeline com o mínimo que o roteamento lê."""
    campos = []
    if cpf:
        campos.append({"nome": "cpf", "valor": "529.982.247-25", "valido": True})
    if rg:
        campos.append({"nome": "rg", "valor": "12.345.678-9", "valido": True})
    return {
        "id": "falso",
        "arquivo": "falso.pdf",
        "tipo": {
            "codigo": tipo,
            "detectado": tipo,
            "descricao": tipo,
            "descricao_detectado": tipo,
            "confianca_classificacao": 24 if tipo != "desconhecido" else 0,
        },
        "campos": campos,
        "validacao": {
            "veredito": "APROVADO",
            "dados_utilizaveis": bool(campos),
            "texto_utilizavel": texto,
            "score_legibilidade": 90,
        },
        "texto_linhas": [{"texto": "documento de teste", "confianca": 0.9}],
        "texto_completo": "documento de teste",
    }


#: O nome do arquivo diz que documento é. Fora desta tabela, o falso devolve
#: "desconhecido" com texto legível — o caso do laudo, da CAT e do contracheque.
POR_NOME = {
    "comprovante": ("comprovante_residencia", False, False),
    "cpf": ("cpf", True, False),
    "cnh": ("cnh", True, True),
    "ctps": ("ctps", False, False),
    "ilegivel": ("desconhecido", False, False),
}


def processar_falso(conteudo: bytes, nome: str, idioma: str, tipo_forcado=None, **_o) -> dict:
    assert conteudo
    for chave, (tipo, cpf, rg) in POR_NOME.items():
        if chave in nome:
            return extracao(tipo, cpf=cpf, rg=rg, texto=chave != "ilegivel")
    return extracao("desconhecido", texto=True)


def esperar_leitura(cliente: TestClient, caso_id: str, limite_s: float = 20.0) -> dict:
    limite = time.monotonic() + limite_s
    while True:
        situacao = cliente.get(f"/api/casos/{caso_id}").json()
        lendo = [
            e
            for grupo in ([i["entregas"] for i in situacao["itens"]] + [situacao.get("triagem", [])])
            for e in grupo
            if e.get("status_proc") in {"na_fila", "processando"}
        ]
        if not lendo:
            return situacao
        if time.monotonic() > limite:
            raise AssertionError(f"{len(lendo)} entrega(s) ainda em leitura após {limite_s}s")
        time.sleep(0.05)


def item_de(situacao: dict, codigo: str) -> dict:
    return next(i for i in situacao["itens"] if i["codigo"] == codigo)


# ------------------------------------------------------------------ a decisão


def testar_decisao() -> int:
    falhas = 0
    print("1. A decisão de destino, sem passar pela API")

    cpf = next(i for i in CATEGORIA.itens if i.codigo == "DOC.04")
    residencia = next(i for i in CATEGORIA.itens if i.codigo == "DOC.05")

    # O caso do enunciado: comprovante de residência enviado no campo do CPF.
    destino = roteamento.decidir(extracao("comprovante_residencia"), CATEGORIA, cpf)
    falhas += not checar(destino.itens == ["DOC.05"], "comprovante no campo do CPF vai para DOC.05", str(destino.itens))
    falhas += not checar(destino.origem == roteamento.DETERMINISTICO, "e a decisão é do classificador, não do modelo")

    # O mesmo arquivo, agora no campo certo: nada muda de lugar.
    destino = roteamento.decidir(extracao("comprovante_residencia"), CATEGORIA, residencia)
    falhas += not checar(
        destino.itens == ["DOC.05"] and destino.origem == roteamento.ESCOLHA,
        "no campo certo, a escolha de quem enviou é mantida",
    )

    # Sem campo nenhum (envio em massa): o documento se coloca sozinho.
    destino = roteamento.decidir(extracao("ctps"), CATEGORIA, None)
    falhas += not checar(destino.itens == ["DOC.06"], "sem campo escolhido, a CTPS acha o DOC.06", str(destino.itens))

    # CNH legível vale por identidade e CPF, como já valia no envio manual.
    destino = roteamento.decidir(extracao("cnh", cpf=True, rg=True), CATEGORIA, None)
    falhas += not checar(
        set(destino.itens) == {"DOC.03", "DOC.04"}, "CNH legível cobre RG e CPF", str(destino.itens)
    )

    # Sem classificador e sem modelo, ninguém chuta: vai para a triagem.
    def sem_modelo(*_a, **_k):
        raise valor_documento.ErroValor("modelo desligado no teste")

    with patch.object(roteamento.valor_documento, "ler", sem_modelo):
        destino = roteamento.decidir(extracao("desconhecido"), CATEGORIA, None)
        falhas += not checar(destino.em_triagem, "documento não identificado fica em triagem")
        falhas += not checar(destino.itens == [], "e não é marcado em item nenhum")

        # Com item escolhido, a indisponibilidade do modelo não move nada.
        destino = roteamento.decidir(extracao("desconhecido"), CATEGORIA, cpf)
        falhas += not checar(
            destino.itens == ["DOC.04"] and destino.origem == roteamento.ESCOLHA,
            "sem evidência, a escolha de quem enviou é respeitada",
        )

    # A leitura do modelo é a única fonte para CAT, laudo e contracheque.
    def leitura_cat(*_a, **_k):
        return {
            "documento": "CAT",
            "serve_para": [{"item": "DOC.10", "porque": "comunica o acidente"}],
            "achados": [],
            "atencao": [],
            "sugere_pedir": [],
        }

    with patch.object(roteamento.valor_documento, "ler", leitura_cat):
        destino = roteamento.decidir(extracao("desconhecido"), CATEGORIA, None)
        falhas += not checar(
            destino.itens == ["DOC.10"] and destino.origem == roteamento.SEMANTICO,
            "sem classificador, o modelo aponta a CAT — e vai rotulado como leitura",
        )
        falhas += not checar(destino.confianca <= 65, "e a confiança do modelo não se disfarça de certeza")

    # Duas indicações fracas não derrubam a escolha de uma pessoa.
    def leitura_ambigua(*_a, **_k):
        return {
            "documento": "Laudo",
            "serve_para": [{"item": "DOC.14", "porque": "x"}, {"item": "DOC.15", "porque": "y"}],
            "achados": [],
            "atencao": [],
            "sugere_pedir": [],
        }

    with patch.object(roteamento.valor_documento, "ler", leitura_ambigua):
        destino = roteamento.decidir(extracao("desconhecido"), CATEGORIA, cpf)
        falhas += not checar(
            destino.itens == ["DOC.04"],
            "leitura ambígua não move o documento do item escolhido",
            str(destino.itens),
        )
    return falhas


# --------------------------------------------------------------- pela API


def testar_api() -> int:
    falhas = 0
    with (
        patch.object(main, "_tentar_aquecer"),
        patch.object(main.auth, "ATIVA", False),
        TestClient(main.app) as cliente,
    ):
        caso_id = cliente.post(
            "/api/casos",
            data={"cliente": "Joana do Roteamento", "categoria": "acidente_trabalho_correios"},
        ).json()["id"]

        print("\n2. Documento no campo errado")
        resposta = cliente.post(
            f"/api/casos/{caso_id}/documentos",
            data={"item": "DOC.04", "idioma": "pt"},
            files={"arquivo": ("comprovante.pdf", PDF, "application/pdf")},
        )
        falhas += not checar(resposta.status_code == 201, "a rota aceita o envio")

        situacao = esperar_leitura(cliente, caso_id)
        falhas += not checar(
            item_de(situacao, "DOC.05")["status"] == casos.ENTREGUE,
            "o comprovante marca o item do comprovante",
            item_de(situacao, "DOC.05")["status"],
        )
        falhas += not checar(
            item_de(situacao, "DOC.04")["status"] == casos.PENDENTE,
            "e o item do CPF volta a ser 'falta enviar', não 'precisa reenviar'",
            item_de(situacao, "DOC.04")["status"],
        )
        entrega = item_de(situacao, "DOC.05")["entregas"][0]
        falhas += not checar(
            entrega.get("roteamento_origem") == "deterministico",
            "fica gravado que quem decidiu foi o classificador",
            str(entrega.get("roteamento_origem")),
        )
        falhas += not checar(
            any("encaminhado" in a for a in entrega["alertas"]),
            "e a tela do advogado diz que o arquivo foi remanejado",
            str(entrega["alertas"]),
        )

        print("\n3. Envio em massa, sem escolher item nenhum")
        lote = cliente.post(
            f"/api/casos/{caso_id}/documentos/lote",
            files=[
                ("arquivos", ("meu-cpf.pdf", PDF, "application/pdf")),
                ("arquivos", ("ctps-pagina.pdf", PDF, "application/pdf")),
                ("arquivos", ("ilegivel.jpg", PDF, "image/jpeg")),
            ],
        )
        falhas += not checar(lote.status_code == 201, "o lote é aceito", str(lote.status_code))
        falhas += not checar(len(lote.json()["recebidos"]) == 3, "os três arquivos entram")

        with patch.object(roteamento.valor_documento, "ler", lambda *a, **k: (_ for _ in ()).throw(
            valor_documento.ErroValor("modelo desligado no teste")
        )):
            situacao = esperar_leitura(cliente, caso_id)

        falhas += not checar(
            item_de(situacao, "DOC.04")["status"] == casos.ENTREGUE, "o CPF do lote acha o DOC.04"
        )
        falhas += not checar(
            item_de(situacao, "DOC.06")["status"] == casos.ENTREGUE, "a CTPS do lote acha o DOC.06"
        )

        print("\n4. O que ninguém identificou fica na triagem")
        falhas += not checar(len(situacao["triagem"]) == 1, "o ilegível não entrou em item nenhum", str(len(situacao["triagem"])))
        falhas += not checar(situacao["progresso"]["em_triagem"] == 1, "e o progresso conta a triagem")
        falhas += not checar(
            not situacao["progresso"]["pronto"],
            "com arquivo por identificar, o caso não se declara pronto",
        )

        print("\n5. O advogado tira da triagem com um clique")
        entrega_id = situacao["triagem"][0]["id"]
        movida = cliente.patch(f"/api/entregas/{entrega_id}/itens", json={"itens": ["DOC.10"]})
        falhas += not checar(movida.status_code == 200, "a reatribuição responde", str(movida.status_code))

        situacao = cliente.get(f"/api/casos/{caso_id}").json()
        falhas += not checar(situacao["triagem"] == [], "a triagem esvazia")
        falhas += not checar(
            item_de(situacao, "DOC.10")["entregas"][0]["roteamento_origem"] == "humano",
            "e fica registrado que quem decidiu foi uma pessoa",
        )

        recusada = cliente.patch(f"/api/entregas/{entrega_id}/itens", json={"itens": ["DOC.99"]})
        falhas += not checar(recusada.status_code == 400, "item fora do checklist é recusado")

        print("\n6. Documento sem campo cadastral conta como entregue")
        cliente.post(
            f"/api/casos/{caso_id}/documentos",
            data={"item": "DOC.13", "idioma": "pt"},
            files={"arquivo": ("atestado.pdf", PDF, "application/pdf")},
        )
        with patch.object(roteamento.valor_documento, "ler", lambda *a, **k: {
            "documento": "Atestado médico",
            "serve_para": [{"item": "DOC.13", "porque": "afastamento"}],
            "achados": [], "atencao": [], "sugere_pedir": [],
        }):
            situacao = esperar_leitura(cliente, caso_id)
        falhas += not checar(
            item_de(situacao, "DOC.13")["status"] == casos.ENTREGUE,
            "o atestado, sem campo nenhum extraído, cumpre o item",
            item_de(situacao, "DOC.13")["status"],
        )

        print("\n7. O portal do cliente enxerga o que está em análise")
        situacao_cliente = casos.visao_do_cliente(casos.montar_situacao(caso_id))
        falhas += not checar(
            situacao_cliente["em_analise"] == 0,
            "nada em análise depois que tudo foi roteado",
            str(situacao_cliente["em_analise"]),
        )
    return falhas


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="ocr-roteamento-"))
    armazenamento.DIR_DADOS = temporario
    armazenamento.DIR_ARQUIVOS = temporario / "casos"
    armazenamento.CAMINHO_BANCO = temporario / "casos.db"
    armazenamento.inicializar()

    processador_original = pipeline.processar
    pipeline.processar = processar_falso
    eager_original = celery_app.conf.task_always_eager
    propaga_original = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False

    try:
        falhas = testar_decisao() + testar_api()
    finally:
        pipeline.processar = processador_original
        celery_app.conf.task_always_eager = eager_original
        celery_app.conf.task_eager_propagates = propaga_original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
