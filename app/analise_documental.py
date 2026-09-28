"""Análise documental do caso, EXECUTANDO a skill `analise-e-organizacao-documental`.

QUEM DECIDE O QUÊ

- A SKILL decide como analisar: o que é análise documento a documento, como classificar risco e
  documento faltante (🔴/🟡/⚪), o que é duplicidade, como nomear e ordenar. Ela é lida em tempo de
  execução (`skill_de_arquivo`) e entra na instrução exatamente como está escrita.
- ESTE MÓDULO cuida do que não é conhecimento de domínio: montar o material (documentos lidos),
  fixar o formato de resposta (contrato `DocumentAnalysis`), conferir a proveniência de cada
  conclusão, persistir com a versão da skill, e aplicar a resposta humana.

Não existe aqui lista de documentos obrigatórios, ordem de pasta, regra de nomenclatura nem
critério jurídico: tudo isso vem da skill. O que o código impõe por INTEGRIDADE (e por que não
pode depender só da skill):

1. Toda conclusão factual (fato, inconsistência, prova) precisa apontar documento + trecho LITERAL
   conferível no texto lido. O modelo pode errar ou alucinar; conferir citação é verificação
   mecânica, não conhecimento jurídico. O que não se confere é descartado e contado
   (`descartados`), nunca mostrado como fato.
2. Nenhum documento do caso some da análise: se o modelo não o cobriu, entra como "não
   identificado". Descartar documento é decisão humana (a skill diz: só com autorização expressa).
3. O vocabulário de classificação de faltante e de status é fechado, porque a tela e o gate de
   organização dependem dele.

Reaproveita `analise_documentos` (leitura dos anexos, chamada ao modelo, conferência de citação)
e `case_brief_estado` (estado humano CONFIRMED/CORRECTED/REJECTED) — não cria outro mecanismo.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Protocol

from . import analise_documentos, armazenamento, skill_de_arquivo

log = logging.getLogger("analise_documental")

NOME_DA_SKILL = skill_de_arquivo.SKILL_DOCUMENTAL

#: Estados do ciclo (compatíveis com a fila de OCR existente: o OCR roda ANTES, nas entregas).
STATUS = ("queued", "processing", "analyzing", "ready", "error")

CLASSIFICACOES_DE_FALTANTE = ("COMPROMETE", "ERA_MELHOR_TER", "NAO_INTERFERE")

#: Teto do texto enviado ao modelo (todas as entregas, fatiadas). Mesmo motivo de
#: `analise_documentos.MAX_CARACTERES_TOTAL`.
MAX_CARACTERES_TOTAL = int(os.getenv("ANALISE_DOCUMENTAL_MAX_CARACTERES", "250000"))
MAX_CARACTERES_POR_DOCUMENTO = int(os.getenv("ANALISE_DOCUMENTAL_MAX_CARACTERES_DOCUMENTO", "25000"))
TEMPO_MINIMO_POR_DOCUMENTO = 700


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ instrução (skill + contrato)

#: O que NÃO é conhecimento de domínio: o formato da resposta e as regras de integridade dos dados.
_ORQUESTRACAO = """Você executa a SKILL DOCUMENTAL abaixo sobre os documentos deste caso. A skill é a
AUTORIDADE sobre como analisar, classificar riscos e documentos faltantes, tratar duplicidade e nomear/ordenar
a pasta; este texto só fixa o FORMATO da resposta e as regras de INTEGRIDADE dos dados.

Você está na Etapa 3 da skill (análise) e prepara o plano da Etapa 5, mas NÃO organiza nada: a parada
obrigatória da Etapa 4 (confirmação humana) é feita pelo sistema depois.

Devolva APENAS JSON com estas chaves (todas obrigatórias; lista vazia é resposta válida):
{
 "diagnostico": {"sentido":"POSITIVO|NEGATIVO","motivo":"uma frase: os documentos sustentam o caso, ou há contradição/lacuna que o compromete"},
 "resumo_do_caso": {"fatos_cronologicos":[{"data":"","fato":"","documento_id":""}],
                    "partes":[{"nome":"","papel":""}], "questao_central":"", "objetivo_do_cliente":""},
 "documentos": [{"documento_id":"id exato da lista","tipo":"o que o documento É","nome_sugerido":"nome pela nomenclatura da skill, sem prefixo Doc N",
                 "pessoal":true|false,"data":"AAAA-MM-DD ou vazio","paginas":número ou null,
                 "dados_principais":[{"campo":"","valor":"","citacao":"trecho LITERAL do documento"}],
                 "pontos_fortes":[""],"vulnerabilidades":[""],"inconsistencias":[""],
                 "atualizacao":"ATUALIZADO|DESATUALIZADO|NAO_SE_APLICA","pode_melhorar":true|false|null,
                 "motivo_atualizacao":"","legivel":true|false,"problema":"","duplicado_de":"documento_id ou vazio",
                 "relacao_com_teses":[{"hipotese":"","papel":"que requisito resolve / o que ainda falta"}]}],
 "fatos_extraidos": [{"fato":"","documento_id":"","citacao":"trecho LITERAL","confianca":"alta|media|baixa"}],
 "inconsistencias": [{"titulo":"","tipo":"NOME|CPF|ENDERECO|DATA|VALOR|ASSINATURA|OUTRA",
                      "fontes":[{"documento_id":"","citacao":"trecho LITERAL","valor":"o que este trecho diz"}],
                      "impacto":"por que importa","acao_sugerida":""}],
 "provas": [{"fato":"","status":"SUFICIENTE|FRACA","documento_ids":[""],"observacao":""}],
 "documentos_faltantes": [{"documento":"","hipotese":"para qual ação/hipótese","classificacao":"COMPROMETE|ERA_MELHOR_TER|NAO_INTERFERE",
                           "como_obter":"canal, fundamento, prazo","responsavel":"cliente|escritório|empregador|órgão","prazo_ou_dificuldade":""}],
 "hipoteses_juridicas": [{"hipotese":"","objeto":"","fundamento_legal":"","requisitos":[""],"documentos_necessarios":[""],
                          "pontos_fortes":[""],"pontos_fracos":[""],"riscos":[{"risco":"","nivel":"ALTO|MEDIO|BAIXO"}],
                          "probabilidade_pratica":"ALTA|MEDIA|BAIXA e o motivo","documento_ids":[""]}],
 "perguntas": [{"pergunta":"pergunta ACIONÁVEL","motivo":"","fontes":[{"documento_id":"","citacao":""}]}],
 "proximos_passos": [""]
}

INTEGRIDADE (vale para qualquer skill):
- Todo item de fatos_extraidos, inconsistencias e dados_principais traz `documento_id` EXATO da lista e uma
  `citacao` copiada LITERALMENTE do texto daquele documento. Sem citação conferível, o item não existe.
- Inconsistência exige PELO MENOS DUAS fontes que realmente divergem (dois documentos, ou documento e o
  cadastro/entrevista informados abaixo — nesse caso use documento_id "cadastro" ou "entrevista" e cite o que consta lá).
  Não invente divergência; nome grafado diferente por erro de OCR não é inconsistência sem conferir.
- `diagnostico.sentido` é POSITIVO só quando não há inconsistência conferida e nenhum faltante COMPROMETE.
  Havendo contradição ou faltante que compromete a hipótese, o sentido é NEGATIVO. O motivo cita o que
  os documentos mostram, sem percentual.
- Não invente fato, dado do cliente, dispositivo legal, jurisprudência nem probabilidade numérica. Lacuna
  vira `perguntas` (acionáveis), não suposição.
- Cubra TODOS os documentos da lista em `documentos`, inclusive os ilegíveis ou sem texto (legivel=false).
- EXTRAIA O MÁXIMO de cada documento: leia o texto inteiro, do começo ao fim, e registre em
  `dados_principais` CADA dado útil (datas, valores, CIDs, números de benefício/processo, funções, salários,
  períodos, nomes e papéis, conclusões) — um item por dado, sem escolher só o "principal". O mesmo vale para
  `fatos_extraidos` e `resumo_do_caso.fatos_cronologicos`: todo fato datado que os documentos registram. Um
  dado a mais nunca atrapalha; um dado que passa despercebido pode custar um pedido.
- Em conflito entre `SKILL.md` e `references/nomenclatura.md` sobre o FORMATO do nome do arquivo, vale o `SKILL.md`
  (é o que o script `montar.py` implementa)."""


def instrucao_da_skill() -> tuple[str, dict[str, Any]]:
    """A instrução completa (orquestração mínima + skill lida do disco) e o resumo da skill usada."""
    skill = skill_de_arquivo.carregar(NOME_DA_SKILL)
    # Trechos do SKILL.md que governam a ANÁLISE e o plano de organização. São lidos por título:
    # mudar a skill muda o que o modelo recebe, sem tocar neste código.
    partes = [
        skill.secao(r"^Regra de ouro"),
        skill.secao(r"Arquivos duplicados"),
        skill.secao(r"^Etapa 3"),
        skill.secao(r"^Nomenclatura obrigat"),
        skill.secao(r"^Ordem obrigat"),
        skill.secao(r"^Regras que não se flexibilizam"),
        "### references/nomenclatura.md\n" + skill.ler("references/nomenclatura.md"),
    ]
    corpo = "\n\n".join(p for p in partes if p)
    instrucao = f"{_ORQUESTRACAO}\n\n=== SKILL DOCUMENTAL: {NOME_DA_SKILL} ===\n{corpo}"
    return instrucao, {**skill.resumo(), "trechos_carregados": [p.splitlines()[0][:80] for p in partes if p]}


# ------------------------------------------------------------------ armazenamento

class Armazenamento(Protocol):
    def proxima_versao(self, caso_id: str) -> int: ...
    def criar(self, registro: dict[str, Any]) -> None: ...
    def atualizar(self, analise_id: str, **campos: Any) -> None: ...
    def ultima(self, caso_id: str) -> dict[str, Any] | None: ...
    def salvar_resposta(self, caso_id: str, analise_id: str, pergunta_id: str, resposta: str, usuario: str) -> None: ...
    def respostas(self, caso_id: str) -> dict[str, dict[str, Any]]: ...
    def salvar_organizacao(self, registro: dict[str, Any]) -> None: ...
    def organizacao(self, caso_id: str) -> dict[str, Any] | None: ...


class ArmazenamentoMemoria:
    """Para testes e para rodar sem Postgres: mesmo contrato, nada persiste entre processos."""

    def __init__(self) -> None:
        self.analises: list[dict[str, Any]] = []
        self._respostas: dict[tuple[str, str], dict[str, Any]] = {}
        self._organizacoes: dict[str, dict[str, Any]] = {}

    def proxima_versao(self, caso_id: str) -> int:
        return 1 + max((a["versao"] for a in self.analises if a["caso_id"] == caso_id), default=0)

    def criar(self, registro: dict[str, Any]) -> None:
        self.analises.append(dict(registro))

    def atualizar(self, analise_id: str, **campos: Any) -> None:
        for a in self.analises:
            if a["id"] == analise_id:
                a.update(campos)

    def ultima(self, caso_id: str) -> dict[str, Any] | None:
        doCaso = [a for a in self.analises if a["caso_id"] == caso_id]
        return dict(max(doCaso, key=lambda a: a["versao"])) if doCaso else None

    def salvar_resposta(self, caso_id, analise_id, pergunta_id, resposta, usuario):
        self._respostas[(caso_id, pergunta_id)] = {
            "pergunta_id": pergunta_id, "resposta": resposta, "usuario": usuario,
            "analise_id": analise_id, "respondida_em": _agora(),
        }

    def respostas(self, caso_id: str) -> dict[str, dict[str, Any]]:
        return {p: dict(v) for (c, p), v in self._respostas.items() if c == caso_id}

    def salvar_organizacao(self, registro: dict[str, Any]) -> None:
        self._organizacoes[registro["caso_id"]] = dict(registro)

    def organizacao(self, caso_id: str) -> dict[str, Any] | None:
        registro = self._organizacoes.get(caso_id)
        return dict(registro) if registro else None


class ArmazenamentoPostgres:
    """Mesmo banco e mesma conexão do estado do case brief (`case_brief_estado`)."""

    def __init__(self) -> None:
        from . import case_brief_estado

        self._estado = case_brief_estado
        self._pronto = False

    def _con(self, **kw: Any):
        return self._estado._conectar(**kw)  # noqa: SLF001 - mesma infraestrutura de conexão

    def inicializar(self) -> None:
        if self._pronto:
            return
        with self._con() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS analises_documentais (
                    id            uuid PRIMARY KEY,
                    caso_id       varchar(64) NOT NULL,
                    versao        integer NOT NULL,
                    status        varchar(20) NOT NULL,
                    skill_name    varchar(120) NOT NULL DEFAULT '',
                    skill_sha256  varchar(64) NOT NULL DEFAULT '',
                    modelo        varchar(120) NOT NULL DEFAULT '',
                    iniciada_em   timestamptz NOT NULL DEFAULT now(),
                    concluida_em  timestamptz,
                    resultado     jsonb,
                    erro          text NOT NULL DEFAULT '',
                    revisada_em   timestamptz,
                    UNIQUE (caso_id, versao)
                )""")
            con.execute("""
                CREATE TABLE IF NOT EXISTS analise_documental_respostas (
                    caso_id       varchar(64) NOT NULL,
                    pergunta_id   varchar(80) NOT NULL,
                    analise_id    uuid NOT NULL,
                    resposta      text NOT NULL,
                    usuario       varchar(200) NOT NULL DEFAULT '',
                    respondida_em timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (caso_id, pergunta_id)
                )""")
            con.execute("""
                CREATE TABLE IF NOT EXISTS organizacoes_documentais (
                    caso_id       varchar(64) PRIMARY KEY,
                    analise_id    uuid,
                    status        varchar(30) NOT NULL,
                    plano         jsonb,
                    resultado     jsonb,
                    confirmada_por varchar(200) NOT NULL DEFAULT '',
                    confirmada_em timestamptz,
                    atualizada_em timestamptz NOT NULL DEFAULT now()
                )""")
        self._pronto = True

    def proxima_versao(self, caso_id: str) -> int:
        self.inicializar()
        with self._con() as con:
            linha = con.execute("SELECT COALESCE(MAX(versao),0) FROM analises_documentais WHERE caso_id=%s", (caso_id,)).fetchone()
        return int(linha[0]) + 1

    def criar(self, r: dict[str, Any]) -> None:
        self.inicializar()
        with self._con() as con:
            con.execute(
                """INSERT INTO analises_documentais (id,caso_id,versao,status,skill_name,skill_sha256,modelo,iniciada_em)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (r["id"], r["caso_id"], r["versao"], r["status"], r.get("skill_name", ""), r.get("skill_sha256", ""),
                 r.get("modelo", ""), r["iniciada_em"]),
            )

    def atualizar(self, analise_id: str, **campos: Any) -> None:
        if not campos:
            return
        colunas, valores = [], []
        for k, v in campos.items():
            colunas.append(f"{k} = %s")
            valores.append(json.dumps(v, ensure_ascii=False) if k == "resultado" and v is not None else v)
        with self._con() as con:
            con.execute(f"UPDATE analises_documentais SET {', '.join(colunas)} WHERE id = %s", (*valores, analise_id))

    def ultima(self, caso_id: str) -> dict[str, Any] | None:
        self.inicializar()
        from psycopg.rows import dict_row

        with self._con(row_factory=dict_row) as con:
            linha = con.execute(
                "SELECT * FROM analises_documentais WHERE caso_id=%s ORDER BY versao DESC LIMIT 1", (caso_id,)
            ).fetchone()
        if not linha:
            return None
        registro = dict(linha)
        registro["id"] = str(registro["id"])
        for k in ("iniciada_em", "concluida_em", "revisada_em"):
            if registro.get(k) is not None:
                registro[k] = registro[k].isoformat(timespec="seconds")
        return registro

    def salvar_resposta(self, caso_id, analise_id, pergunta_id, resposta, usuario):
        self.inicializar()
        with self._con() as con:
            con.execute(
                """INSERT INTO analise_documental_respostas (caso_id,pergunta_id,analise_id,resposta,usuario)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (caso_id,pergunta_id) DO UPDATE SET resposta=EXCLUDED.resposta,
                        usuario=EXCLUDED.usuario, analise_id=EXCLUDED.analise_id, respondida_em=now()""",
                (caso_id, pergunta_id, analise_id, resposta, usuario),
            )

    def respostas(self, caso_id: str) -> dict[str, dict[str, Any]]:
        self.inicializar()
        from psycopg.rows import dict_row

        with self._con(row_factory=dict_row) as con:
            linhas = con.execute("SELECT * FROM analise_documental_respostas WHERE caso_id=%s", (caso_id,)).fetchall()
        return {l["pergunta_id"]: {**l, "analise_id": str(l["analise_id"]), "respondida_em": l["respondida_em"].isoformat(timespec="seconds")} for l in linhas}

    def salvar_organizacao(self, r: dict[str, Any]) -> None:
        self.inicializar()
        with self._con() as con:
            con.execute(
                """INSERT INTO organizacoes_documentais (caso_id,analise_id,status,plano,resultado,confirmada_por,confirmada_em,atualizada_em)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (caso_id) DO UPDATE SET analise_id=EXCLUDED.analise_id,status=EXCLUDED.status,
                     plano=EXCLUDED.plano,resultado=EXCLUDED.resultado,confirmada_por=EXCLUDED.confirmada_por,
                     confirmada_em=EXCLUDED.confirmada_em,atualizada_em=now()""",
                (r["caso_id"], r.get("analise_id"), r["status"], json.dumps(r.get("plano"), ensure_ascii=False),
                 json.dumps(r.get("resultado"), ensure_ascii=False), r.get("confirmada_por", ""), r.get("confirmada_em")),
            )

    def organizacao(self, caso_id: str) -> dict[str, Any] | None:
        self.inicializar()
        from psycopg.rows import dict_row

        with self._con(row_factory=dict_row) as con:
            linha = con.execute("SELECT * FROM organizacoes_documentais WHERE caso_id=%s", (caso_id,)).fetchone()
        return dict(linha) if linha else None


_ARMAZENAMENTO: Armazenamento | None = None


def armazenamento_padrao() -> Armazenamento:
    global _ARMAZENAMENTO
    if _ARMAZENAMENTO is None:
        _ARMAZENAMENTO = ArmazenamentoPostgres()
    return _ARMAZENAMENTO


def usar_armazenamento(novo: Armazenamento | None) -> None:
    """Injeção (testes)."""
    global _ARMAZENAMENTO
    _ARMAZENAMENTO = novo


# ------------------------------------------------------------------ material do modelo

def _documentos(caso_id: str) -> list[dict[str, Any]]:
    """TODOS os anexos do caso (com ou sem texto): nenhum documento some da análise."""
    saida = []
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        texto = str((entrega.get("extracao") or {}).get("texto_completo") or "").strip()
        saida.append({"id": str(entrega["id"]), "arquivo": str(entrega.get("arquivo") or ""), "texto": texto,
                      "status_proc": entrega.get("status_proc")})
    return saida


def montar_mensagem(documentos: list[dict[str, Any]], entrevista: str, cadastro: str) -> str:
    partes = ["CADASTRO DO CLIENTE (documento_id \"cadastro\"):\n" + (cadastro or "(sem cadastro)"),
              "\nENTREVISTA (documento_id \"entrevista\"):\n" + ((entrevista or "(sem entrevista)")[:12000]),
              "\nDOCUMENTOS DO CASO (use o documento_id exato):"]
    com_texto = [d for d in documentos if d["texto"]]
    cabecalhos = sum(len(f"\n=== documento_id={d['id']} | arquivo={d['arquivo']} ===\n") for d in documentos)
    disponivel = max(0, MAX_CARACTERES_TOTAL - cabecalhos - 14000)
    limite = min(
        MAX_CARACTERES_POR_DOCUMENTO,
        max(
            TEMPO_MINIMO_POR_DOCUMENTO,
            analise_documentos._limite_por_documento(  # noqa: SLF001 - mesma divisão do orçamento
                [len(d["texto"]) for d in com_texto], disponivel
            ),
        ),
    )
    for d in documentos:
        cab = f"\n=== documento_id={d['id']} | arquivo={d['arquivo']} ==="
        if not d["texto"]:
            partes.append(cab + "\n[SEM TEXTO LIDO — ilegível ou ainda em leitura; marque legivel=false]")
        else:
            partes.append(cab + "\n" + analise_documentos._fatia(d["texto"], limite))  # noqa: SLF001
    return "\n".join(partes)


# ------------------------------------------------------------------ validação do contrato + proveniência

def _norm(t: str) -> str:
    return analise_documentos._normalizar(t)  # noqa: SLF001 - mesma regra de conferência de citação


def _citacao_confere(citacao: str, texto: str) -> bool:
    c = _norm(citacao)
    return len(c) >= 6 and c in _norm(texto)


def _pagina_da_citacao(texto: str, citacao: str) -> int | None:
    """Página onde o trecho está, SE o texto lido trouxer marcas de página (form feed).

    A extração atual guarda o texto do documento inteiro, sem página; nesse caso devolve None
    em vez de inventar (pendência conhecida: OCR por página persistida).
    """
    if "\f" not in texto:
        return None
    for n, pagina in enumerate(texto.split("\f"), start=1):
        if _citacao_confere(citacao, pagina):
            return n
    return None


def _diagnostico_documental(
    bruto: dict[str, Any], inconsistencias: list[dict[str, Any]], faltantes: list[dict[str, Any]],
) -> dict[str, str]:
    """Positivo ou negativo. Contradição conferida ou faltante que compromete nunca é positivo."""
    compromete = [f for f in faltantes if f.get("classificacao") == "COMPROMETE"]
    sentido = "NEGATIVO" if inconsistencias or compromete else "POSITIVO"
    if inconsistencias and compromete:
        motivo = (
            f"Diagnóstico negativo: {len(inconsistencias)} contradição(ões) entre os documentos "
            f"e {len(compromete)} documento(s) faltante(s) que comprometem a hipótese."
        )
    elif inconsistencias:
        motivo = f"Diagnóstico negativo: {len(inconsistencias)} contradição(ões) entre os documentos."
    elif compromete:
        motivo = (
            "Diagnóstico negativo: falta documento sem o qual a hipótese não se sustenta ("
            + "; ".join(str(f.get("documento") or "") for f in compromete[:3])
            + ")."
        )
    else:
        motivo = "Diagnóstico positivo: os documentos não se contradizem e não falta peça que comprometa a hipótese."
    informado = bruto.get("diagnostico") if isinstance(bruto.get("diagnostico"), dict) else {}
    if str(informado.get("sentido") or "").strip().upper() == sentido:
        texto = str(informado.get("motivo") or "").strip()
        if texto:
            motivo = texto[:400]
    return {"sentido": sentido, "motivo": motivo}


def validar_contrato(
    bruto: dict[str, Any], documentos: list[dict[str, Any]], *, entrevista: str = "", cadastro: str = ""
) -> dict[str, Any]:
    """Normaliza a resposta ao contrato `DocumentAnalysis` e DESCARTA o que não tem proveniência."""
    por_id = {d["id"]: d for d in documentos}
    por_arquivo = {d["arquivo"]: d for d in documentos}
    externos = {"entrevista": entrevista, "cadastro": cadastro}
    descartados: dict[str, int] = {}

    def resolver(ref: Any) -> dict[str, Any] | None:
        ref = str(ref or "").strip()
        if ref in por_id:
            return por_id[ref]
        if ref in por_arquivo:
            return por_arquivo[ref]
        resolvido = analise_documentos._resolver_arquivo(ref, por_arquivo)  # noqa: SLF001
        return por_arquivo.get(resolvido)

    def descartar(chave: str) -> None:
        descartados[chave] = descartados.get(chave, 0) + 1

    def fonte_verificada(f: Any) -> dict[str, Any] | None:
        if not isinstance(f, dict):
            return None
        ref = str(f.get("documento_id") or "").strip().lower()
        citacao = str(f.get("citacao") or f.get("valor") or "")
        if ref in externos:
            return {"origem": ref, "documento_id": ref, "citacao": citacao, "valor": str(f.get("valor") or "")} if _citacao_confere(citacao, externos[ref]) else None
        doc = resolver(f.get("documento_id"))
        if doc and _citacao_confere(str(f.get("citacao") or ""), doc["texto"]):
            return {"documento_id": doc["id"], "arquivo": doc["arquivo"], "citacao": str(f["citacao"]),
                    "valor": str(f.get("valor") or ""), "pagina": _pagina_da_citacao(doc["texto"], str(f["citacao"]))}
        return None

    def lista(chave: str) -> list[Any]:
        v = bruto.get(chave)
        return v if isinstance(v, list) else []

    # -- documentos: um por anexo do caso, sempre
    identificados: dict[str, dict[str, Any]] = {}
    for item in lista("documentos"):
        if not isinstance(item, dict):
            continue
        doc = resolver(item.get("documento_id"))
        if doc is None or doc["id"] in identificados:
            descartar("documentos_sem_id_valido")
            continue
        dados = []
        for d in item.get("dados_principais") or []:
            if isinstance(d, dict) and _citacao_confere(str(d.get("citacao") or ""), doc["texto"]):
                dados.append({"campo": str(d.get("campo") or ""), "valor": str(d.get("valor") or ""), "citacao": str(d["citacao"]),
                              "pagina": _pagina_da_citacao(doc["texto"], str(d["citacao"]))})
            else:
                descartar("dados_principais")
        dup = resolver(item.get("duplicado_de"))
        identificados[doc["id"]] = {
            "documento_id": doc["id"], "arquivo": doc["arquivo"],
            "tipo": str(item.get("tipo") or "NÃO IDENTIFICADO"),
            "nome_sugerido": str(item.get("nome_sugerido") or item.get("tipo") or ""),
            "pessoal": bool(item.get("pessoal")), "data": str(item.get("data") or ""),
            "paginas": item.get("paginas") if isinstance(item.get("paginas"), int) else None,
            "dados_principais": dados,
            "pontos_fortes": [str(x) for x in item.get("pontos_fortes") or []],
            "vulnerabilidades": [str(x) for x in item.get("vulnerabilidades") or []],
            "inconsistencias": [str(x) for x in item.get("inconsistencias") or []],
            "atualizacao": str(item.get("atualizacao") or "NAO_SE_APLICA"),
            "pode_melhorar": item.get("pode_melhorar") if isinstance(item.get("pode_melhorar"), bool) else None,
            "motivo_atualizacao": str(item.get("motivo_atualizacao") or ""),
            "legivel": bool(item.get("legivel", True)) and bool(doc["texto"]),
            "problema": str(item.get("problema") or ("" if doc["texto"] else "sem texto lido")),
            "duplicado_de": dup["id"] if dup and dup["id"] != doc["id"] else "",
            "relacao_com_teses": [r for r in item.get("relacao_com_teses") or [] if isinstance(r, dict)],
        }
    for doc in documentos:  # nenhum documento some
        identificados.setdefault(doc["id"], {
            "documento_id": doc["id"], "arquivo": doc["arquivo"], "tipo": "NÃO IDENTIFICADO", "nome_sugerido": "",
            "pessoal": False, "data": "", "paginas": None, "dados_principais": [], "pontos_fortes": [],
            "vulnerabilidades": [], "inconsistencias": [], "atualizacao": "NAO_SE_APLICA", "pode_melhorar": None,
            "motivo_atualizacao": "", "legivel": bool(doc["texto"]),
            "problema": "não coberto pela análise" if doc["texto"] else "sem texto lido",
            "duplicado_de": "", "relacao_com_teses": [],
        })

    # -- fatos (proveniência obrigatória)
    fatos = []
    for item in lista("fatos_extraidos"):
        f = fonte_verificada({"documento_id": (item or {}).get("documento_id"), "citacao": (item or {}).get("citacao")}) if isinstance(item, dict) else None
        if not f or f.get("origem") or not str(item.get("fato") or "").strip():
            descartar("fatos_sem_proveniencia")
            continue
        fatos.append({"id": f"dfato-{len(fatos) + 1}", "fato": str(item["fato"]), "confianca": str(item.get("confianca") or "media"),
                      "proveniencia": {"documento_id": f["documento_id"], "arquivo": f["arquivo"], "pagina": f["pagina"],
                                       "tipo_documento": identificados[f["documento_id"]]["tipo"], "citacao": f["citacao"]}})

    # -- inconsistências (>= 2 fontes que conferem)
    inconsistencias = []
    for item in lista("inconsistencias"):
        if not isinstance(item, dict):
            continue
        fontes = [x for x in (fonte_verificada(f) for f in item.get("fontes") or []) if x]
        if len(fontes) < 2:
            descartar("inconsistencias_sem_duas_fontes")
            continue
        inconsistencias.append({"id": f"dinc-{len(inconsistencias) + 1}", "titulo": str(item.get("titulo") or ""),
                                "tipo": str(item.get("tipo") or "OUTRA"), "fontes": fontes,
                                "impacto": str(item.get("impacto") or ""), "acao_sugerida": str(item.get("acao_sugerida") or "")})

    # -- provas
    provas = []
    for item in lista("provas"):
        if not isinstance(item, dict):
            continue
        ids = [d["id"] for d in (resolver(x) for x in item.get("documento_ids") or []) if d]
        if not ids or not str(item.get("fato") or "").strip():
            descartar("provas_sem_documento")
            continue
        provas.append({"id": f"dprova-{len(provas) + 1}", "fato": str(item["fato"]), "status": str(item.get("status") or "FRACA").upper(),
                       "documento_ids": ids, "observacao": str(item.get("observacao") or "")})

    # -- faltantes (vocabulário fechado; sem "faltando PPP" solto)
    faltantes = []
    for item in lista("documentos_faltantes"):
        if not isinstance(item, dict):
            continue
        cls = str(item.get("classificacao") or "").upper().replace(" ", "_")
        if cls not in CLASSIFICACOES_DE_FALTANTE or not str(item.get("documento") or "").strip() \
                or not str(item.get("hipotese") or "").strip() or not str(item.get("como_obter") or "").strip():
            descartar("faltantes_incompletos")
            continue
        faltantes.append({"id": f"dfalt-{len(faltantes) + 1}", "documento": str(item["documento"]), "hipotese": str(item["hipotese"]),
                          "classificacao": cls, "como_obter": str(item["como_obter"]),
                          "responsavel": str(item.get("responsavel") or ""), "prazo_ou_dificuldade": str(item.get("prazo_ou_dificuldade") or "")})

    # -- hipóteses (fundamento legal vai marcado como NÃO verificado: a skill proíbe citar de memória)
    hipoteses = []
    for item in lista("hipoteses_juridicas"):
        if isinstance(item, dict) and str(item.get("hipotese") or "").strip():
            hipoteses.append({**{k: item.get(k) for k in ("hipotese", "objeto", "fundamento_legal", "requisitos",
                              "documentos_necessarios", "pontos_fortes", "pontos_fracos", "riscos", "probabilidade_pratica")},
                              "id": f"dhip-{len(hipoteses) + 1}", "fundamento_verificado": False,
                              "documento_ids": [d["id"] for d in (resolver(x) for x in item.get("documento_ids") or []) if d]})

    # -- perguntas
    perguntas = []
    for item in lista("perguntas"):
        if isinstance(item, dict) and str(item.get("pergunta") or "").strip():
            perguntas.append({"id": f"dperg-{len(perguntas) + 1}", "pergunta": str(item["pergunta"]), "motivo": str(item.get("motivo") or ""),
                              "fontes": [x for x in (fonte_verificada(f) for f in item.get("fontes") or []) if x]})

    resumo = bruto.get("resumo_do_caso") if isinstance(bruto.get("resumo_do_caso"), dict) else {}
    return {
        "diagnostico": _diagnostico_documental(bruto, inconsistencias, faltantes),
        "resumo_do_caso": {
            "fatos_cronologicos": [c for c in resumo.get("fatos_cronologicos") or [] if isinstance(c, dict)],
            "partes": [p for p in resumo.get("partes") or [] if isinstance(p, dict)],
            "questao_central": str(resumo.get("questao_central") or ""),
            "objetivo_do_cliente": str(resumo.get("objetivo_do_cliente") or ""),
        },
        "documentos": list(identificados.values()),
        "fatos_extraidos": fatos, "inconsistencias": inconsistencias, "provas": provas,
        "documentos_faltantes": faltantes, "hipoteses_juridicas": hipoteses,
        "riscos": [r for h in hipoteses for r in (h.get("riscos") or []) if isinstance(r, dict)],
        "perguntas": perguntas, "proximos_passos": [str(x) for x in lista("proximos_passos")],
        "descartados": descartados,
    }


# ------------------------------------------------------------------ execução

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analise-documental")
_EM_ANDAMENTO: dict[str, str] = {}
_TRAVA = threading.Lock()


def _contexto_humano(caso_id: str) -> tuple[str, str]:
    caso = armazenamento.obter_caso(caso_id) or {}
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001
        qualificacao = {}
    cadastro = " | ".join(f"{k}: {v}" for k, v in [("cliente", caso.get("cliente")), *qualificacao.items()] if v)
    entrevistas = [e for e in armazenamento.listar_entrevistas(caso_id) if str(e.get("texto") or "").strip()]
    return cadastro, str(entrevistas[0]["texto"]) if entrevistas else ""


def executar(caso_id: str, analise_id: str, *, chamar_modelo=None, store: Armazenamento | None = None) -> dict[str, Any]:
    """Roda a análise (síncrono; use `iniciar` para o caminho assíncrono da API)."""
    store = store or armazenamento_padrao()
    chamar = chamar_modelo or analise_documentos._chamar_modelo  # noqa: SLF001
    try:
        store.atualizar(analise_id, status="processing")
        instrucao, skill = instrucao_da_skill()
        log.info("análise documental %s: skill=%s sha=%s trechos=%s", caso_id, skill["skill_name"],
                 skill["skill_sha256"][:16], skill["trechos_carregados"])
        documentos = _documentos(caso_id)
        cadastro, entrevista = _contexto_humano(caso_id)
        store.atualizar(analise_id, status="analyzing", skill_name=skill["skill_name"], skill_sha256=skill["skill_sha256"])
        bruto = chamar(montar_mensagem(documentos, entrevista, cadastro), instrucao=instrucao, max_tokens=32000)
        resultado = validar_contrato(bruto, documentos, entrevista=entrevista, cadastro=cadastro)
        resultado["skill"] = skill
        resultado["gerado_em"] = _agora()
        store.atualizar(analise_id, status="ready", resultado=resultado, concluida_em=_agora())
        return resultado
    except Exception as erro:  # noqa: BLE001 - o estado "error" é observável; a falha de UM caso não derruba o worker
        log.exception("análise documental %s falhou", caso_id)
        store.atualizar(analise_id, status="error", erro=f"{type(erro).__name__}: {str(erro)[:400]}")
        raise
    finally:
        with _TRAVA:
            _EM_ANDAMENTO.pop(caso_id, None)


def iniciar(caso_id: str, *, chamar_modelo=None, store: Armazenamento | None = None, sincrono: bool = False) -> dict[str, Any]:
    """Cria a análise (`queued`) e a executa em segundo plano; idempotente por caso."""
    store = store or armazenamento_padrao()
    with _TRAVA:
        if caso_id in _EM_ANDAMENTO:
            atual = store.ultima(caso_id)
            if atual:
                return atual
        analise_id = str(uuid.uuid4())
        _EM_ANDAMENTO[caso_id] = analise_id
    modelo = os.getenv("OPENROUTER_MODELO_ANALISE", "").strip() or "google/gemini-3.7-flash"
    registro = {"id": analise_id, "caso_id": caso_id, "versao": store.proxima_versao(caso_id), "status": "queued",
                "skill_name": NOME_DA_SKILL, "skill_sha256": "", "modelo": modelo, "iniciada_em": _agora()}
    store.criar(registro)
    if sincrono:
        try:
            executar(caso_id, analise_id, chamar_modelo=chamar_modelo, store=store)
        except Exception:  # noqa: BLE001 - o registro guarda o erro
            pass
    else:
        _EXECUTOR.submit(lambda: _seguro(caso_id, analise_id, chamar_modelo, store))
    return store.ultima(caso_id) or registro


def _seguro(caso_id, analise_id, chamar_modelo, store) -> None:
    try:
        executar(caso_id, analise_id, chamar_modelo=chamar_modelo, store=store)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ leitura (com a resposta humana)

def obter(caso_id: str, *, store: Armazenamento | None = None) -> dict[str, Any] | None:
    """A última análise, com o estado humano dos itens e as respostas às perguntas aplicados."""
    store = store or armazenamento_padrao()
    registro = store.ultima(caso_id)
    if not registro:
        return None
    resultado = registro.get("resultado")
    if isinstance(resultado, str):
        resultado = json.loads(resultado)
    if isinstance(resultado, dict):
        respostas = store.respostas(caso_id)
        try:
            from . import case_brief_estado

            estados = case_brief_estado.estados_do_caso(caso_id)
        except Exception:  # noqa: BLE001 - sem estado humano, tudo DETECTED
            estados = {}
        for chave in ("fatos_extraidos", "inconsistencias", "documentos_faltantes"):
            for item in resultado.get(chave) or []:
                if item["id"] in estados:
                    item["estado"] = estados[item["id"]]["estado"]
        for p in resultado.get("perguntas") or []:
            if p["id"] in respostas:
                p["resposta"] = respostas[p["id"]]["resposta"]
        registro = {**registro, "resultado": resultado}
    return registro


def responder(caso_id: str, pergunta_id: str, resposta: str, usuario: str = "", *, store: Armazenamento | None = None) -> None:
    store = store or armazenamento_padrao()
    atual = store.ultima(caso_id)
    if not atual:
        raise ValueError("Não há análise para este caso.")
    if not resposta.strip():
        raise ValueError("A resposta está vazia.")
    store.salvar_resposta(caso_id, atual["id"], pergunta_id, resposta.strip(), usuario)


def contexto_para_peticao(caso_id: str, *, store: Armazenamento | None = None) -> str:
    """A análise documental em texto, para entrar no contexto da GERAÇÃO DA PEÇA.

    Só o que tem proveniência e o que o humano não rejeitou; perguntas respondidas entram como fato
    informado pelo escritório (não como fato de documento). Não substitui a skill da peça: é MATERIAL.
    """
    try:
        registro = obter(caso_id, store=store)
    except Exception as erro:  # noqa: BLE001 - sem análise documental a peça segue como antes
        log.warning("análise documental indisponível para a peça (%s): %s", caso_id, erro)
        return ""
    if not registro or registro.get("status") != "ready" or not isinstance(registro.get("resultado"), dict):
        return ""
    r = registro["resultado"]
    linhas = ["=== ANÁLISE DOCUMENTAL (skill documental — cada item aponta o documento de origem) ==="]
    diag = r.get("diagnostico") if isinstance(r.get("diagnostico"), dict) else {}
    if diag.get("sentido"):
        linhas.append(f"Diagnóstico do caso: {diag['sentido']} — {diag.get('motivo') or ''}")
    resumo = r.get("resumo_do_caso") or {}
    if resumo.get("questao_central"):
        linhas.append(f"Questão central: {resumo['questao_central']}")
    if resumo.get("objetivo_do_cliente"):
        linhas.append(f"Objetivo do cliente: {resumo['objetivo_do_cliente']}")
    fatos = [f for f in r.get("fatos_extraidos") or [] if f.get("estado") != "REJECTED"]
    if fatos:
        linhas.append("\nFatos extraídos (id | fato | documento | trecho):")
        for f in fatos:
            p = f.get("proveniencia") or {}
            pg = f", p. {p['pagina']}" if p.get("pagina") else ""
            marca = " [CONFIRMADO PELO ADVOGADO]" if f.get("estado") == "CONFIRMED" else ""
            linhas.append(f"- {f['id']} | {f['fato']}{marca} | {p['tipo_documento']} — {p['arquivo']}{pg} | \"{p['citacao'][:200]}\"")
    inc = [i for i in r.get("inconsistencias") or [] if i.get("estado") != "REJECTED"]
    if inc:
        linhas.append("\nInconsistências entre documentos (NÃO afirme como fato o dado divergente; trate conforme a skill da peça):")
        for i in inc:
            fontes = " × ".join(
                f"{s.get('arquivo') or s.get('documento_id')}: \"{(s.get('valor') or s.get('citacao') or '')[:100]}\""
                for s in (i.get("fontes") or []) if isinstance(s, dict)
            )
            linhas.append(f"- {i['id']} | {i['titulo']} | {fontes} | impacto: {i['impacto']}")
    provas = r.get("provas") or []
    if provas:
        linhas.append("\nProvas por fato (fato | status | documentos):")
        nomes = {d["documento_id"]: d["arquivo"] for d in r.get("documentos") or []}
        for p in provas:
            linhas.append(f"- {p['fato']} | {p['status']} | {', '.join(nomes.get(x, x) for x in (p.get('documento_ids') or []))}")
    faltantes = [f for f in r.get("documentos_faltantes") or [] if f.get("estado") != "REJECTED"]
    if faltantes:
        linhas.append("\nDocumentos faltantes (documento | hipótese | classificação):")
        linhas.extend(f"- {f['documento']} | {f['hipotese']} | {f['classificacao']}" for f in faltantes)
    respondidas = [p for p in r.get("perguntas") or [] if p.get("resposta")]
    if respondidas:
        linhas.append("\nRESPOSTAS DO ESCRITÓRIO a dúvidas dos documentos (informadas pelo advogado, não extraídas de documento):")
        linhas.extend(f"- {p['pergunta']} → {p['resposta']}" for p in respondidas)
    abertas = [p for p in r.get("perguntas") or [] if not p.get("resposta")]
    if abertas:
        linhas.append("\nDúvidas AINDA SEM RESPOSTA (não presuma; use [PENDENTE] se essenciais):")
        linhas.extend(f"- {p['pergunta']}" for p in abertas)
    skill = r.get("skill") or {}
    linhas.append(f"\n(análise produzida pela skill {skill.get('skill_name')} sha256={str(skill.get('skill_sha256'))[:12]})")
    return "\n".join(linhas)
