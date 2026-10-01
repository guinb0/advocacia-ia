"""O que o cliente vê no link quando a falha é do sistema, e o reenvio do lote.

Sem banco: a visão do cliente e as pendências são puras, e o lote é exercitado
com o registro de cada arquivo substituído.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app import casos, duplicidade
from app.rotas import registro_documentos


def _item(codigo: str, status: str, entregas: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "codigo": codigo, "numero": int(codigo[-2:]), "nome": f"Documento {codigo}",
        "obrigatorio": True, "status": status, "observacao": "", "entregas": entregas,
    }


FALHA_NOSSA = _item("DOC.01", casos.CONFERIR, [{"status_proc": "erro", "erro_proc": "worker caiu"}])
FOTO_RUIM = _item("DOC.02", casos.CONFERIR, [{"status_proc": "pronto", "dados_utilizaveis": False}])
MISTO = _item("DOC.03", casos.CONFERIR, [
    {"status_proc": "erro"}, {"status_proc": "pronto", "tipo_confere": False},
])

SITUACAO = {
    "caso": {"cliente": "Cliente"},
    "categoria": {"nome": "Trabalhista"},
    "itens": [FALHA_NOSSA, FOTO_RUIM, MISTO],
    "triagem": [{"status_proc": "erro"}, {"status_proc": "na_fila"}],
    "progresso": {"obrigatorios_total": 3, "obrigatorios_entregues": 0,
                  "percentual_obrigatorios": 0, "pronto": False},
}


def test_falha_de_leitura_aparece_como_recebido_sem_pedir_reenvio():
    itens = {i["codigo"]: i for i in casos.visao_do_cliente(SITUACAO)["itens"]}
    assert itens["DOC.01"]["status"] == casos.RECEBIDO_EM_CONFERENCIA
    assert itens["DOC.01"]["motivo"] == ""


def test_leitura_concluida_com_ressalva_continua_pedindo_reenvio():
    itens = {i["codigo"]: i for i in casos.visao_do_cliente(SITUACAO)["itens"]}
    assert itens["DOC.02"]["status"] == casos.CONFERIR and itens["DOC.02"]["motivo"]
    assert itens["DOC.03"]["status"] == casos.CONFERIR and itens["DOC.03"]["motivo"]


def test_arquivo_da_triagem_com_falha_continua_em_analise():
    visao = casos.visao_do_cliente(SITUACAO)
    assert visao["em_analise"] == 2
    assert visao["processando"] == 1


def test_cobranca_nao_pede_o_que_so_falhou_na_leitura():
    nomes = {i["codigo"] for i in casos.documentos_pendentes_da_situacao(SITUACAO)}
    assert nomes == {"DOC.02", "DOC.03"}


class _Arquivo:
    def __init__(self, nome: str):
        self.filename = nome


def _lote(monkeypatch, **kwargs) -> dict[str, Any]:
    async def registrar(caso, item, arquivo, *a, **k):
        if arquivo.filename == "repetido.jpg":
            raise duplicidade.DocumentoDuplicado([], "Este arquivo já está no caso. Nada foi gravado.")
        return {"entrega": {"id": f"id-{arquivo.filename}"}}

    async def sem_zip(arquivos):
        return arquivos

    monkeypatch.setattr(registro_documentos, "_registrar_documento", registrar)
    monkeypatch.setattr(registro_documentos, "_expandir_zips", sem_zip)
    return asyncio.run(registro_documentos._registrar_lote(
        {"id": "c1"}, [_Arquivo("novo.jpg"), _Arquivo("repetido.jpg")], "pt", **kwargs,
    ))


def test_portal_conta_repetido_como_ja_recebido(monkeypatch):
    r = _lote(monkeypatch, repetido_conta_como_recebido=True)
    assert [x["arquivo"] for x in r["recebidos"]] == ["novo.jpg"]
    assert r["ja_recebidos"] == [{"arquivo": "repetido.jpg"}]
    assert r["recusados"] == []


def test_equipe_continua_vendo_o_repetido_como_recusado(monkeypatch):
    r = _lote(monkeypatch)
    assert "ja_recebidos" not in r
    assert [x["arquivo"] for x in r["recusados"]] == ["repetido.jpg"]


def test_lote_so_de_repetidos_no_portal_nao_e_erro(monkeypatch):
    async def registrar(*a, **k):
        raise duplicidade.DocumentoDuplicado([], "Já está no caso.")

    async def sem_zip(arquivos):
        return arquivos

    monkeypatch.setattr(registro_documentos, "_registrar_documento", registrar)
    monkeypatch.setattr(registro_documentos, "_expandir_zips", sem_zip)
    r = asyncio.run(registro_documentos._registrar_lote(
        {"id": "c1"}, [_Arquivo("a.jpg")], "pt", repetido_conta_como_recebido=True,
    ))
    assert r["recebidos"] == [] and r["ja_recebidos"] == [{"arquivo": "a.jpg"}]
