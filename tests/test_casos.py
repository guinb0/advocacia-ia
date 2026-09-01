"""Fluxo do caso: criar, receber documentos, ver o que falta, gerar o pedido.

Usa um banco temporário — não encosta em `dados/casos.db`.

    .venv\\Scripts\\python.exe -m tests.test_casos
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402

# Redireciona o banco e os arquivos ANTES de qualquer uso.
_TEMP = Path(tempfile.mkdtemp(prefix="ocr-casos-"))
armazenamento.DIR_DADOS = _TEMP
armazenamento.DIR_ARQUIVOS = _TEMP / "casos"
armazenamento.CAMINHO_BANCO = _TEMP / "casos.db"

from app import casos, categorias  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def extracao_falsa(tipo: str, utilizaveis: bool = True, score: int = 90) -> dict:
    """Imita o retorno de pipeline.processar sem gastar OCR."""
    return {
        "id": f"fake-{tipo}-{score}",
        "tipo": {"codigo": tipo, "descricao": tipo},
        "validacao": {
            "veredito": "APROVADO" if utilizaveis else "REPROVADO",
            "dados_utilizaveis": utilizaveis,
            "score_legibilidade": score,
        },
        "campos": [],
    }


def entregar(caso_id: str, item_codigo: str, tipo: str, utilizaveis=True, score=90) -> dict:
    categoria = categorias.ACIDENTE_TRABALHO_CORREIOS
    item = next(i for i in categoria.itens if i.codigo == item_codigo)
    extracao = extracao_falsa(tipo, utilizaveis, score)
    confere = casos.tipo_confere(item, tipo)

    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item_codigo}_{extracao['id']}.png"
    caminho.write_bytes(b"imagem-de-mentira")

    return armazenamento.registrar_entrega(
        caso_id, item_codigo, f"{item_codigo}.png", caminho, extracao, confere
    )


def main() -> int:
    armazenamento.inicializar()
    print(f"banco temporário: {armazenamento.CAMINHO_BANCO}\n")

    # -------------------------------------- categoria de acidente geral (DOCX)
    geral = categorias.obter("acidente_trabalho_geral")
    checar(geral is not None, "categoria de acidente do trabalho geral está disponível")
    checar(len(geral.itens) == 35, "categoria geral contém os 35 documentos do checklist")
    obrigatorios_geral = [i.numero for i in geral.itens if i.obrigatorio]
    checar(
        obrigatorios_geral == [*range(1, 11), *range(12, 18), *range(20, 26)],
        "obrigatórios da categoria geral respeitam os itens em vermelho do DOCX",
        str(obrigatorios_geral),
    )

    # ------------------------------------------ categoria de doença ocupacional
    doenca = categorias.obter("doenca_ocupacional")
    checar(doenca is not None, "categoria de doença ocupacional está disponível")
    checar(len(doenca.itens) == 37, "doença ocupacional contém os 37 documentos")
    obrigatorios_doenca = [i.numero for i in doenca.obrigatorios]
    checar(
        obrigatorios_doenca
        == [*range(1, 10), 15, 16, 17, 19, 21, 22, 23, 24, 26, 27, 29, 30, 31, 32],
        "obrigatórios de doença ocupacional respeitam os itens em vermelho do DOCX",
        str(obrigatorios_doenca),
    )
    caso_doenca = armazenamento.criar_caso("José da Silva", "doenca_ocupacional")
    situacao_doenca = casos.montar_situacao(caso_doenca["id"])
    checar(
        situacao_doenca["progresso"]["obrigatorios_total"] == 23,
        "caso de doença ocupacional inicia com 23 obrigatórios pendentes",
    )
    armazenamento.excluir_caso(caso_doenca["id"])

    # ------------------------------------------------ categoria assalto a carteiro
    assalto = categorias.obter("assalto_carteiro")
    checar(assalto is not None, "categoria de assalto a carteiro está disponível")
    checar(len(assalto.itens) == 19, "assalto a carteiro contém os 19 documentos")
    numeros_assalto = [i.numero for i in assalto.itens]
    checar(
        numeros_assalto == [*range(1, 17), 18, 19, 20],
        "assalto preserva o salto do DOC.16 para o DOC.18 existente no checklist",
        str(numeros_assalto),
    )
    obrigatorios_assalto = [i.numero for i in assalto.obrigatorios]
    checar(
        obrigatorios_assalto == [*range(1, 10), 12, 14],
        "obrigatórios de assalto respeitam os itens em vermelho do DOCX",
        str(obrigatorios_assalto),
    )
    caso_assalto = armazenamento.criar_caso("João Carteiro", "assalto_carteiro")
    situacao_assalto = casos.montar_situacao(caso_assalto["id"])
    checar(
        situacao_assalto["progresso"]["obrigatorios_total"] == 11,
        "caso de assalto inicia com 11 obrigatórios pendentes",
    )
    armazenamento.excluir_caso(caso_assalto["id"])

    # ---------------------------------------------------- categoria auxílio-acidente
    auxilio = categorias.obter("auxilio_acidente")
    checar(auxilio is not None, "categoria de auxílio-acidente está disponível")
    checar(len(auxilio.itens) == 11, "auxílio-acidente contém os 11 grupos informados")
    obrigatorios_auxilio = [i.numero for i in auxilio.obrigatorios]
    checar(
        obrigatorios_auxilio == [1, 2, 4, 5, 10],
        "auxílio-acidente possui 5 grupos essenciais",
        str(obrigatorios_auxilio),
    )
    caso_auxilio = armazenamento.criar_caso("Maria Segurada", "auxilio_acidente")
    situacao_auxilio = casos.montar_situacao(caso_auxilio["id"])
    checar(
        situacao_auxilio["progresso"]["obrigatorios_total"] == 5,
        "caso de auxílio-acidente inicia com 5 obrigatórios pendentes",
    )
    pedido_auxilio = casos.montar_pedido(caso_auxilio["id"])
    checar(
        "últimos 90 dias" in pedido_auxilio["texto"]
        and "Extrato de Contribuição (CNIS)" in pedido_auxilio["texto"],
        "pedido obrigatório inclui as orientações detalhadas ao cliente",
    )
    checar(
        "Último contracheque" not in pedido_auxilio["texto"],
        "pedido padrão não cobra documento condicional",
    )
    pedido_auxilio_completo = casos.montar_pedido(
        caso_auxilio["id"], incluir_opcionais=True
    )
    checar(
        "Último contracheque" in pedido_auxilio_completo["texto"],
        "pedido com opcionais inclui documento condicional",
    )
    armazenamento.excluir_caso(caso_auxilio["id"])

    # ------------------------------------------------------------ criar caso
    print("1. Criar caso")
    caso = armazenamento.criar_caso("Maria Aparecida", "acidente_trabalho_correios")
    caso_id = caso["id"]
    checar(len(armazenamento.listar_casos()) == 1, "o caso aparece na listagem")

    situacao = casos.montar_situacao(caso_id)
    p = situacao["progresso"]
    checar(len(situacao["itens"]) == 33, "checklist com 33 itens", f"veio {len(situacao['itens'])}")
    checar(p["obrigatorios_total"] == 14, "14 obrigatórios", f"veio {p['obrigatorios_total']}")
    checar(p["obrigatorios_entregues"] == 0, "nada entregue no início")
    checar(p["percentual_obrigatorios"] == 0, "progresso em 0%")
    checar(not p["pronto"], "caso novo não está pronto")
    checar(
        all(i["status"] == casos.PENDENTE for i in situacao["itens"]),
        "todos os itens começam pendentes",
    )

    # -------------------------------------------------- entrega que dá certo
    print("\n2. Entregar o CPF (DOC.04), tipo bate")
    entregar(caso_id, "DOC.04", "cpf")
    situacao = casos.montar_situacao(caso_id)
    item_cpf = next(i for i in situacao["itens"] if i["codigo"] == "DOC.04")
    checar(item_cpf["status"] == casos.ENTREGUE, "DOC.04 fica 'entregue'", item_cpf["status"])
    checar(situacao["progresso"]["obrigatorios_entregues"] == 1, "1 obrigatório entregue")
    checar(situacao["progresso"]["percentual_obrigatorios"] == 7, "progresso 1/14 = 7%")

    # ------------------------------------------------------- arquivo trocado
    print("\n3. Enviar um CPF no lugar do RG (DOC.03)")
    entregar(caso_id, "DOC.03", "cpf")
    situacao = casos.montar_situacao(caso_id)
    item_rg = next(i for i in situacao["itens"] if i["codigo"] == "DOC.03")
    checar(item_rg["status"] == casos.CONFERIR, "DOC.03 fica 'conferir'", item_rg["status"])
    alertas = item_rg["entregas"][0]["alertas"]
    checar(any("troca" in a.lower() for a in alertas), "avisa da possível troca", str(alertas))
    checar(
        situacao["progresso"]["obrigatorios_entregues"] == 1,
        "arquivo trocado não conta como entregue",
    )
    checar(situacao["progresso"]["itens_a_conferir"] == 1, "1 item a conferir")

    # ---------------------------------------------------- documento ilegível
    print("\n4. Entregar a CAT (DOC.10) ilegível")
    entregar(caso_id, "DOC.10", "desconhecido", utilizaveis=False, score=40)
    situacao = casos.montar_situacao(caso_id)
    item_cat = next(i for i in situacao["itens"] if i["codigo"] == "DOC.10")
    checar(item_cat["status"] == casos.CONFERIR, "DOC.10 fica 'conferir'", item_cat["status"])
    checar(
        any("extrair" in a for a in item_cat["entregas"][0]["alertas"]),
        "avisa que não deu para ler",
    )

    # ------------------------------- item sem classificador aceita sem palpite
    print("\n5. Entregar a procuração (DOC.01), que não tem classificador")
    entregar(caso_id, "DOC.01", "desconhecido")
    situacao = casos.montar_situacao(caso_id)
    item_proc = next(i for i in situacao["itens"] if i["codigo"] == "DOC.01")
    checar(item_proc["status"] == casos.ENTREGUE, "DOC.01 entregue", item_proc["status"])
    checar(
        item_proc["entregas"][0]["tipo_confere"] is None,
        "sem classificador, o sistema não opina sobre o tipo",
    )

    # ------------------------------------------ vários arquivos no mesmo item
    print("\n6. Dois atestados no DOC.13, um ilegível")
    entregar(caso_id, "DOC.13", "desconhecido", utilizaveis=False, score=30)
    entregar(caso_id, "DOC.13", "desconhecido", utilizaveis=True)
    situacao = casos.montar_situacao(caso_id)
    item_at = next(i for i in situacao["itens"] if i["codigo"] == "DOC.13")
    checar(len(item_at["entregas"]) == 2, "as duas entregas ficam registradas")
    checar(item_at["status"] == casos.ENTREGUE, "basta um arquivo bom para entregar o item")

    # --------------------------------------------------- pedido para o cliente
    print("\n7. Gerar o pedido para o cliente")
    pedido = casos.montar_pedido(caso_id)
    texto = pedido["texto"]
    checar("Maria Aparecida" in texto, "o pedido chama o cliente pelo nome")
    checar("CPF" not in pedido["faltando_obrigatorios"], "não pede o que já chegou")
    checar("RG" in pedido["reenviar"], "pede o reenvio do RG", str(pedido["reenviar"]))
    checar(
        "Contracheque do último mês trabalhado" in pedido["faltando_obrigatorios"],
        "cobra um obrigatório que falta",
    )
    # 14 obrigatórios menos os 5 que já têm arquivo: DOC.01, 03, 04, 10 e 13.
    # O 03 e o 10 entraram com problema, então saem em "reenviar", não em "faltando".
    checar(
        len(pedido["faltando_obrigatorios"]) == 9,
        "9 obrigatórios sem nenhum arquivo",
        f"veio {len(pedido['faltando_obrigatorios'])}: {pedido['faltando_obrigatorios']}",
    )
    checar(len(pedido["reenviar"]) == 2, "2 itens para reenviar", str(pedido["reenviar"]))
    checar("REENVIADOS" in texto, "o texto tem a seção de reenvio")
    checar("flash" in texto, "o texto traz as dicas de foto")

    sem_opcionais = casos.montar_pedido(caso_id, incluir_opcionais=False)["texto"]
    com_opcionais = casos.montar_pedido(caso_id, incluir_opcionais=True)["texto"]
    checar(len(com_opcionais) > len(sem_opcionais), "incluir_opcionais aumenta o pedido")
    checar("CNIS" in com_opcionais and "CNIS" not in sem_opcionais, "opcionais só quando pedidos")

    # ----------------------------------------------------- apagar uma entrega
    print("\n8. Apagar a entrega errada do RG")
    item_rg = next(i for i in situacao["itens"] if i["codigo"] == "DOC.03")
    id_entrega = item_rg["entregas"][0]["id"]
    # `listar_entregas` omite o caminho de propósito (não deve ir para o cliente HTTP),
    # então o caminho vem do registro completo.
    caminho_no_disco = Path(armazenamento.obter_entrega(id_entrega)["caminho"])
    checar(caminho_no_disco.exists(), "o arquivo está no disco antes de apagar")

    checar(armazenamento.excluir_entrega(id_entrega), "a entrega é removida")
    situacao = casos.montar_situacao(caso_id)
    item_rg = next(i for i in situacao["itens"] if i["codigo"] == "DOC.03")
    checar(item_rg["status"] == casos.PENDENTE, "DOC.03 volta a pendente", item_rg["status"])
    checar(not caminho_no_disco.exists(), "o arquivo sai do disco junto")

    # --------------------------------------------- identidade unificada (CIN)
    print("\n9. Uma CIN pode atender RG e CPF, mas só com a opção explícita")
    caso_cin = armazenamento.criar_caso("João da CIN", "acidente_trabalho_correios")
    categoria = categorias.ACIDENTE_TRABALHO_CORREIOS
    rg = next(i for i in categoria.itens if i.codigo == "DOC.03")
    checar(casos.tipo_confere(rg, "cin") is False, "sem a opção, CIN não substitui RG")

    extracao = extracao_falsa("cin")
    destino = armazenamento.DIR_ARQUIVOS / caso_cin["id"]
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "cin.png"
    caminho.write_bytes(b"cin-de-mentira")
    entrega_cin = armazenamento.registrar_entrega(
        caso_cin["id"],
        "DOC.03",
        "cin.png",
        caminho,
        extracao,
        casos.tipo_confere(rg, "cin", identidade_unificada=True),
        casos.itens_para_identidade_unificada(categoria, rg),
    )
    situacao_cin = casos.montar_situacao(caso_cin["id"])
    rg_cin = next(i for i in situacao_cin["itens"] if i["codigo"] == "DOC.03")
    cpf_cin = next(i for i in situacao_cin["itens"] if i["codigo"] == "DOC.04")
    checar(rg_cin["status"] == casos.ENTREGUE, "CIN atende o RG")
    checar(cpf_cin["status"] == casos.ENTREGUE, "CIN atende o CPF")
    checar(entrega_cin["itens_atendidos"] == ["DOC.03", "DOC.04"], "uma entrega referencia ambos")

    # O botão da tela também precisa consertar uma CIN que já havia sido enviada
    # somente no RG, sem exigir outro upload.
    caso_retroativo = armazenamento.criar_caso("Ana da CIN", "acidente_trabalho_correios")
    destino = armazenamento.DIR_ARQUIVOS / caso_retroativo["id"]
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "identidade-ja-enviada.png"
    caminho.write_bytes(b"cin-ja-enviada")
    entrega_antiga = armazenamento.registrar_entrega(
        caso_retroativo["id"], "DOC.03", "identidade-ja-enviada.png", caminho,
        extracao_falsa("rg"), False,
    )
    armazenamento.atualizar_para_identidade_unificada(
        entrega_antiga["id"], extracao_falsa("cin", utilizaveis=False),
        casos.itens_para_identidade_unificada(categoria, rg),
    )
    situacao_retroativa = casos.montar_situacao(caso_retroativo["id"])
    checar(
        all(next(i for i in situacao_retroativa["itens"] if i["codigo"] == codigo)["status"] == casos.ENTREGUE
            for codigo in ("DOC.03", "DOC.04")),
        "vinculação posterior conclui RG e CPF sem novo arquivo",
    )
    entrega_confirmada = armazenamento.obter_entrega(entrega_antiga["id"])
    checar(entrega_confirmada["confirmado_manual"], "vinculação fica identificada como manual")

    # ------------------------------------------------------ apagar tudo no fim
    print("\n10. Excluir o caso")
    pasta = armazenamento.DIR_ARQUIVOS / caso_id
    checar(armazenamento.excluir_caso(caso_id), "o caso é removido")
    checar(armazenamento.obter_caso(caso_id) is None, "some da listagem")
    checar(not pasta.exists(), "a pasta de arquivos do cliente é apagada")
    checar(casos.montar_situacao(caso_id) is None, "consultar caso apagado devolve None")

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
