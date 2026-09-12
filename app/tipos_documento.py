"""Glossário de tipos de documento: a lista única do que um documento pode ser.

O PROBLEMA QUE ISTO RESOLVE

"Tipo de documento" morava em três lugares que não se falavam: os nove tipos
cadastrais do classificador (`extractors.ROTULOS_TIPO`), os nomes dos itens de cada
checklist (`app/categorias.py`) e o que a correção manual gravava. E a correção gravava
`item.tipo_ocr or item.codigo` — para uma CAT, o tipo salvo era "DOC.10" no acidente de
trabalho geral e "DOC.09" na doença ocupacional. O mesmo documento com dois "tipos", e
o mesmo "DOC.13" querendo dizer atestado numa categoria e extrato do FGTS noutra. A
memória de correções que orienta o modelo aprendia com esse ruído.

Aqui cada tipo tem um código estável e um nome que o escritório mantém. Cada item de
checklist aponta para um tipo (`ItemChecklist.tipo_documento`), e a reclassificação
grava o código do glossário.

O QUE PODE MUDAR E O QUE NÃO PODE — a avaliação de impacto, em regra

- `codigo` é imutável. É ele que fica gravado em cada documento classificado
  (`entregas.tipo_detectado`) e em cada correção. Trocar o código deixaria esses
  registros apontando para o nada, por isso não há rota que o altere.
- `nome`, `descricao` e `sinonimos` mudam à vontade. O documento guarda o código, não
  o nome: o nome novo aparece em todo lugar que consulta o glossário. O registro de
  cada leitura (`extracao_json`) continua com o nome da época, que é histórico.
- Sinônimos entram na leitura automática dos PRÓXIMOS documentos (ver
  `descrever_item`, usado por `roteamento._semantico`). Não reclassificam o que já foi
  lido — isso mudaria documento sem ninguém ter olhado para ele.
- Desativar tira o tipo das opções de classificação sem tocar no que já foi
  classificado. Tipo apontado por item de checklist NÃO desativa: o checklist
  continuaria pedindo o documento, e a reclassificação não teria para onde levá-lo.
  Tipo de sistema também não — o classificador ou os checklists dependem dele.
- Apagar não existe. Um tipo apagado levaria junto o significado dos documentos que o
  usam; desativar faz o que se quer sem essa perda.
- Os tipos de caso marcados decidem em que checklists, além do fixo do escritório, o
  tipo é pedido (ver `categorias._com_itens_do_glossario`). Desmarcar um tipo de caso
  em que já há documento entregue nesse item é recusado: o documento ficaria preso a um
  item que a tela não mostra mais.

QUEM MANTÉM

Criar e editar exige o módulo `glossario_documentos` (ver `app/perfis.py`). O sistema
não tem perfil "gestor" ou "admin" cravado no código: acesso é por módulo, entregue de
fábrica ao Advogado e ao Secretário — os perfis que já administram usuários — e
qualquer perfil novo (um "Gestor", por exemplo) passa a manter o glossário marcando a
caixa na tela de perfis. Consultar é livre para a equipe: a reclassificação precisa da
lista.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import auth, categorias
from . import historico_alteracoes as historico
from .banco import PREFIXO, SCHEMA, conectar, sessao
from .cache_leitura import por_alguns_segundos
from .extractors import ROTULOS_TIPO, normalizar

log = logging.getLogger("tipos_documento")

#: Módulo da matriz de acesso que libera criar e editar. Consultar não exige.
MODULO = "glossario_documentos"

LIMITE_NOME = 120
LIMITE_DESCRICAO = 600
LIMITE_SINONIMO = 80
MAXIMO_SINONIMOS = 20

#: Minúsculas, números e `_`, começando por letra. É o formato dos códigos que o
#: classificador já produzia (`comprovante_residencia`), e o que cabe numa coluna
#: `varchar` sem surpresa de acento ou de maiúscula em comparação.
RE_CODIGO = re.compile(r"^[a-z][a-z0-9_]{1,59}$")

_TABELA = f"{SCHEMA}.{PREFIXO}tipos_documento"
_TABELA_CATEGORIAS = f"{SCHEMA}.{PREFIXO}tipos_documento_categorias"


@dataclass(frozen=True)
class SementeTipo:
    codigo: str
    nome: str
    descricao: str = ""
    sinonimos: tuple[str, ...] = ()


_CADASTRAIS = (
    "rg",
    "cpf",
    "cin",
    "cnh",
    "ctps",
    "titulo_eleitor",
    "cartao_sus",
    "comprovante_residencia",
    "certidao",
)

#: Os tipos que o sistema garante existir.
#:
#: Os nove primeiros são os do classificador de OCR, com o MESMO código que ele
#: grava em `tipo_detectado` — é isso que faz um documento lido automaticamente já
#: nascer com tipo do glossário, sem tradução. Os demais saíram dos checklists do
#: escritório: cada item de `categorias.py` aponta para um deles (o teste
#: `tests/test_tipos_documento.py` garante que nenhum item fique sem tipo).
#:
#: A semente só INSERE o que falta. Nome e sinônimos editados pelo escritório nunca
#: são sobrescritos por uma subida do servidor.
SEMENTE: tuple[SementeTipo, ...] = (
    *(
        SementeTipo(
            codigo,
            ROTULOS_TIPO[codigo],
            "Reconhecido automaticamente pelo classificador de OCR.",
        )
        for codigo in _CADASTRAIS
    ),
    SementeTipo("procuracao", "Procuração", "Mandato do cliente ao escritório."),
    SementeTipo(
        "declaracao_hipossuficiencia",
        "Declaração de hipossuficiência",
        "Declaração para o pedido de gratuidade de justiça.",
        ("declaração de pobreza", "gratuidade de justiça"),
    ),
    SementeTipo(
        "contracheque",
        "Contracheque",
        "Demonstrativo mensal de pagamento do salário.",
        ("holerite", "folha de pagamento", "demonstrativo de pagamento"),
    ),
    SementeTipo(
        "cnis",
        "CNIS (extrato previdenciário)",
        "Cadastro Nacional de Informações Sociais: vínculos, contribuições e remunerações.",
        ("extrato de contribuição", "histórico previdenciário"),
    ),
    SementeTipo(
        "ficha_funcional",
        "Ficha funcional",
        "Ficha de registro do empregado e evolução de cargo, função e salário.",
        ("ficha de registro", "evolução funcional"),
    ),
    SementeTipo(
        "cat",
        "CAT (Comunicação de Acidente de Trabalho)",
        "Comunicação do acidente ou da doença do trabalho ao INSS.",
        ("comunicação de acidente de trabalho",),
    ),
    SementeTipo(
        "boletim_ocorrencia",
        "Boletim de ocorrência",
        "Registro policial do fato.",
        ("BO", "registro policial"),
    ),
    SementeTipo(
        "atendimento_emergencia",
        "Ficha de atendimento de emergência",
        "Registro do atendimento em pronto-socorro, UPA ou hospital.",
        ("pronto-socorro", "atendimento na UPA", "boletim de atendimento"),
    ),
    SementeTipo("atestado_medico", "Atestado médico", "Atestado de afastamento ou de condição de saúde."),
    SementeTipo(
        "laudo_medico",
        "Laudo médico",
        "Laudo com diagnóstico, CID e, quando possível, relação com o trabalho.",
        ("laudo com CID",),
    ),
    SementeTipo(
        "relatorio_medico",
        "Relatório médico",
        "Relatório de acompanhamento e evolução clínica.",
        ("relatório de acompanhamento", "evolução clínica"),
    ),
    SementeTipo(
        "exame_imagem",
        "Exame de imagem ou laboratorial",
        "Raio X, tomografia, ressonância, ultrassom e exames laboratoriais.",
        ("raio X", "ressonância magnética", "tomografia", "ultrassom"),
    ),
    SementeTipo(
        "laudo_exame",
        "Laudo de exame",
        "Laudo que interpreta um exame de imagem ou laboratorial.",
        ("laudo de raio X", "laudo de ressonância", "laudo de tomografia"),
    ),
    SementeTipo(
        "receituario",
        "Receituário médico",
        "Receitas dos medicamentos prescritos.",
        ("receita médica", "prescrição"),
    ),
    SementeTipo(
        "comprovante_tratamento",
        "Comprovante de tratamento",
        "Fisioterapia, terapia ocupacional, psicologia, psiquiatria, fonoaudiologia e similares.",
        ("fisioterapia", "psicologia", "psiquiatria", "terapia ocupacional"),
    ),
    SementeTipo(
        "prontuario",
        "Prontuário médico",
        "Cópia do prontuário hospitalar ou da clínica.",
        ("prontuário hospitalar", "histórico de atendimentos"),
    ),
    SementeTipo(
        "decisao_inss",
        "Decisão do INSS",
        "Comunicação de concessão, indeferimento, cessação ou prorrogação de benefício.",
        ("carta de indeferimento", "comunicado de decisão", "cessação de benefício", "prorrogação de benefício"),
    ),
    SementeTipo(
        "carta_concessao",
        "Carta de concessão do INSS",
        "Carta de concessão do benefício, com memória de cálculo.",
        ("memória de cálculo",),
    ),
    SementeTipo(
        "historico_beneficios",
        "Histórico de benefícios",
        "Histórico de benefícios e extratos previdenciários.",
        ("extrato de benefícios",),
    ),
    SementeTipo(
        "laudo_pericial_inss",
        "Laudo pericial do INSS",
        "Laudos e resultados das perícias médicas do INSS, inclusive SABI.",
        ("laudo SABI", "perícia médica do INSS", "resultado da perícia"),
    ),
    SementeTipo(
        "processo_inss",
        "Processo administrativo do INSS",
        "Cópia integral do processo administrativo do benefício.",
        ("processo administrativo", "cópia integral do processo"),
    ),
    SementeTipo(
        "aso",
        "ASO (Atestado de Saúde Ocupacional)",
        "Admissional, periódico, retorno ao trabalho, mudança de função e demissional.",
        ("atestado de saúde ocupacional", "exame admissional", "exame demissional"),
    ),
    SementeTipo(
        "laudo_pericial_particular",
        "Laudo pericial particular",
        "Laudo de perito ou assistente técnico contratado.",
        ("perícia particular", "assistente técnico"),
    ),
    SementeTipo(
        "fotos",
        "Fotos e vídeos",
        "Imagens do local, do posto de trabalho, de máquinas ou do reclamante.",
        ("vídeos", "imagens do local"),
    ),
    SementeTipo(
        "ppp",
        "PPP (Perfil Profissiográfico Previdenciário)",
        "Histórico laboral e de exposição a agentes nocivos.",
        ("perfil profissiográfico previdenciário",),
    ),
    SementeTipo(
        "programa_ocupacional",
        "Programa de saúde e segurança do trabalho",
        "PCMSO, PGR, LTCAT, PPRA, mapas de risco e documentos semelhantes.",
        ("PCMSO", "PGR", "LTCAT", "PPRA", "mapa de risco"),
    ),
    SementeTipo(
        "comprovante_despesas",
        "Comprovante de despesas",
        "Recibos e notas de medicamentos, tratamentos e demais gastos relacionados.",
        ("nota fiscal", "recibo"),
    ),
    SementeTipo(
        "controle_jornada",
        "Controle de jornada",
        "Ponto, escalas e registros de horas extras.",
        ("cartão de ponto", "escala de trabalho", "horas extras"),
    ),
    SementeTipo(
        "prova_condicoes_trabalho",
        "Prova das condições de trabalho",
        "Exposição a risco, sobrecarga, acúmulo de funções e metas abusivas.",
        ("exposição a risco", "insalubridade", "acúmulo de função", "metas abusivas"),
    ),
    SementeTipo("testemunhas", "Rol de testemunhas", "Nomes e contatos de testemunhas."),
    SementeTipo(
        "contrato_trabalho",
        "Contrato de trabalho",
        "Contrato, aditivos e normas contratuais.",
        ("aditivo contratual",),
    ),
    SementeTipo(
        "documentos_rescisorios",
        "Documentos rescisórios",
        "TRCT e comprovantes das verbas rescisórias.",
        ("TRCT", "termo de rescisão", "verbas rescisórias"),
    ),
    SementeTipo(
        "extrato_fgts",
        "Extrato do FGTS",
        "Extrato da conta vinculada e chave de conectividade.",
        ("chave de conectividade",),
    ),
    SementeTipo(
        "regulamento_empresa",
        "Regulamento da empresa",
        "Manual, regulamento interno ou norma da empresa.",
        ("manual da empresa", "norma interna"),
    ),
)

SEMENTE_POR_CODIGO: dict[str, SementeTipo] = {s.codigo: s for s in SEMENTE}


class ErroGlossario(ValueError):
    """Pedido recusado. `status` é o código HTTP que a rota devolve."""

    status = 400


class TipoNaoEncontrado(ErroGlossario):
    status = 404


class ConflitoGlossario(ErroGlossario):
    status = 409


ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    codigo         varchar(60)   NOT NULL CONSTRAINT pk_acervo_tipos_documento PRIMARY KEY,
    nome           nvarchar(120) NOT NULL CONSTRAINT uq_acervo_tipos_documento_nome UNIQUE,
    descricao      nvarchar(600) NOT NULL CONSTRAINT df_acervo_tipos_doc_desc DEFAULT N'',
    sinonimos      nvarchar(max) NOT NULL CONSTRAINT df_acervo_tipos_doc_sin DEFAULT N'[]',
    ativo          bit           NOT NULL CONSTRAINT df_acervo_tipos_doc_ativo DEFAULT 1,
    sistema        bit           NOT NULL CONSTRAINT df_acervo_tipos_doc_sis DEFAULT 0,
    versao         int           NOT NULL CONSTRAINT df_acervo_tipos_doc_versao DEFAULT 1,
    criado_em      varchar(40)   NOT NULL,
    criado_por     nvarchar(200) NOT NULL CONSTRAINT df_acervo_tipos_doc_cpor DEFAULT N'',
    atualizado_em  varchar(40)   NOT NULL,
    atualizado_por nvarchar(200) NOT NULL CONSTRAINT df_acervo_tipos_doc_apor DEFAULT N''
);
IF OBJECT_ID('{_TABELA_CATEGORIAS}') IS NULL
CREATE TABLE {_TABELA_CATEGORIAS} (
    tipo_codigo varchar(60)   NOT NULL,
    categoria   varchar(120)  NOT NULL,
    criado_em   varchar(40)   NOT NULL,
    criado_por  nvarchar(200) NOT NULL CONSTRAINT df_acervo_tipos_doc_cat_cpor DEFAULT N'',
    CONSTRAINT pk_acervo_tipos_doc_categorias PRIMARY KEY (tipo_codigo, categoria),
    CONSTRAINT fk_acervo_tipos_doc_categorias_tipo FOREIGN KEY (tipo_codigo)
        REFERENCES {_TABELA} (codigo)
)
"""

_COLUNAS = (
    "codigo, nome, descricao, sinonimos, ativo, sistema, versao, "
    "criado_em, criado_por, atualizado_em, atualizado_por"
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _espacos(texto: Any) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


# ----------------------------------------------------------------- validação


def validar_nome(nome: Any) -> str:
    limpo = _espacos(nome)
    if len(limpo) < 2:
        raise ErroGlossario("Informe o nome do tipo de documento.")
    if len(limpo) > LIMITE_NOME:
        raise ErroGlossario(f"O nome passa de {LIMITE_NOME} caracteres.")
    return limpo


def validar_codigo(codigo: Any) -> str:
    limpo = str(codigo or "").strip()
    if not RE_CODIGO.match(limpo):
        raise ErroGlossario(
            "Código inválido: use de 2 a 60 letras minúsculas, números ou _, "
            "começando por letra (ex.: laudo_medico)."
        )
    return limpo


def validar_descricao(descricao: Any) -> str:
    limpo = _espacos(descricao)
    if len(limpo) > LIMITE_DESCRICAO:
        raise ErroGlossario(f"A descrição passa de {LIMITE_DESCRICAO} caracteres.")
    return limpo


def gerar_codigo(nome: str) -> str:
    """Código a partir do nome: "Laudo médico — perícia" vira `laudo_medico_pericia`."""
    base = re.sub(r"[^a-z0-9]+", "_", normalizar(nome).lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"tipo_{base}".rstrip("_")
    return base[:60].rstrip("_")


def normalizar_sinonimos(bruto: Any) -> list[str]:
    """Sem vazio, sem repetido (ignorando acento e caixa), na ordem em que vieram.

    Aceita lista ou texto separado por vírgula — é como a tela os digita.
    """
    if isinstance(bruto, str):
        bruto = bruto.split(",")
    vistos: set[str] = set()
    saida: list[str] = []
    for item in bruto or []:
        limpo = _espacos(item)
        if not limpo:
            continue
        if len(limpo) > LIMITE_SINONIMO:
            raise ErroGlossario(
                f"O sinônimo “{limpo[:30]}…” passa de {LIMITE_SINONIMO} caracteres."
            )
        chave = normalizar(limpo)
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(limpo)
    if len(saida) > MAXIMO_SINONIMOS:
        raise ErroGlossario(f"São aceitos até {MAXIMO_SINONIMOS} sinônimos por tipo.")
    return saida


# --------------------------------------------------------- vínculo com checklist


@por_alguns_segundos(30, maximo=2)
def _marcacoes_em_cache() -> tuple[dict[str, Any], ...]:
    with conectar() as con:
        linhas = con.execute(
            f"""
            SELECT m.tipo_codigo, m.categoria, t.nome, t.descricao, t.ativo
              FROM {_TABELA_CATEGORIAS} m
              JOIN {_TABELA} t ON t.codigo = m.tipo_codigo
             ORDER BY m.criado_em, t.nome
            """
        ).fetchall()
    return tuple(
        {
            "codigo": str(linha["tipo_codigo"]),
            "categoria": str(linha["categoria"]),
            "nome": linha["nome"],
            "descricao": linha["descricao"] or "",
            "ativo": bool(linha["ativo"]),
        }
        for linha in linhas
    )


def _marcacoes() -> tuple[dict[str, Any], ...]:
    """Cada par (tipo, tipo de caso) marcado no glossário.

    Com o banco fora do ar, nenhum: o checklist do escritório continua de pé e só os
    itens acrescentados somem até o banco voltar.
    """
    try:
        return _marcacoes_em_cache()
    except Exception:  # noqa: BLE001 - leitura auxiliar; o checklist fixo é o piso
        log.warning("Tipos de caso do glossário indisponíveis.", exc_info=True)
        return ()


def categorias_marcadas(codigo: str) -> list[str]:
    """Os tipos de caso em que o glossário pede este tipo, além do checklist fixo.

    Na ordem do catálogo, a mesma de `validar_categorias` e do histórico — a do cache
    é a de marcação, e marcações salvas juntas empatam no mesmo segundo.
    """
    marcadas = {m["categoria"] for m in _marcacoes() if m["codigo"] == codigo}
    return [c for c in categorias.CATEGORIAS if c in marcadas] + sorted(
        marcadas - set(categorias.CATEGORIAS)
    )


def tipos_marcados(categoria: str) -> list[dict[str, Any]]:
    """Os tipos ATIVOS que o glossário acrescenta ao checklist deste tipo de caso."""
    return [m for m in _marcacoes() if m["categoria"] == categoria and m["ativo"]]


def _itens_fixos(codigo: str) -> list[dict[str, Any]]:
    return [
        {
            "categoria": categoria.codigo,
            "categoria_nome": categoria.nome,
            "item": item.codigo,
            "nome": item.nome,
            "do_glossario": False,
        }
        for categoria in categorias.CATEGORIAS.values()
        for item in categoria.itens
        if item.tipo_documento == codigo
    ]


def itens_do_checklist(
    codigo: str, marcadas: list[str] | None = None, nome: str | None = None
) -> list[dict[str, Any]]:
    """Os itens de checklist, de todas as categorias, que pedem este tipo.

    Os do checklist do escritório e os acrescentados pelos tipos de caso marcados.
    `marcadas` substitui o que está gravado — é assim que uma edição se confere antes
    de ser salva.
    """
    itens = _itens_fixos(codigo)
    ja_pedem = {i["categoria"] for i in itens}
    for codigo_categoria in categorias_marcadas(codigo) if marcadas is None else marcadas:
        categoria = categorias.CATEGORIAS.get(codigo_categoria)
        if categoria is None or categoria.codigo in ja_pedem:
            continue
        itens.append(
            {
                "categoria": categoria.codigo,
                "categoria_nome": categoria.nome,
                "item": categorias.codigo_item_do_glossario(codigo),
                "nome": nome or codigo,
                "do_glossario": True,
            }
        )
    return itens


def validar_categorias(bruto: Any, codigo: str) -> list[str]:
    """Os tipos de caso marcados, na ordem do catálogo e sem repetição.

    Tipo de caso cujo checklist fixo já pede este tipo sai da lista em silêncio: a tela
    mostra essa linha marcada e travada, e gravá-la não acrescentaria nada.
    """
    pedidos = {str(c or "").strip() for c in bruto or []} - {""}
    desconhecidos = sorted(pedidos - set(categorias.CATEGORIAS))
    if desconhecidos:
        raise ErroGlossario(f"Tipo de caso inexistente: {', '.join(desconhecidos)}.")
    fixos = {i["categoria"] for i in _itens_fixos(codigo)}
    return [c for c in categorias.CATEGORIAS if c in pedidos and c not in fixos]


def motivo_bloqueio_desativacao(
    tipo: dict[str, Any], marcadas: list[str] | None = None
) -> str | None:
    """Por que este tipo não pode ser desativado — ou `None`, quando pode."""
    itens = itens_do_checklist(str(tipo.get("codigo") or ""), marcadas, tipo.get("nome"))
    if itens:
        categorias_afetadas = sorted({i["categoria_nome"] for i in itens})
        dica = (
            " Desmarque os tipos de caso antes de desativá-lo."
            if any(i["do_glossario"] for i in itens)
            else ""
        )
        return (
            f"Não pode ser desativado: {len(itens)} item(ns) de checklist pedem este tipo "
            f"({', '.join(categorias_afetadas)}). O checklist continuaria pedindo o "
            f"documento sem ter para onde classificá-lo.{dica}"
        )
    if tipo.get("sistema"):
        return (
            "Não pode ser desativado: é um tipo de sistema, que o classificador de "
            "documentos reconhece sozinho. Nome, descrição e sinônimos podem ser editados."
        )
    return None


def descrever_item(item: categorias.ItemChecklist, glossario: dict[str, dict[str, Any]]) -> str:
    """O nome do item acrescido do tipo e dos sinônimos, para a leitura automática.

    É por aqui que a manutenção do glossário alcança a classificação: um sinônimo
    cadastrado hoje ("holerite" em Contracheque) entra no pedido ao modelo do próximo
    documento lido.
    """
    tipo = glossario.get(item.tipo_documento or "")
    if not tipo:
        return item.nome
    partes = [f"tipo: {tipo['nome']}"]
    sinonimos = [s for s in tipo.get("sinonimos") or [] if s]
    if sinonimos:
        partes.append("também chamado: " + ", ".join(sinonimos[:8]))
    return f"{item.nome} [{'; '.join(partes)}]"


# ------------------------------------------------------------------ leitura


def _sinonimos_de(bruto: Any) -> list[str]:
    try:
        valor = json.loads(bruto or "[]")
    except (TypeError, ValueError):
        return []
    return [str(v) for v in valor] if isinstance(valor, list) else []


def _registro(linha: Any) -> dict[str, Any]:
    codigo = str(linha["codigo"])
    return {
        "codigo": codigo,
        "nome": linha["nome"],
        "descricao": linha["descricao"] or "",
        "sinonimos": _sinonimos_de(linha["sinonimos"]),
        "ativo": bool(linha["ativo"]),
        "sistema": bool(linha["sistema"]),
        "versao": int(linha["versao"]),
        "criado_em": linha["criado_em"],
        "criado_por": linha["criado_por"] or "",
        "atualizado_em": linha["atualizado_em"],
        "atualizado_por": linha["atualizado_por"] or "",
        "categorias": categorias_marcadas(codigo),
        "itens_checklist": len(itens_do_checklist(codigo, nome=linha["nome"])),
    }


def _retrato(tipo: dict[str, Any]) -> dict[str, Any]:
    """O que o histórico guarda de antes e depois: só o que a edição pode mudar."""
    return {
        "nome": tipo["nome"],
        "descricao": tipo["descricao"],
        "sinonimos": list(tipo["sinonimos"]),
        "ativo": bool(tipo["ativo"]),
        "categorias": list(tipo.get("categorias") or []),
    }


def inicializar() -> None:
    """Cria a tabela e insere os tipos de sistema que faltarem. Idempotente."""
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)

    agora = _agora()
    with conectar() as con:
        existentes = {
            str(linha["codigo"])
            for linha in con.execute(f"SELECT codigo FROM {_TABELA}").fetchall()
        }
        for semente in SEMENTE:
            if semente.codigo in existentes:
                continue
            try:
                con.execute(
                    f"""
                    INSERT INTO {_TABELA} ({_COLUNAS})
                    VALUES (?, ?, ?, ?, 1, 1, 1, ?, N'sistema', ?, N'sistema')
                    """,
                    (
                        semente.codigo,
                        semente.nome,
                        semente.descricao,
                        json.dumps(list(semente.sinonimos), ensure_ascii=False),
                        agora,
                        agora,
                    ),
                )
            except Exception:  # noqa: BLE001 - um tipo recusado não impede os demais
                # O caso real é o escritório ter criado antes um tipo com o mesmo nome
                # que uma semente nova traz. Sobrescrever o dele seria pior.
                log.warning(
                    "Tipo de sistema %r não entrou no glossário (nome já usado?).",
                    semente.codigo,
                    exc_info=True,
                )
    limpar_cache()


def listar(incluir_inativos: bool = False) -> list[dict[str, Any]]:
    filtro = "" if incluir_inativos else " WHERE ativo = 1"
    with conectar() as con:
        linhas = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA}{filtro} ORDER BY nome"
        ).fetchall()
    return [_registro(linha) for linha in linhas]


def obter(codigo: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA} WHERE codigo = ?", (codigo,)
        ).fetchone()
    return _registro(linha) if linha else None


@por_alguns_segundos(30, maximo=2)
def _todos_em_cache() -> dict[str, dict[str, Any]]:
    return {tipo["codigo"]: tipo for tipo in listar(incluir_inativos=True)}


def limpar_cache() -> None:
    _todos_em_cache.limpar_cache()  # type: ignore[attr-defined]
    _marcacoes_em_cache.limpar_cache()  # type: ignore[attr-defined]


def glossario_por_codigo() -> dict[str, dict[str, Any]]:
    """Todos os tipos, inclusive desativados, por código.

    Desativado entra de propósito: documento classificado antes da desativação
    continua precisando de nome. Com o banco fora do ar, devolve a semente — a
    leitura automática segue com os tipos de sistema em vez de parar.
    """
    try:
        return _todos_em_cache()
    except Exception:  # noqa: BLE001 - leitura auxiliar; a semente é o piso
        log.warning("Glossário indisponível; usando os tipos de sistema.", exc_info=True)
        return {
            s.codigo: {
                "codigo": s.codigo,
                "nome": s.nome,
                "descricao": s.descricao,
                "sinonimos": list(s.sinonimos),
                "ativo": True,
                "sistema": True,
            }
            for s in SEMENTE
        }


def codigos_conhecidos() -> set[str]:
    return set(glossario_por_codigo())


# ------------------------------------------------------------------ escrita


def _recusar_nome_repetido(con: Any, nome: str, ignorar: str | None) -> None:
    """Dois tipos com o mesmo nome — ou nomes que só diferem em acento — confundem a escolha."""
    chave = normalizar(nome)
    for linha in con.execute(f"SELECT codigo, nome FROM {_TABELA}").fetchall():
        if linha["codigo"] != ignorar and normalizar(linha["nome"]) == chave:
            raise ConflitoGlossario(
                f"Já existe o tipo “{linha['nome']}” ({linha['codigo']}). "
                "Use-o, ou escolha outro nome."
            )


def _marcadas_no_banco(con: Any, codigo: str) -> list[str]:
    """As marcações gravadas, lidas na transação da edição — o cache pode estar atrasado."""
    gravadas = {
        str(linha["categoria"])
        for linha in con.execute(
            f"SELECT categoria FROM {_TABELA_CATEGORIAS} WHERE tipo_codigo = ?", (codigo,)
        ).fetchall()
    }
    # Na ordem do catálogo, a mesma de `validar_categorias`: senão `antes` e `depois`
    # do histórico acusariam mudança que é só de ordem.
    return [c for c in categorias.CATEGORIAS if c in gravadas] + sorted(
        gravadas - set(categorias.CATEGORIAS)
    )


def _documentos_no_item(con: Any, categoria: str, codigo: str) -> int:
    """Documentos entregues no item que este tipo acrescenta, em casos da categoria."""
    item = categorias.codigo_item_do_glossario(codigo)
    # `itens_atendidos` é JSON (`["GLOS.x"]`); `[`, `_` e `%` escapados para o LIKE.
    literal = item.replace("[", "[[]").replace("_", "[_]").replace("%", "[%]")
    linha = con.execute(
        """
        SELECT COUNT(DISTINCT e.id) AS total_documentos
          FROM entregas e
          JOIN casos c ON c.id = e.caso_id
         WHERE c.categoria = ?
           AND (e.item_codigo = ? OR e.itens_atendidos LIKE ?)
        """,
        (categoria, item, f'%"{literal}"%'),
    ).fetchone()
    return int(linha["total_documentos"] or 0)


def _recusar_desmarcacao_com_documentos(con: Any, codigo: str, desmarcadas: list[str]) -> None:
    for codigo_categoria in desmarcadas:
        total = _documentos_no_item(con, codigo_categoria, codigo)
        if total:
            categoria = categorias.CATEGORIAS.get(codigo_categoria)
            raise ConflitoGlossario(
                f"“{categoria.nome if categoria else codigo_categoria}” não pode ser "
                f"desmarcado: {total} documento(s) já entregue(s) neste item em casos "
                "desse tipo ficariam fora do checklist. Reclassifique-os antes."
            )


def _gravar_marcacoes(
    con: Any, codigo: str, antes: list[str], depois: list[str], quem: str, agora: str
) -> None:
    for categoria in antes:
        if categoria not in depois:
            con.execute(
                f"DELETE FROM {_TABELA_CATEGORIAS} WHERE tipo_codigo = ? AND categoria = ?",
                (codigo, categoria),
            )
    for categoria in depois:
        if categoria not in antes:
            con.execute(
                f"""
                INSERT INTO {_TABELA_CATEGORIAS} (tipo_codigo, categoria, criado_em, criado_por)
                VALUES (?, ?, ?, ?)
                """,
                (codigo, categoria, agora, quem),
            )


def criar(
    *,
    nome: str,
    usuario: str,
    codigo: str | None = None,
    descricao: str = "",
    sinonimos: Any = (),
    categorias_caso: Any = (),
) -> dict[str, Any]:
    nome_limpo = validar_nome(nome)
    codigo_limpo = validar_codigo(
        codigo if str(codigo or "").strip() else gerar_codigo(nome_limpo)
    )
    descricao_limpa = validar_descricao(descricao)
    lista = normalizar_sinonimos(sinonimos)
    marcadas = validar_categorias(categorias_caso, codigo_limpo)
    quem = (_espacos(usuario) or "escritório")[:200]
    agora = _agora()

    with sessao() as con:
        if con.execute(
            f"SELECT 1 AS existe FROM {_TABELA} WHERE codigo = ?", (codigo_limpo,)
        ).fetchone():
            raise ConflitoGlossario(
                f"Já existe um tipo com o código “{codigo_limpo}”. Se ele está "
                "desativado, reative-o em vez de criar outro."
            )
        _recusar_nome_repetido(con, nome_limpo, ignorar=None)
        con.execute(
            f"""
            INSERT INTO {_TABELA} ({_COLUNAS})
            VALUES (?, ?, ?, ?, 1, 0, 1, ?, ?, ?, ?)
            """,
            (
                codigo_limpo,
                nome_limpo,
                descricao_limpa,
                json.dumps(lista, ensure_ascii=False),
                agora,
                quem,
                agora,
                quem,
            ),
        )
        _gravar_marcacoes(con, codigo_limpo, [], marcadas, quem, agora)
        historico.registrar(
            historico.ENTIDADE_TIPO_DOCUMENTO,
            codigo_limpo,
            "criado",
            usuario=quem,
            depois={
                "nome": nome_limpo,
                "descricao": descricao_limpa,
                "sinonimos": lista,
                "ativo": True,
                "categorias": marcadas,
            },
        )
    limpar_cache()
    return obter(codigo_limpo) or {}


def editar(
    codigo: str,
    *,
    nome: str,
    descricao: str,
    sinonimos: Any,
    ativo: bool,
    versao: int,
    usuario: str,
    motivo: str = "",
    categorias_caso: Any = None,
) -> dict[str, Any]:
    """Aplica a edição, se ninguém tiver editado o mesmo tipo no meio do caminho.

    `versao` é a que a tela tinha quando abriu o formulário. Sem ela, duas pessoas
    editando o mesmo tipo fariam a segunda apagar a alteração da primeira sem que
    nenhuma das duas soubesse. `categorias_caso` ausente mantém os tipos de caso
    marcados.
    """
    nome_limpo = validar_nome(nome)
    descricao_limpa = validar_descricao(descricao)
    lista = normalizar_sinonimos(sinonimos)
    novas = None if categorias_caso is None else validar_categorias(categorias_caso, codigo)
    quem = (_espacos(usuario) or "escritório")[:200]

    with sessao() as con:
        linha = con.execute(
            f"SELECT {_COLUNAS} FROM {_TABELA} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if linha is None:
            raise TipoNaoEncontrado(f"O tipo “{codigo}” não está no glossário.")
        atual = _registro(linha)
        atual["categorias"] = _marcadas_no_banco(con, codigo)
        if int(versao) != atual["versao"]:
            raise ConflitoGlossario(
                f"“{atual['nome']}” foi alterado por "
                f"{atual['atualizado_por'] or 'outra pessoa'} enquanto você editava. "
                "Recarregue a lista e refaça a alteração."
            )

        antes = _retrato(atual)
        marcadas = antes["categorias"] if novas is None else novas
        depois = {
            "nome": nome_limpo,
            "descricao": descricao_limpa,
            "sinonimos": lista,
            "ativo": bool(ativo),
            "categorias": marcadas,
        }
        if depois == antes:
            return atual

        if antes["ativo"] and not depois["ativo"]:
            # Com as marcações NOVAS: desmarcar tudo e desativar cabe na mesma edição.
            bloqueio = motivo_bloqueio_desativacao(atual, marcadas)
            if bloqueio:
                raise ConflitoGlossario(bloqueio)
        _recusar_desmarcacao_com_documentos(
            con, codigo, [c for c in antes["categorias"] if c not in marcadas]
        )
        if normalizar(nome_limpo) != normalizar(atual["nome"]):
            _recusar_nome_repetido(con, nome_limpo, ignorar=codigo)

        alteradas = con.execute(
            f"""
            UPDATE {_TABELA}
               SET nome = ?, descricao = ?, sinonimos = ?, ativo = ?,
                   versao = versao + 1, atualizado_em = ?, atualizado_por = ?
             WHERE codigo = ? AND versao = ?
            """,
            (
                nome_limpo,
                descricao_limpa,
                json.dumps(lista, ensure_ascii=False),
                int(bool(ativo)),
                _agora(),
                quem,
                codigo,
                int(versao),
            ),
        ).rowcount
        if alteradas == 0:
            raise ConflitoGlossario(
                f"“{atual['nome']}” foi alterado por outra pessoa enquanto você "
                "editava. Recarregue a lista e refaça a alteração."
            )
        _gravar_marcacoes(con, codigo, antes["categorias"], marcadas, quem, _agora())

        if antes["ativo"] and not depois["ativo"]:
            acao = "desativado"
        elif not antes["ativo"] and depois["ativo"]:
            acao = "reativado"
        else:
            acao = "editado"
        historico.registrar(
            historico.ENTIDADE_TIPO_DOCUMENTO,
            codigo,
            acao,
            usuario=quem,
            antes=antes,
            depois=depois,
            motivo=motivo,
        )
    limpar_cache()
    return obter(codigo) or {}


# ------------------------------------------------------------------ impacto


def _uso_em_documentos(codigo: str, itens: list[dict[str, str]]) -> dict[str, int]:
    """Quantos documentos e casos este tipo alcança hoje.

    Conta o documento classificado com o tipo (pelo leitor ou por correção) e o
    entregue num item de checklist que pede o tipo. Os aliases evitam nome de
    tabela de propósito: `banco._qualificar` trocaria um `AS casos` por
    `AS dbo.acervo_casos`.
    """
    condicoes = ["e.tipo_detectado = ?"]
    parametros: list[Any] = [codigo]
    por_categoria: dict[str, list[str]] = {}
    for item in itens:
        por_categoria.setdefault(item["categoria"], []).append(item["item"])
    for categoria, codigos_item in por_categoria.items():
        marcadores = ",".join("?" for _ in codigos_item)
        condicoes.append(f"(c.categoria = ? AND e.item_codigo IN ({marcadores}))")
        parametros.extend([categoria, *codigos_item])

    with conectar() as con:
        uso = con.execute(
            f"""
            SELECT COUNT(DISTINCT e.id) AS total_documentos,
                   COUNT(DISTINCT e.caso_id) AS total_casos
              FROM entregas e
              JOIN casos c ON c.id = e.caso_id
             WHERE {' OR '.join(condicoes)}
            """,
            parametros,
        ).fetchone()
        correcoes = con.execute(
            "SELECT COUNT(*) AS total_correcoes FROM classificacoes_documentos_corrigidas"
            " WHERE tipo_correto = ?",
            (codigo,),
        ).fetchone()
    return {
        "documentos": int(uso["total_documentos"] or 0),
        "casos": int(uso["total_casos"] or 0),
        "correcoes": int(correcoes["total_correcoes"] or 0),
    }


def impacto(codigo: str) -> dict[str, Any]:
    """O que muda — e o que não muda — se este tipo for editado ou desativado."""
    tipo = obter(codigo)
    if tipo is None:
        raise TipoNaoEncontrado(f"O tipo “{codigo}” não está no glossário.")
    itens = itens_do_checklist(codigo)
    uso = _uso_em_documentos(codigo, itens)
    bloqueio = motivo_bloqueio_desativacao(tipo)
    documentos = uso["documentos"]

    if documentos:
        renomear = (
            f"O novo nome passa a aparecer na reclassificação e nas próximas leituras. "
            f"Os {documentos} documento(s) já classificados continuam com este tipo — "
            "só o nome exibido muda."
        )
        desativar = (
            f"O tipo sai das opções de classificação. Os {documentos} documento(s) que "
            "já o usam continuam como estão, e o histórico é preservado."
        )
    else:
        renomear = "Nenhum documento usa este tipo ainda: renomear não afeta nada já classificado."
        desativar = "O tipo sai das opções de classificação. Nenhum documento o usa."

    return {
        "tipo": tipo,
        "itens_checklist": itens,
        **uso,
        "pode_desativar": bloqueio is None,
        "bloqueio_desativacao": bloqueio,
        "efeitos": {
            "codigo": (
                "O código não muda: é ele que fica gravado em cada documento "
                "classificado e em cada correção."
            ),
            "renomear": renomear,
            "sinonimos": (
                "Sinônimos entram na leitura automática dos próximos documentos; não "
                "reclassificam os que já foram lidos."
            ),
            "desativar": bloqueio or desativar,
        },
    }


# ------------------------------------------------------------------- rotas

roteador = APIRouter(prefix="/api/tipos-documento", tags=["tipos-documento"])

PodeManter = Depends(auth.exigir_modulo(MODULO))


class PedidoNovoTipo(BaseModel):
    nome: str = Field(..., max_length=LIMITE_NOME * 2)
    codigo: str | None = Field(None, max_length=80)
    descricao: str = Field("", max_length=LIMITE_DESCRICAO * 2)
    sinonimos: list[str] = Field(default_factory=list, max_length=MAXIMO_SINONIMOS * 2)
    #: Códigos das categorias (tipos de caso) em que o tipo passa a ser pedido.
    categorias: list[str] = Field(default_factory=list, max_length=50)


class PedidoEdicaoTipo(BaseModel):
    nome: str = Field(..., max_length=LIMITE_NOME * 2)
    descricao: str = Field("", max_length=LIMITE_DESCRICAO * 2)
    sinonimos: list[str] = Field(default_factory=list, max_length=MAXIMO_SINONIMOS * 2)
    ativo: bool = True
    versao: int
    #: Ausente mantém os tipos de caso marcados; lista vazia desmarca todos.
    categorias: list[str] | None = Field(None, max_length=50)
    motivo: str = Field("", max_length=600)


def _quem(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.usuario or usuario.id or "escritório"


def _http(exc: ErroGlossario) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@roteador.get("")
def listar_tipos(incluir_inativos: bool = Query(False)) -> dict[str, Any]:
    """O glossário. Livre para a equipe: a reclassificação precisa desta lista."""
    return {"tipos": listar(incluir_inativos)}


@roteador.get("/{codigo}")
def obter_tipo(codigo: str) -> dict[str, Any]:
    tipo = obter(codigo)
    if tipo is None:
        raise HTTPException(404, f"O tipo “{codigo}” não está no glossário.")
    return tipo


@roteador.get("/{codigo}/impacto")
def impacto_do_tipo(codigo: str) -> dict[str, Any]:
    try:
        return impacto(codigo)
    except ErroGlossario as exc:
        raise _http(exc) from exc


@roteador.get("/{codigo}/historico")
def historico_do_tipo(codigo: str) -> dict[str, Any]:
    return {
        "eventos": historico.listar(historico.ENTIDADE_TIPO_DOCUMENTO, codigo)
    }


@roteador.post("", status_code=201)
def criar_tipo(
    pedido: PedidoNovoTipo, usuario: auth.Usuario = PodeManter
) -> dict[str, Any]:
    try:
        return criar(
            nome=pedido.nome,
            codigo=pedido.codigo,
            descricao=pedido.descricao,
            sinonimos=pedido.sinonimos,
            categorias_caso=pedido.categorias,
            usuario=_quem(usuario),
        )
    except ErroGlossario as exc:
        raise _http(exc) from exc


@roteador.put("/{codigo}")
def editar_tipo(
    codigo: str, pedido: PedidoEdicaoTipo, usuario: auth.Usuario = PodeManter
) -> dict[str, Any]:
    try:
        return editar(
            codigo,
            nome=pedido.nome,
            descricao=pedido.descricao,
            sinonimos=pedido.sinonimos,
            ativo=pedido.ativo,
            versao=pedido.versao,
            usuario=_quem(usuario),
            motivo=pedido.motivo,
            categorias_caso=pedido.categorias,
        )
    except ErroGlossario as exc:
        raise _http(exc) from exc
