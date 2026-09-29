"""Catálogo de tipos de caso: as ações que o escritório aceita e o checklist de cada uma.

O PROBLEMA QUE ISTO RESOLVE

O glossário (`app/tipos_documento.py`) já deixava o escritório criar um tipo de
DOCUMENTO pela tela. O tipo de CASO, não: as cinco ações moravam escritas à mão em
`app/categorias.py`, e criar a sexta era trabalho de programador — editar o checklist,
as pistas da triagem, o prompt do modelo e subir o servidor. Enquanto isso, a ação nova
não existia em lugar nenhum: não aparecia na criação do caso, a triagem enquadrava o
relato numa das cinco antigas e o cliente recebia o checklist errado.

Aqui o tipo de caso é cadastro. Quem tem o módulo `tipos_caso` cria a ação, monta o
checklist escolhendo tipos do glossário e escreve as pistas que a triagem usa — e o
caso novo já nasce com o checklist certo.

O QUE PODE MUDAR E O QUE NÃO PODE

- `codigo` é imutável. Ele fica gravado em `casos.categoria`, nas críticas e nas skills
  de petição por categoria; trocá-lo deixaria esses registros órfãos.
- `nome` e `descricao` mudam à vontade: o caso guarda o código, não o nome.
- O checklist muda, e a mudança alcança os casos JÁ ABERTOS — é o mesmo comportamento
  dos itens que o glossário acrescenta. Item que já tem documento entregue não é
  removido: a entrega ficaria presa a um item que a tela não mostra mais.
- O código de cada item (`DOC.NN`) nunca é reaproveitado. Ele fica gravado em
  `entregas.item_codigo`; se remover o item 3 renumerasse os seguintes, os documentos
  do antigo item 4 passariam a responder pelo 3. Por isso `proximo_item` só cresce, e
  `numero` — a ordem na tela — é outra coisa, recalculada a cada gravação.
- Desativar tira a ação da criação de casos e da triagem. Os casos que já a usam
  continuam com ela, com o mesmo checklist: `obter` devolve tipo desativado de
  propósito.
- Apagar não existe, pela mesma razão do glossário: levaria junto o significado dos
  casos que a usam.

OS CINCO DO CÓDIGO

As ações escritas em `app/categorias.py` entram aqui como linhas de sistema. Delas só
`ativo` é editável — o checklist continua sendo o do escritório, conferido contra o
`.docx` original por `tests/test_categorias.py`. Poder desligar uma delas resolve um
problema real (o escritório que parou de aceitar assalto a carteiro) sem abrir a porta
para o cadastro divergir do documento assinado.

QUEM MANTÉM

Criar e editar exige o módulo `tipos_caso` (ver `app/perfis.py`), de fábrica com o
Advogado e o Secretário — os mesmos que mantêm o glossário. Consultar é livre: a
criação do caso e a triagem precisam da lista.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import auth, categorias
from . import historico_alteracoes as historico
from . import tipos_documento
from .banco import PREFIXO, SCHEMA, conectar, sessao
from .cache_leitura import por_alguns_segundos
from .extractors import normalizar

log = logging.getLogger("tipos_caso")

#: Módulo da matriz de acesso que libera criar e editar. Consultar não exige.
MODULO = "tipos_caso"

LIMITE_NOME = 120
LIMITE_DESCRICAO = 600
LIMITE_QUANDO_USAR = 1200
LIMITE_ITEM_NOME = 160
LIMITE_OBSERVACAO = 600
LIMITE_PISTA = 80
MAXIMO_ITENS = 80
MAXIMO_PISTAS = 40
#: Faixa de peso de uma pista da triagem. O catálogo do código usa de 3 a 14; acima de
#: 20 uma única palavra decidiria a categoria sozinha, que é o que os desempates evitam.
PESO_MINIMO = 1
PESO_MAXIMO = 20

#: O mesmo formato do glossário: minúsculas, números e `_`, começando por letra.
RE_CODIGO = re.compile(r"^[a-z][a-z0-9_]{1,59}$")

_TABELA = f"{SCHEMA}.{PREFIXO}tipos_caso"
_TABELA_ITENS = f"{SCHEMA}.{PREFIXO}tipos_caso_itens"

_COLUNAS = (
    "codigo, nome, descricao, quando_usar, pistas, ativo, sistema, proximo_item, "
    "versao, criado_em, criado_por, atualizado_em, atualizado_por"
)


class ErroTipoCaso(ValueError):
    """Pedido recusado. `status` é o código HTTP que a rota devolve."""

    status = 400


class TipoCasoNaoEncontrado(ErroTipoCaso):
    status = 404


class ConflitoTipoCaso(ErroTipoCaso):
    status = 409


ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    codigo         varchar(60)    NOT NULL CONSTRAINT pk_acervo_tipos_caso PRIMARY KEY,
    nome           nvarchar(120)  NOT NULL CONSTRAINT uq_acervo_tipos_caso_nome UNIQUE,
    descricao      nvarchar(600)  NOT NULL CONSTRAINT df_acervo_tipos_caso_desc DEFAULT N'',
    quando_usar    nvarchar(1200) NOT NULL CONSTRAINT df_acervo_tipos_caso_quando DEFAULT N'',
    pistas         nvarchar(max)  NOT NULL CONSTRAINT df_acervo_tipos_caso_pistas DEFAULT N'[]',
    ativo          bit            NOT NULL CONSTRAINT df_acervo_tipos_caso_ativo DEFAULT 1,
    sistema        bit            NOT NULL CONSTRAINT df_acervo_tipos_caso_sis DEFAULT 0,
    proximo_item   int            NOT NULL CONSTRAINT df_acervo_tipos_caso_prox DEFAULT 1,
    versao         int            NOT NULL CONSTRAINT df_acervo_tipos_caso_versao DEFAULT 1,
    criado_em      varchar(40)    NOT NULL,
    criado_por     nvarchar(200)  NOT NULL CONSTRAINT df_acervo_tipos_caso_cpor DEFAULT N'',
    atualizado_em  varchar(40)    NOT NULL,
    atualizado_por nvarchar(200)  NOT NULL CONSTRAINT df_acervo_tipos_caso_apor DEFAULT N''
);
IF OBJECT_ID('{_TABELA_ITENS}') IS NULL
CREATE TABLE {_TABELA_ITENS} (
    tipo_codigo    varchar(60)   NOT NULL,
    codigo         varchar(20)   NOT NULL,
    numero         int           NOT NULL,
    nome           nvarchar(160) NOT NULL,
    obrigatorio    bit           NOT NULL CONSTRAINT df_acervo_tipos_caso_it_obr DEFAULT 0,
    tipo_documento varchar(60)   NULL,
    observacao     nvarchar(600) NOT NULL CONSTRAINT df_acervo_tipos_caso_it_obs DEFAULT N'',
    CONSTRAINT pk_acervo_tipos_caso_itens PRIMARY KEY (tipo_codigo, codigo),
    CONSTRAINT fk_acervo_tipos_caso_itens_tipo FOREIGN KEY (tipo_codigo)
        REFERENCES {_TABELA} (codigo)
)
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _espacos(texto: Any) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


# ----------------------------------------------------------------- validação


def validar_nome(nome: Any) -> str:
    limpo = _espacos(nome)
    if len(limpo) < 2:
        raise ErroTipoCaso("Informe o nome do tipo de caso.")
    if len(limpo) > LIMITE_NOME:
        raise ErroTipoCaso(f"O nome passa de {LIMITE_NOME} caracteres.")
    return limpo


def validar_codigo(codigo: Any) -> str:
    limpo = str(codigo or "").strip()
    if not RE_CODIGO.match(limpo):
        raise ErroTipoCaso(
            "Código inválido: use de 2 a 60 letras minúsculas, números ou _, "
            "começando por letra (ex.: acidente_transporte)."
        )
    return limpo


def _texto(valor: Any, limite: int, rotulo: str) -> str:
    limpo = _espacos(valor)
    if len(limpo) > limite:
        raise ErroTipoCaso(f"{rotulo} passa de {limite} caracteres.")
    return limpo


def gerar_codigo(nome: str) -> str:
    """Código a partir do nome: "Acidente de transporte" vira `acidente_de_transporte`."""
    base = re.sub(r"[^a-z0-9]+", "_", normalizar(nome).lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"caso_{base}".rstrip("_")
    return base[:60].rstrip("_")


def normalizar_pistas(bruto: Any) -> list[dict[str, Any]]:
    """As expressões que a triagem procura no relato, com o peso de cada uma.

    Aceita a lista de objetos da tela e também texto solto separado por vírgula ou
    linha — quem está cadastrando costuma colar uma lista de palavras. Sem peso, vale
    um peso médio: é melhor a pista contar pouco do que não existir.
    """
    if isinstance(bruto, str):
        bruto = re.split(r"[,\n]", bruto)
    vistas: set[str] = set()
    saida: list[dict[str, Any]] = []
    for item in bruto or []:
        if isinstance(item, dict):
            expressao = _espacos(item.get("expressao"))
            peso_bruto = item.get("peso", 6)
        else:
            expressao = _espacos(item)
            peso_bruto = 6
        if not expressao:
            continue
        if len(expressao) > LIMITE_PISTA:
            raise ErroTipoCaso(
                f"A pista “{expressao[:30]}…” passa de {LIMITE_PISTA} caracteres."
            )
        try:
            peso = int(peso_bruto)
        except (TypeError, ValueError):
            raise ErroTipoCaso(f"O peso da pista “{expressao}” não é um número.") from None
        if not PESO_MINIMO <= peso <= PESO_MAXIMO:
            raise ErroTipoCaso(
                f"O peso da pista “{expressao}” precisa ficar entre "
                f"{PESO_MINIMO} e {PESO_MAXIMO}."
            )
        chave = normalizar(expressao)
        if chave in vistas:
            continue
        vistas.add(chave)
        saida.append({"expressao": expressao, "peso": peso})
    if len(saida) > MAXIMO_PISTAS:
        raise ErroTipoCaso(f"São aceitas até {MAXIMO_PISTAS} pistas por tipo de caso.")
    return saida


def validar_itens(bruto: Any) -> list[dict[str, Any]]:
    """O checklist pedido pela tela, conferido contra o glossário.

    O código de cada item NÃO vem daqui: item que já existe traz o seu, e item novo
    recebe um na gravação (ver `_gravar_itens`). A tela não inventa código porque o
    código é o que amarra a entrega ao item.
    """
    conhecidos = tipos_documento.codigos_conhecidos()
    itens: list[dict[str, Any]] = []
    for posicao, bruta in enumerate(bruto or [], start=1):
        if not isinstance(bruta, dict):
            raise ErroTipoCaso("Item de checklist inválido.")
        nome = _espacos(bruta.get("nome"))
        if not nome:
            raise ErroTipoCaso(f"O item {posicao} do checklist está sem nome.")
        if len(nome) > LIMITE_ITEM_NOME:
            raise ErroTipoCaso(
                f"O nome do item “{nome[:30]}…” passa de {LIMITE_ITEM_NOME} caracteres."
            )
        tipo = str(bruta.get("tipo_documento") or "").strip() or None
        if tipo is not None and tipo not in conhecidos:
            raise ErroTipoCaso(
                f"O item “{nome}” aponta para o tipo de documento “{tipo}”, que não "
                "está no glossário. Cadastre-o antes, ou deixe o item sem tipo."
            )
        itens.append(
            {
                "codigo": str(bruta.get("codigo") or "").strip(),
                "numero": posicao,
                "nome": nome,
                "obrigatorio": bool(bruta.get("obrigatorio")),
                "tipo_documento": tipo,
                "observacao": _texto(
                    bruta.get("observacao"), LIMITE_OBSERVACAO, "A observação do item"
                ),
            }
        )
    if len(itens) > MAXIMO_ITENS:
        raise ErroTipoCaso(f"São aceitos até {MAXIMO_ITENS} itens por checklist.")
    return itens


# ------------------------------------------------------------------ leitura


def _pistas_de(bruto: Any) -> list[dict[str, Any]]:
    try:
        valor = json.loads(bruto or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(valor, list):
        return []
    return [
        {"expressao": str(p.get("expressao") or ""), "peso": int(p.get("peso") or 0)}
        for p in valor
        if isinstance(p, dict) and p.get("expressao")
    ]


def _registro(linha: Any, itens: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "codigo": str(linha["codigo"]),
        "nome": linha["nome"],
        "descricao": linha["descricao"] or "",
        "quando_usar": linha["quando_usar"] or "",
        "pistas": _pistas_de(linha["pistas"]),
        "ativo": bool(linha["ativo"]),
        "sistema": bool(linha["sistema"]),
        "versao": int(linha["versao"]),
        "criado_em": linha["criado_em"],
        "criado_por": linha["criado_por"] or "",
        "atualizado_em": linha["atualizado_em"],
        "atualizado_por": linha["atualizado_por"] or "",
        "itens": itens,
        "total_obrigatorios": sum(1 for i in itens if i["obrigatorio"]),
    }


def _item(linha: Any) -> dict[str, Any]:
    return {
        "codigo": str(linha["codigo"]),
        "numero": int(linha["numero"]),
        "nome": linha["nome"],
        "obrigatorio": bool(linha["obrigatorio"]),
        "tipo_documento": linha["tipo_documento"] or None,
        "observacao": linha["observacao"] or "",
    }


def _itens_no_banco(con: Any, codigo: str) -> list[dict[str, Any]]:
    linhas = con.execute(
        f"""
        SELECT codigo, numero, nome, obrigatorio, tipo_documento, observacao
          FROM {_TABELA_ITENS} WHERE tipo_codigo = ? ORDER BY numero, codigo
        """,
        (codigo,),
    ).fetchall()
    return [_item(linha) for linha in linhas]


def listar(incluir_inativos: bool = False) -> list[dict[str, Any]]:
    """O catálogo inteiro — os do código e os criados pelo escritório."""
    filtro = "" if incluir_inativos else " WHERE ativo = 1"
    with conectar() as con:
        linhas = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA}{filtro} ORDER BY sistema DESC, nome"
        ).fetchall()
        return [_registro(linha, _itens_no_banco(con, str(linha["codigo"]))) for linha in linhas]


def obter(codigo: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if linha is None:
            return None
        return _registro(linha, _itens_no_banco(con, codigo))


# ------------------------------------------- o que `app/categorias.py` consome


def _como_categoria(registro: dict[str, Any]) -> categorias.Categoria:
    """O registro do banco no mesmo formato das categorias escritas no código.

    É isto que faz o resto do Acervo — checklist, dossiê, petição — não precisar saber
    se a ação nasceu em `categorias.py` ou na tela.
    """
    return categorias.Categoria(
        codigo=registro["codigo"],
        nome=registro["nome"],
        descricao=registro["descricao"],
        itens=tuple(
            categorias.ItemChecklist(
                codigo=item["codigo"],
                numero=item["numero"],
                nome=item["nome"],
                obrigatorio=item["obrigatorio"],
                tipo=item["tipo_documento"],
                observacao=item["observacao"],
            )
            for item in registro["itens"]
        ),
    )


@por_alguns_segundos(30, maximo=2)
def _catalogo_em_cache() -> tuple[dict[str, Any], ...]:
    return tuple(listar(incluir_inativos=True))


def limpar_cache() -> None:
    _catalogo_em_cache.limpar_cache()  # type: ignore[attr-defined]


def _catalogo() -> tuple[dict[str, Any], ...]:
    """Todo o cadastro, inclusive o desativado.

    Com o banco fora do ar, nada: `app/categorias.py` cai no catálogo do código, que é
    o piso. Um Acervo sem os tipos criados ainda atende os casos das cinco ações; um
    Acervo que estoura ao listar categorias não atende nenhuma.
    """
    try:
        return _catalogo_em_cache()
    except Exception:  # noqa: BLE001 - leitura auxiliar; o catálogo do código é o piso
        log.warning("Catálogo de tipos de caso indisponível.", exc_info=True)
        return ()


def criados() -> dict[str, categorias.Categoria]:
    """As ações criadas pelo escritório, por código — sem as linhas de sistema."""
    return {
        registro["codigo"]: _como_categoria(registro)
        for registro in _catalogo()
        if not registro["sistema"]
    }


def desativados() -> set[str]:
    """Os códigos desligados, do código ou criados aqui."""
    return {registro["codigo"] for registro in _catalogo() if not registro["ativo"]}


def pistas_de_triagem() -> dict[str, list[tuple[str, int]]]:
    """As pistas das ações ATIVAS, no formato que `app/triagem.py` pontua.

    Desativada não entra: a triagem não pode sugerir uma ação que a criação do caso
    não oferece mais.
    """
    return {
        registro["codigo"]: [
            (normalizar(p["expressao"]), int(p["peso"])) for p in registro["pistas"]
        ]
        for registro in _catalogo()
        if registro["ativo"] and not registro["sistema"] and registro["pistas"]
    }


def descricoes_para_o_modelo() -> list[tuple[str, str, str]]:
    """(código, nome, quando usar) das ações criadas e ativas, para o prompt da triagem.

    Sem isto o modelo enquadraria o relato numa das cinco do código, que são as únicas
    que a instrução dele descreve — e o caso novo nasceria com o checklist errado.
    """
    return [
        (registro["codigo"], registro["nome"], registro["quando_usar"] or registro["descricao"])
        for registro in _catalogo()
        if registro["ativo"] and not registro["sistema"]
    ]


# ------------------------------------------------------------------ escrita


def _recusar_nome_repetido(con: Any, nome: str, ignorar: str | None) -> None:
    chave = normalizar(nome)
    for linha in con.execute(f"SELECT codigo, nome FROM {_TABELA}").fetchall():
        if linha["codigo"] != ignorar and normalizar(linha["nome"]) == chave:
            raise ConflitoTipoCaso(
                f"Já existe o tipo de caso “{linha['nome']}” ({linha['codigo']}). "
                "Use-o, ou escolha outro nome."
            )


def _casos_no_item(con: Any, codigo_tipo: str, codigo_item: str) -> int:
    """Documentos já entregues neste item do checklist.

    `itens_atendidos` é JSON (`["DOC.03"]`); `[`, `_` e `%` escapados para o LIKE, como
    em `tipos_documento._documentos_no_item`.
    """
    literal = codigo_item.replace("[", "[[]").replace("_", "[_]").replace("%", "[%]")
    linha = con.execute(
        """
        SELECT COUNT(DISTINCT e.id) AS total_documentos
          FROM entregas e
          JOIN casos c ON c.id = e.caso_id
         WHERE c.categoria = ?
           AND (e.item_codigo = ? OR e.itens_atendidos LIKE ?)
        """,
        (codigo_tipo, codigo_item, f'%"{literal}"%'),
    ).fetchone()
    return int(linha["total_documentos"] or 0)


def _recusar_remocao_com_documentos(
    con: Any, codigo: str, antes: list[dict[str, Any]], depois: list[dict[str, Any]]
) -> None:
    mantidos = {i["codigo"] for i in depois if i["codigo"]}
    for item in antes:
        if item["codigo"] in mantidos:
            continue
        total = _casos_no_item(con, codigo, item["codigo"])
        if total:
            raise ConflitoTipoCaso(
                f"“{item['nome']}” não pode sair do checklist: {total} documento(s) já "
                "foram entregues neste item e ficariam sem lugar. Renomeie o item, ou "
                "reclassifique os documentos antes."
            )


def _gravar_itens(
    con: Any, codigo: str, antes: list[dict[str, Any]], depois: list[dict[str, Any]], proximo: int
) -> int:
    """Aplica o checklist novo e devolve o próximo código de item livre.

    Item sem código é novo e ganha o próximo `DOC.NN` nunca usado — inclusive quando um
    item com aquele número foi removido antes. Reaproveitar código faria os documentos
    do item antigo reaparecerem no item novo.
    """
    conhecidos = {i["codigo"] for i in antes}
    mantidos: set[str] = set()
    for item in depois:
        if item["codigo"] and item["codigo"] in conhecidos:
            mantidos.add(item["codigo"])
            con.execute(
                f"""
                UPDATE {_TABELA_ITENS}
                   SET numero = ?, nome = ?, obrigatorio = ?, tipo_documento = ?,
                       observacao = ?
                 WHERE tipo_codigo = ? AND codigo = ?
                """,
                (
                    item["numero"],
                    item["nome"],
                    int(item["obrigatorio"]),
                    item["tipo_documento"],
                    item["observacao"],
                    codigo,
                    item["codigo"],
                ),
            )
        else:
            novo = f"DOC.{proximo:02d}"
            proximo += 1
            item["codigo"] = novo
            mantidos.add(novo)
            con.execute(
                f"""
                INSERT INTO {_TABELA_ITENS}
                    (tipo_codigo, codigo, numero, nome, obrigatorio, tipo_documento, observacao)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    codigo,
                    novo,
                    item["numero"],
                    item["nome"],
                    int(item["obrigatorio"]),
                    item["tipo_documento"],
                    item["observacao"],
                ),
            )
    for item in antes:
        if item["codigo"] not in mantidos:
            con.execute(
                f"DELETE FROM {_TABELA_ITENS} WHERE tipo_codigo = ? AND codigo = ?",
                (codigo, item["codigo"]),
            )
    return proximo


def _itens_no_retrato(itens: list[dict[str, Any]]) -> list[str]:
    """Uma linha por item, na ordem do checklist. `*` marca o obrigatório."""
    return [f"{i['codigo']} {i['nome']}{' *' if i['obrigatorio'] else ''}" for i in itens]


def _estado(registro: dict[str, Any]) -> dict[str, Any]:
    """Tudo o que a edição pode mudar, sem perder nada — para saber SE mudou algo.

    Não serve o retrato acima: ali um item vira "DOC.03 RG *", e trocar o tipo do
    glossário dele, a observação ou a ordem não mudaria uma letra. Comparar por ele
    faria a edição ser devolvida como "nada a fazer", em silêncio.
    """
    return {
        "nome": registro["nome"],
        "descricao": registro["descricao"],
        "quando_usar": registro["quando_usar"],
        "pistas": [(p["expressao"], p["peso"]) for p in registro["pistas"]],
        "ativo": bool(registro["ativo"]),
        "itens": [
            (
                i["codigo"],
                i["numero"],
                i["nome"],
                bool(i["obrigatorio"]),
                i["tipo_documento"],
                i["observacao"],
            )
            for i in registro["itens"]
        ],
    }


def _retrato(registro: dict[str, Any]) -> dict[str, Any]:
    """O que o histórico guarda: só o que a edição pode mudar."""
    return {
        "nome": registro["nome"],
        "descricao": registro["descricao"],
        "quando_usar": registro["quando_usar"],
        "pistas": [f"{p['expressao']} ({p['peso']})" for p in registro["pistas"]],
        "ativo": bool(registro["ativo"]),
        "itens": _itens_no_retrato(registro["itens"]),
    }


def inicializar() -> None:
    """Cria as tabelas e registra as ações do código. Idempotente.

    As linhas de sistema existem para guardar `ativo` e para reservar o nome: sem elas,
    alguém criaria "Acidente do Trabalho (Correios)" de novo, com outro código, e o
    escritório passaria a ver a mesma ação duas vezes na criação do caso.
    """
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)

    agora = _agora()
    with conectar() as con:
        existentes = {
            str(linha["codigo"]): linha
            for linha in con.execute(f"SELECT codigo, nome FROM {_TABELA}").fetchall()
        }
        for codigo, categoria in categorias.CATEGORIAS.items():
            if codigo == categorias.CATEGORIA_EM_TRIAGEM.codigo:
                # Sentinela, não ação: não se escolhe "em análise" ao abrir um caso.
                continue
            if codigo in existentes:
                if existentes[codigo]["nome"] != categoria.nome:
                    # O nome mudou no código: a linha acompanha, senão a trava de nome
                    # repetido passaria a guardar um nome que não existe mais.
                    con.execute(
                        f"UPDATE {_TABELA} SET nome = ?, descricao = ? WHERE codigo = ?",
                        (categoria.nome, categoria.descricao, codigo),
                    )
                continue
            try:
                con.execute(
                    f"""
                    INSERT INTO {_TABELA} ({_COLUNAS})
                    VALUES (?, ?, ?, N'', N'[]', ?, 1, 1, 1, ?, N'sistema', ?, N'sistema')
                    """,
                    (
                        codigo,
                        categoria.nome,
                        categoria.descricao,
                        int(codigo in categorias._CATEGORIAS_ATIVAS),
                        agora,
                        agora,
                    ),
                )
            except Exception:  # noqa: BLE001 - uma ação recusada não impede as demais
                log.warning(
                    "Tipo de caso de sistema %r não entrou no catálogo (nome já usado?).",
                    codigo,
                    exc_info=True,
                )
    limpar_cache()


def criar(
    *,
    nome: str,
    usuario: str,
    codigo: str | None = None,
    descricao: str = "",
    quando_usar: str = "",
    pistas: Any = (),
    itens: Any = (),
) -> dict[str, Any]:
    nome_limpo = validar_nome(nome)
    codigo_limpo = validar_codigo(
        codigo if str(codigo or "").strip() else gerar_codigo(nome_limpo)
    )
    descricao_limpa = _texto(descricao, LIMITE_DESCRICAO, "A descrição")
    quando_limpo = _texto(quando_usar, LIMITE_QUANDO_USAR, "O texto de “quando usar”")
    lista_pistas = normalizar_pistas(pistas)
    lista_itens = validar_itens(itens)
    quem = (_espacos(usuario) or "escritório")[:200]
    agora = _agora()

    if codigo_limpo in categorias.CATEGORIAS:
        # Trava independente da semente: com o mesmo código, a ação criada aqui
        # SUBSTITUIRIA a do código em `categorias.catalogo()`, e o checklist conferido
        # contra o .docx sumiria sem aviso. O `em_triagem`, que não é ação e por isso
        # não vira linha de sistema, também entra nesta lista.
        raise ConflitoTipoCaso(
            f"O código “{codigo_limpo}” já é de uma ação do sistema. Escolha outro."
        )

    with sessao() as con:
        if con.execute(
            f"SELECT 1 AS existe FROM {_TABELA} WHERE codigo = ?", (codigo_limpo,)
        ).fetchone():
            raise ConflitoTipoCaso(
                f"Já existe um tipo de caso com o código “{codigo_limpo}”. Se ele está "
                "desativado, reative-o em vez de criar outro."
            )
        _recusar_nome_repetido(con, nome_limpo, ignorar=None)
        con.execute(
            f"""
            INSERT INTO {_TABELA} ({_COLUNAS})
            VALUES (?, ?, ?, ?, ?, 1, 0, 1, 1, ?, ?, ?, ?)
            """,
            (
                codigo_limpo,
                nome_limpo,
                descricao_limpa,
                quando_limpo,
                json.dumps(lista_pistas, ensure_ascii=False),
                agora,
                quem,
                agora,
                quem,
            ),
        )
        proximo = _gravar_itens(con, codigo_limpo, [], lista_itens, 1)
        con.execute(
            f"UPDATE {_TABELA} SET proximo_item = ? WHERE codigo = ?", (proximo, codigo_limpo)
        )
        historico.registrar(
            historico.ENTIDADE_TIPO_CASO,
            codigo_limpo,
            "criado",
            usuario=quem,
            depois=_retrato(
                {
                    "nome": nome_limpo,
                    "descricao": descricao_limpa,
                    "quando_usar": quando_limpo,
                    "pistas": lista_pistas,
                    "ativo": True,
                    "itens": lista_itens,
                }
            ),
        )
    limpar_cache()
    return obter(codigo_limpo) or {}


def editar(
    codigo: str,
    *,
    nome: str,
    descricao: str,
    quando_usar: str,
    pistas: Any,
    itens: Any,
    ativo: bool,
    versao: int,
    usuario: str,
    motivo: str = "",
) -> dict[str, Any]:
    """Aplica a edição, se ninguém tiver editado o mesmo tipo no meio do caminho.

    `versao` é a que a tela tinha ao abrir o formulário — a mesma trava do glossário,
    pela mesma razão: sem ela a segunda pessoa a salvar apagaria a alteração da
    primeira sem que nenhuma das duas soubesse.
    """
    nome_limpo = validar_nome(nome)
    descricao_limpa = _texto(descricao, LIMITE_DESCRICAO, "A descrição")
    quando_limpo = _texto(quando_usar, LIMITE_QUANDO_USAR, "O texto de “quando usar”")
    lista_pistas = normalizar_pistas(pistas)
    lista_itens = validar_itens(itens)
    quem = (_espacos(usuario) or "escritório")[:200]

    with sessao() as con:
        linha = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if linha is None:
            raise TipoCasoNaoEncontrado(f"O tipo de caso “{codigo}” não está no catálogo.")
        atual = _registro(linha, _itens_no_banco(con, codigo))
        if int(versao) != atual["versao"]:
            raise ConflitoTipoCaso(
                f"“{atual['nome']}” foi alterado por "
                f"{atual['atualizado_por'] or 'outra pessoa'} enquanto você editava. "
                "Recarregue a lista e refaça a alteração."
            )

        novo = {
            "nome": nome_limpo,
            "descricao": descricao_limpa,
            "quando_usar": quando_limpo,
            "pistas": lista_pistas,
            "ativo": bool(ativo),
            "itens": lista_itens,
        }
        antes_estado, depois_estado = _estado(atual), _estado(novo)
        if antes_estado == depois_estado:
            return atual
        antes, depois = _retrato(atual), _retrato(novo)

        if atual["sistema"]:
            # A ação escrita em `app/categorias.py` é conferida contra o .docx do
            # escritório por `tests/test_categorias.py`. Deixar a tela reescrever o
            # checklist faria o cadastro divergir do documento assinado sem que o
            # teste acusasse — e o cliente receberia um checklist que ninguém aprovou.
            mudou = {
                campo
                for campo in ("nome", "descricao", "quando_usar", "pistas", "itens")
                if antes_estado[campo] != depois_estado[campo]
            }
            if mudou:
                raise ErroTipoCaso(
                    f"“{atual['nome']}” é uma ação do sistema: só dá para ativar ou "
                    "desativar. Nome, checklist e pistas vêm do checklist do escritório."
                )

        if normalizar(nome_limpo) != normalizar(atual["nome"]):
            _recusar_nome_repetido(con, nome_limpo, ignorar=codigo)
        if not atual["sistema"]:
            _recusar_remocao_com_documentos(con, codigo, atual["itens"], lista_itens)

        alteradas = con.execute(
            f"""
            UPDATE {_TABELA}
               SET nome = ?, descricao = ?, quando_usar = ?, pistas = ?, ativo = ?,
                   versao = versao + 1, atualizado_em = ?, atualizado_por = ?
             WHERE codigo = ? AND versao = ?
            """,
            (
                nome_limpo,
                descricao_limpa,
                quando_limpo,
                json.dumps(lista_pistas, ensure_ascii=False),
                int(bool(ativo)),
                _agora(),
                quem,
                codigo,
                int(versao),
            ),
        ).rowcount
        if alteradas == 0:
            raise ConflitoTipoCaso(
                f"“{atual['nome']}” foi alterado por outra pessoa enquanto você "
                "editava. Recarregue a lista e refaça a alteração."
            )
        if not atual["sistema"]:
            proximo = _gravar_itens(
                con, codigo, atual["itens"], lista_itens, int(linha["proximo_item"])
            )
            con.execute(
                f"UPDATE {_TABELA} SET proximo_item = ? WHERE codigo = ?", (proximo, codigo)
            )
            # Só agora os itens novos têm código. O retrato acima foi montado para a
            # COMPARAÇÃO, quando eles ainda não tinham — gravá-lo assim deixaria no
            # histórico uma linha sem código, justamente a informação que se procura ali.
            depois["itens"] = _itens_no_retrato(lista_itens)

        if antes["ativo"] and not depois["ativo"]:
            acao = "desativado"
        elif not antes["ativo"] and depois["ativo"]:
            acao = "reativado"
        else:
            acao = "editado"
        historico.registrar(
            historico.ENTIDADE_TIPO_CASO,
            codigo,
            acao,
            usuario=quem,
            antes=antes,
            depois=depois,
            motivo=motivo,
        )
    limpar_cache()
    return obter(codigo) or {}


# ------------------------------------------------------------------- impacto


def _uso_em_casos(codigo: str, itens: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantos casos usam esta ação e quais itens do checklist já têm documento."""
    with conectar() as con:
        linha = con.execute(
            "SELECT COUNT(*) AS total_casos FROM casos WHERE categoria = ?", (codigo,)
        ).fetchone()
        com_documento = [
            {"codigo": item["codigo"], "nome": item["nome"], "documentos": total}
            for item in itens
            if (total := _casos_no_item(con, codigo, item["codigo"]))
        ]
    return {"casos": int(linha["total_casos"] or 0), "itens_com_documento": com_documento}


def impacto(codigo: str) -> dict[str, Any]:
    """O que muda — e o que não muda — se esta ação for editada ou desativada."""
    tipo = obter(codigo)
    if tipo is None:
        raise TipoCasoNaoEncontrado(f"O tipo de caso “{codigo}” não está no catálogo.")
    uso = _uso_em_casos(codigo, tipo["itens"])
    casos = uso["casos"]

    if casos:
        checklist = (
            f"Alterar o checklist alcança os {casos} caso(s) já abertos desta ação: item "
            "acrescentado passa a ser pedido neles, e item retirado some da tela. Item "
            "que já tem documento entregue não pode ser retirado."
        )
        desativar = (
            f"A ação sai da criação de casos e da triagem. Os {casos} caso(s) que já a "
            "usam continuam com ela e com o mesmo checklist."
        )
    else:
        checklist = "Nenhum caso usa esta ação ainda: alterar o checklist não afeta nada aberto."
        desativar = "A ação sai da criação de casos e da triagem. Nenhum caso a usa."

    return {
        "tipo": tipo,
        **uso,
        "efeitos": {
            "codigo": (
                "O código não muda: é ele que fica gravado em cada caso, nas críticas "
                "da petição e nas instruções por categoria."
            ),
            "renomear": (
                "O novo nome aparece em toda a tela. Os casos guardam o código, não o "
                "nome — nenhum deles muda de ação."
            ),
            "checklist": checklist,
            "pistas": (
                "As pistas valem para as PRÓXIMAS triagens; entrevistas já enquadradas "
                "não mudam de categoria sozinhas."
            ),
            "desativar": desativar,
        },
    }


# ------------------------------------------------------------------- rotas

roteador = APIRouter(prefix="/api/tipos-caso", tags=["tipos-caso"])

PodeManter = Depends(auth.exigir_modulo(MODULO))


class PistaEntrada(BaseModel):
    expressao: str = Field(..., max_length=LIMITE_PISTA * 2)
    peso: int = 6


class ItemEntrada(BaseModel):
    #: Vazio é item novo: o código sai do contador do tipo, nunca da tela.
    codigo: str = Field("", max_length=20)
    nome: str = Field(..., max_length=LIMITE_ITEM_NOME * 2)
    obrigatorio: bool = False
    tipo_documento: str | None = Field(None, max_length=60)
    observacao: str = Field("", max_length=LIMITE_OBSERVACAO * 2)


class PedidoNovoTipoCaso(BaseModel):
    nome: str = Field(..., max_length=LIMITE_NOME * 2)
    codigo: str | None = Field(None, max_length=80)
    descricao: str = Field("", max_length=LIMITE_DESCRICAO * 2)
    quando_usar: str = Field("", max_length=LIMITE_QUANDO_USAR * 2)
    pistas: list[PistaEntrada] = Field(default_factory=list, max_length=MAXIMO_PISTAS * 2)
    itens: list[ItemEntrada] = Field(default_factory=list, max_length=MAXIMO_ITENS * 2)


class PedidoEdicaoTipoCaso(PedidoNovoTipoCaso):
    ativo: bool = True
    versao: int
    motivo: str = Field("", max_length=600)


def _quem(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.usuario or usuario.id or "escritório"


def _http(exc: ErroTipoCaso) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@roteador.get("")
def listar_tipos_caso(incluir_inativos: bool = Query(False)) -> dict[str, Any]:
    """O catálogo. Livre para a equipe: a criação do caso precisa desta lista."""
    return {"tipos": listar(incluir_inativos)}


@roteador.get("/{codigo}")
def obter_tipo_caso(codigo: str) -> dict[str, Any]:
    tipo = obter(codigo)
    if tipo is None:
        raise HTTPException(404, f"O tipo de caso “{codigo}” não está no catálogo.")
    return tipo


@roteador.get("/{codigo}/impacto")
def impacto_do_tipo_caso(codigo: str) -> dict[str, Any]:
    try:
        return impacto(codigo)
    except ErroTipoCaso as exc:
        raise _http(exc) from exc


@roteador.get("/{codigo}/historico")
def historico_do_tipo_caso(codigo: str) -> dict[str, Any]:
    return {"eventos": historico.listar(historico.ENTIDADE_TIPO_CASO, codigo)}


@roteador.post("", status_code=201)
def criar_tipo_caso(
    pedido: PedidoNovoTipoCaso, usuario: auth.Usuario = PodeManter
) -> dict[str, Any]:
    try:
        return criar(
            nome=pedido.nome,
            codigo=pedido.codigo,
            descricao=pedido.descricao,
            quando_usar=pedido.quando_usar,
            pistas=[p.model_dump() for p in pedido.pistas],
            itens=[i.model_dump() for i in pedido.itens],
            usuario=_quem(usuario),
        )
    except ErroTipoCaso as exc:
        raise _http(exc) from exc


@roteador.put("/{codigo}")
def editar_tipo_caso(
    codigo: str, pedido: PedidoEdicaoTipoCaso, usuario: auth.Usuario = PodeManter
) -> dict[str, Any]:
    try:
        return editar(
            codigo,
            nome=pedido.nome,
            descricao=pedido.descricao,
            quando_usar=pedido.quando_usar,
            pistas=[p.model_dump() for p in pedido.pistas],
            itens=[i.model_dump() for i in pedido.itens],
            ativo=pedido.ativo,
            versao=pedido.versao,
            usuario=_quem(usuario),
            motivo=pedido.motivo,
        )
    except ErroTipoCaso as exc:
        raise _http(exc) from exc
