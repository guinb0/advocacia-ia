"""Cenário de aceite: glossário, classificação, reclassificação e duplicidade.

O roteiro é o da issue — criar um tipo, classificar um documento, reclassificá-lo e
tentar adicionar um documento identificado como duplicado — pela API de verdade
(`TestClient` sobre `app.main`), com a autenticação LIGADA para conferir quem pode
manter o glossário, e contra o SQL Server do `.env`. É o banco que diz se as tabelas
novas, a transação do histórico e as consultas de duplicidade funcionam; um banco
falso responderia o que o teste quisesse ouvir.

Simulados, e só estes: o OCR (`pipeline.processar`), o modelo de linguagem e o envio
ao agente jurídico. Tudo o que o cenário cria leva a marca `MARCA` e é apagado no
fim, passe ou falhe.

Não tem prefixo `test_` de propósito: o pytest o coletaria e rodaria contra o banco
em toda execução da suíte.

    .venv\\Scripts\\python.exe -m tests.cenario_glossario_duplicidade
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

from app import ambiente

ambiente.carregar()

from fastapi.testclient import TestClient  # noqa: E402

from app import (  # noqa: E402
    armazenamento,
    auth,
    banco,
    historico_alteracoes,
    indexacao_documento,
    main,
    pipeline,
    tipos_documento,
    valor_documento,
)
from app.celery_app import celery_app  # noqa: E402
from app.tasks import ocr as tarefa_ocr  # noqa: E402

MARCA = uuid.uuid4().hex[:8]

TEXTO_LAUDO = (
    "Laudo médico. Paciente atendido em consulta ortopédica apresenta lombalgia crônica "
    "com irradiação para o membro inferior esquerdo, iniciada após esforço repetitivo no "
    "posto de trabalho, com limitação funcional para carregar peso e permanecer em pé por "
    "longos períodos. Ressonância magnética evidencia protrusão discal em L4 L5. CID M51.1. "
    "Recomendo afastamento das atividades laborais por noventa dias."
)

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: Any = "") -> bool:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n        {str(detalhe)[:400]}" if detalhe != "" else ""))
    return condicao


def extracao_falsa(conteudo: bytes, nome: str, idioma: str, tipo_forcado=None, **_opcoes) -> dict:
    """O OCR simulado: `cpf*` é um cartão de CPF legível; o resto, um laudo sem campo."""
    validacao = {
        "veredito": "APROVADO",
        "dados_utilizaveis": True,
        "texto_utilizavel": True,
        "score_legibilidade": 95,
    }
    if nome.startswith("cpf"):
        return {
            "arquivo": nome,
            "tipo": {
                "codigo": "cpf",
                "detectado": "cpf",
                "descricao": "CPF",
                "descricao_detectado": "CPF",
                "confianca_classificacao": 30,
            },
            "campos": [
                {"nome": "cpf", "rotulo": "CPF", "valor": "529.982.247-25", "valido": True, "confianca": 0.99}
            ],
            "texto_completo": "MINISTERIO DA FAZENDA CADASTRO DE PESSOAS FISICAS 529.982.247-25",
            "validacao": validacao,
        }
    return {
        "arquivo": nome,
        "tipo": {
            "codigo": tipo_forcado or "desconhecido",
            "detectado": "desconhecido",
            "descricao": "Documento não identificado",
            "descricao_detectado": "Documento não identificado",
            "confianca_classificacao": 0,
        },
        "campos": [],
        "texto_completo": TEXTO_LAUDO,
        "texto_linhas": [{"texto": TEXTO_LAUDO, "confianca": 0.9}],
        "validacao": validacao,
    }


def sem_modelo(*_args, **_kwargs):
    raise valor_documento.ErroValor("modelo desligado no cenário")


def cabecalho(perfil: str) -> dict[str, str]:
    token = auth.gerar_token(
        codigo=f"cenario-{perfil}",
        nome=f"Cenário {perfil}",
        email=f"cenario-{perfil}@teste.local",
        perfil=perfil,
    )
    return {"Authorization": f"Bearer {token}"}


def enviar(cliente, quem, caso_id, item, nome, conteudo, confirmar=False):
    return cliente.post(
        f"/api/casos/{caso_id}/documentos",
        data={"item": item, "idioma": "pt", "confirmar_duplicidade": str(confirmar).lower()},
        files={"arquivo": (nome, conteudo, "application/pdf")},
        headers=quem,
    )


def item_de(situacao: dict, codigo: str) -> dict:
    return next(i for i in situacao["itens"] if i["codigo"] == codigo)


def ids_do_item(situacao: dict, codigo: str) -> list[str]:
    return [e["id"] for e in item_de(situacao, codigo)["entregas"]]


def limpar(caso_id: str | None, codigo_tipo: str | None) -> None:
    """Apaga o que o cenário criou. Roda mesmo se o cenário falhou no meio."""
    tabela_historico = historico_alteracoes._TABELA
    with banco.conectar() as con:
        if caso_id:
            # A correção aponta para o caso sem cascata: sai antes do caso.
            con.execute(
                "DELETE FROM classificacoes_documentos_corrigidas WHERE caso_id = ?", (caso_id,)
            )
            con.execute(f"DELETE FROM {tabela_historico} WHERE caso_id = ?", (caso_id,))
        if codigo_tipo:
            con.execute(
                f"DELETE FROM {tabela_historico} WHERE entidade = ? AND entidade_id = ?",
                (historico_alteracoes.ENTIDADE_TIPO_DOCUMENTO, codigo_tipo),
            )
            con.execute(f"DELETE FROM {tipos_documento._TABELA} WHERE codigo = ?", (codigo_tipo,))
    if caso_id:
        armazenamento.excluir_caso(caso_id)
    tipos_documento.limpar_cache()


def roteiro(cliente: TestClient, estado: dict[str, str | None]) -> None:
    gestor = cabecalho("advogado")
    sem_modulo = cabecalho("documentacao")

    print("\n1. Criar e manter um tipo no glossário")
    pedido = {
        "nome": f"Laudo de teste {MARCA}",
        "descricao": "Criado pelo cenário de aceite.",
        "sinonimos": ["laudo do cenário"],
    }
    r = cliente.post("/api/tipos-documento", json=pedido, headers=sem_modulo)
    checar(r.status_code == 403, "perfil sem o módulo não cria tipo", f"{r.status_code} {r.text}")

    r = cliente.post("/api/tipos-documento", json=pedido, headers=gestor)
    if not checar(r.status_code == 201, "gestor cria o tipo", f"{r.status_code} {r.text}"):
        return
    tipo = r.json()
    estado["codigo_tipo"] = codigo = tipo["codigo"]
    checar(codigo == f"laudo_de_teste_{MARCA}", "o código sai do nome", codigo)
    checar(tipo["sistema"] is False and tipo["versao"] == 1, "nasce do escritório, versão 1", tipo)

    edicao = {
        "nome": f"Laudo pericial de teste {MARCA}",
        "descricao": "Criado pelo cenário de aceite.",
        "sinonimos": ["laudo do cenário", "perícia do cenário"],
        "ativo": True,
        "versao": 1,
        "motivo": "nome mais preciso",
    }
    r = cliente.put(f"/api/tipos-documento/{codigo}", json=edicao, headers=sem_modulo)
    checar(r.status_code == 403, "perfil sem o módulo não edita", f"{r.status_code} {r.text}")
    r = cliente.put(f"/api/tipos-documento/{codigo}", json=edicao, headers=gestor)
    checar(
        r.status_code == 200 and r.json().get("versao") == 2,
        "gestor edita, e a versão sobe",
        f"{r.status_code} {r.text}",
    )
    r = cliente.put(
        f"/api/tipos-documento/{codigo}", json={**edicao, "nome": "Outro nome"}, headers=gestor
    )
    checar(r.status_code == 409, "edição feita sobre versão velha é recusada", f"{r.status_code} {r.text}")

    cat = cliente.get("/api/tipos-documento/cat", headers=gestor).json()
    r = cliente.put(
        "/api/tipos-documento/cat",
        json={
            "nome": cat["nome"],
            "descricao": cat["descricao"],
            "sinonimos": cat["sinonimos"],
            "ativo": False,
            "versao": cat["versao"],
        },
        headers=gestor,
    )
    checar(
        r.status_code == 409 and "checklist" in r.json().get("detail", ""),
        "tipo pedido por checklist não pode ser desativado",
        f"{r.status_code} {r.text}",
    )

    r = cliente.get(f"/api/tipos-documento/{codigo}/impacto", headers=gestor)
    checar(
        r.status_code == 200 and r.json()["documentos"] == 0 and r.json()["pode_desativar"],
        "o impacto de um tipo ainda sem uso é zero, e ele pode ser desativado",
        r.text,
    )
    eventos = cliente.get(f"/api/tipos-documento/{codigo}/historico", headers=gestor).json()["eventos"]
    checar(
        [e["acao"] for e in eventos] == ["editado", "criado"]
        and eventos[0]["antes"]["nome"] == pedido["nome"]
        and eventos[0]["motivo"] == "nome mais preciso"
        and eventos[0]["usuario"] == "Cenário advogado",
        "o histórico do tipo guarda quem, o antes e o motivo",
        eventos,
    )
    tipos_visiveis = cliente.get("/api/tipos-documento", headers=sem_modulo).json()["tipos"]
    checar(
        any(t["codigo"] == codigo for t in tipos_visiveis),
        "qualquer perfil interno consulta o glossário",
    )

    print("\n2. Classificar um documento")
    r = cliente.post(
        "/api/casos",
        data={"cliente": f"Cenário Glossário {MARCA} (apagar)", "categoria": "acidente_trabalho_geral"},
        headers=gestor,
    )
    if not checar(r.status_code == 201, "o caso de teste é criado", r.text):
        return
    estado["caso_id"] = caso_id = r.json()["id"]

    laudo = f"%PDF-1.7 laudo {MARCA}".encode()
    r = enviar(cliente, gestor, caso_id, "DOC.14", "laudo-1.pdf", laudo)
    if not checar(r.status_code == 201, "o laudo é enviado", f"{r.status_code} {r.text}"):
        return
    laudo_id = r.json()["entrega"]["id"]
    situacao = cliente.get(f"/api/casos/{caso_id}", headers=gestor).json()
    checar(laudo_id in ids_do_item(situacao, "DOC.14"), "o laudo entra no item de laudos médicos")
    checar(
        item_de(situacao, "DOC.14").get("tipo_documento") == "laudo_medico",
        "o item informa o tipo do glossário que pede",
        item_de(situacao, "DOC.14").get("tipo_documento"),
    )

    print("\n3. Reclassificar o documento")
    r = cliente.patch(
        f"/api/entregas/{laudo_id}/itens",
        json={"itens": ["DOC.15"], "tipo": "tipo_que_nao_existe"},
        headers=gestor,
    )
    checar(r.status_code == 400, "tipo fora do glossário é recusado", f"{r.status_code} {r.text}")

    r = cliente.patch(
        f"/api/entregas/{laudo_id}/itens",
        json={"itens": ["DOC.15"], "tipo": codigo, "motivo": "é relatório de perícia"},
        headers=gestor,
    )
    corpo = r.json()
    checar(
        r.status_code == 200
        and corpo.get("tipo_detectado") == codigo
        and corpo.get("itens_atendidos") == ["DOC.15"]
        and corpo.get("roteamento_origem") == "humano",
        "o documento passa ao novo item, com o tipo criado no glossário",
        f"{r.status_code} {str(corpo)[:300]}",
    )
    eventos = cliente.get(f"/api/entregas/{laudo_id}/historico", headers=gestor).json()["eventos"]
    ultimo = eventos[0] if eventos else {}
    checar(
        ultimo.get("acao") == "reclassificada"
        and ultimo["antes"]["tipo_documento"] == "laudo_medico"
        and ultimo["antes"]["itens_atendidos"] == ["DOC.14"]
        and ultimo["depois"]["tipo_documento"] == codigo
        and ultimo["depois"]["itens_atendidos"] == ["DOC.15"]
        and ultimo["usuario"] == "Cenário advogado"
        and ultimo["motivo"] == "é relatório de perícia",
        "o histórico do documento guarda antes, depois, quem e o motivo",
        ultimo,
    )
    impacto = cliente.get(f"/api/tipos-documento/{codigo}/impacto", headers=gestor).json()
    checar(impacto["documentos"] == 1, "o impacto do tipo passa a contar o documento", impacto)

    print("\n4. Tentar adicionar um documento duplicado")
    antes = len(armazenamento.listar_entregas(caso_id))
    r = enviar(cliente, gestor, caso_id, "DOC.14", "laudo-copia.pdf", laudo)
    corpo = r.json()
    checar(
        r.status_code == 409
        and corpo.get("codigo") == "DOCUMENTO_DUPLICADO"
        and corpo["duplicidades"][0]["entrega_id"] == laudo_id
        and corpo["duplicidades"][0]["regra"] == "identico",
        "arquivo idêntico é barrado, apontando o original",
        f"{r.status_code} {str(corpo)[:300]}",
    )
    checar(len(armazenamento.listar_entregas(caso_id)) == antes, "e nada foi gravado")

    r = enviar(cliente, gestor, caso_id, "DOC.14", "laudo-copia.pdf", laudo, confirmar=True)
    if checar(r.status_code == 201, "a equipe pode insistir, confirmando", f"{r.status_code} {r.text}"):
        copia_id = r.json()["entrega"]["id"]
        eventos = cliente.get(f"/api/entregas/{copia_id}/historico", headers=gestor).json()["eventos"]
        checar(
            eventos and eventos[0]["acao"] == "duplicidade_confirmada"
            and eventos[0]["depois"]["duplicidades"][0]["entrega_id"] == laudo_id,
            "a confirmação fica no histórico da cópia",
            eventos,
        )
        situacao = cliente.get(f"/api/casos/{caso_id}", headers=gestor).json()
        checar(
            copia_id in ids_do_item(situacao, "DOC.14"),
            "e a cópia confirmada não é segurada de novo na leitura",
        )
        r = cliente.delete(f"/api/entregas/{copia_id}", headers=gestor)
        eventos = cliente.get(f"/api/entregas/{copia_id}/historico", headers=gestor).json()["eventos"]
        checar(
            r.status_code == 200 and eventos and eventos[0]["acao"] == "removida"
            and eventos[0]["antes"]["arquivo"] == "laudo-copia.pdf",
            "remover a cópia deixa rastro, mesmo sem o documento",
            eventos,
        )

    r = enviar(cliente, gestor, caso_id, "DOC.04", "cpf-frente.pdf", f"%PDF cpf 1 {MARCA}".encode())
    cpf1_id = r.json()["entrega"]["id"] if r.status_code == 201 else ""
    r = enviar(cliente, gestor, caso_id, "DOC.04", "cpf-outra-foto.pdf", f"%PDF cpf 2 {MARCA}".encode())
    checar(r.status_code == 201, "outra foto do mesmo CPF (bytes diferentes) é recebida", r.text)
    cpf2_id = r.json()["entrega"]["id"] if r.status_code == 201 else ""
    situacao = cliente.get(f"/api/casos/{caso_id}", headers=gestor).json()
    na_triagem = {e["id"]: e for e in situacao.get("triagem") or []}
    segurada = na_triagem.get(cpf2_id, {})
    checar(
        cpf1_id in ids_do_item(situacao, "DOC.04")
        and segurada.get("roteamento_origem") == "duplicidade"
        and any("CPF" in a for a in segurada.get("alertas") or []),
        "depois da leitura, a segunda foto fica na triagem pelo mesmo número de CPF",
        segurada or situacao.get("triagem"),
    )

    r = cliente.patch(f"/api/entregas/{cpf2_id}/itens", json={"itens": ["DOC.04"]}, headers=gestor)
    corpo = r.json()
    checar(
        r.status_code == 409
        and any(
            d["entrega_id"] == cpf1_id and d["regra"] == "mesmo_numero"
            for d in corpo.get("duplicidades", [])
        ),
        "atribuí-la ao item pede confirmação, apontando o CPF já entregue",
        f"{r.status_code} {str(corpo)[:300]}",
    )
    situacao = cliente.get(f"/api/casos/{caso_id}", headers=gestor).json()
    checar(
        any(e["id"] == cpf2_id for e in situacao.get("triagem") or []),
        "sem confirmação, o documento continua na triagem",
    )
    r = cliente.patch(
        f"/api/entregas/{cpf2_id}/itens",
        json={"itens": ["DOC.04"], "confirmar_duplicidade": True, "motivo": "foto mais nítida"},
        headers=gestor,
    )
    eventos = cliente.get(f"/api/entregas/{cpf2_id}/historico", headers=gestor).json()["eventos"]
    checar(
        r.status_code == 200
        and eventos
        and eventos[0]["acao"] == "reclassificada"
        and eventos[0]["depois"].get("duplicidades_confirmadas"),
        "com confirmação conclui, e o histórico registra a duplicidade aceita",
        f"{r.status_code} {eventos[:1]}",
    )

    lote_bytes = f"%PDF lote {MARCA}".encode()
    r = cliente.post(
        f"/api/casos/{caso_id}/documentos/lote",
        files=[
            ("arquivos", ("lote-a.pdf", lote_bytes, "application/pdf")),
            ("arquivos", ("lote-b.pdf", lote_bytes, "application/pdf")),
        ],
        headers=gestor,
    )
    corpo = r.json()
    checar(
        r.status_code == 201
        and len(corpo.get("recebidos", [])) == 1
        and len(corpo.get("recusados", [])) == 1
        and "já está no caso" in corpo["recusados"][0]["motivo"],
        "no envio em lote, o arquivo repetido dentro do próprio lote é recusado com o motivo",
        corpo,
    )


def main_cenario() -> int:
    estado: dict[str, str | None] = {"caso_id": None, "codigo_tipo": None}
    eager = celery_app.conf.task_always_eager
    propaga = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        with (
            patch.object(main, "_tentar_aquecer"),
            patch.object(auth, "ATIVA", True),
            patch.object(auth, "JWT_SECRET", auth.JWT_SECRET or f"cenario-{MARCA}"),
            # O perfil vem do token: as contas do cenário não existem no banco.
            patch.object(auth, "_papeis_atuais", lambda usuario: tuple(sorted(usuario.papeis))),
            patch.object(pipeline, "processar", extracao_falsa),
            patch.object(valor_documento, "ler", sem_modelo),
            patch.object(indexacao_documento, "classificar", sem_modelo),
            patch.object(tarefa_ocr, "_entregar_ao_agente", lambda *a, **k: None),
            patch.object(main, "_entregar_ao_agente", lambda *a, **k: None),
            TestClient(main.app) as cliente,
        ):
            roteiro(cliente, estado)
    finally:
        celery_app.conf.task_always_eager = eager
        celery_app.conf.task_eager_propagates = propaga
        try:
            limpar(estado["caso_id"], estado["codigo_tipo"])
            print("\nLimpeza: caso, documentos, tipo e histórico do cenário apagados.")
        except Exception as exc:  # noqa: BLE001 - relatar, sem esconder o resultado
            print(
                f"\nLIMPEZA FALHOU ({exc}). Apague à mão: caso {estado['caso_id']}, "
                f"tipo {estado['codigo_tipo']}."
            )

    print(f"\n{'CENÁRIO PASSOU' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_cenario())
