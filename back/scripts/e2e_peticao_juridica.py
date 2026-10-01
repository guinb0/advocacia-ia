"""E2E da camada jurídica num caso real — sem gravar nada em produção.

Três passos, em processos separados de propósito:

  exportar   COM `SQLSERVER_*` no ambiente. Chama as funções de leitura do `armazenamento` com a conexão
             travada: só SELECT/WITH passa, a transação é sempre desfeita e a conexão abre com
             `ApplicationIntent=ReadOnly`. Grava um snapshot JSON local — fora do repositório, porque tem
             dado pessoal do cliente.
  gerar      SEM credencial de banco: o processo apaga `SQLSERVER_*`, `DATABASE_URL`, `PGVECTOR_*`, não lê
             `.env` e derruba `pyodbc.connect`/`psycopg.connect`. O `armazenamento` passa a ler do snapshot e
             toda escrita vira registro em memória. Roda `peticao_local.gerar` em cada modo pedido
             (`PETICAO_PIPELINE_JURIDICO_MODE`). Exige a chave do modelo (`DEEPSEEK_API_KEY`) no ambiente.
  relatorio  Audita, com as etapas determinísticas da camada, a última peça gravada em produção e junta as
             gerações num relatório markdown.

Uso (de `back/`):

    python -m scripts.e2e_peticao_juridica exportar <caso_id> --saida <pasta>
    python -m scripts.e2e_peticao_juridica gerar --saida <pasta> --modos off,strict [--autoridades base.json]
    python -m scripts.e2e_peticao_juridica relatorio --saida <pasta> [--referencia peca.txt]

`--autoridades`: linhas no formato da tabela `autoridades_juridicas` (sql/010), para homologar a base antes
de aplicá-la. Sem o arquivo, a base é a do ambiente — e, offline, ela está indisponível.
"""

from __future__ import annotations

import argparse
import base64
import copy
import difflib
import json
import os
import re
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

LEITURAS_DO_CASO = (
    "obter_caso", "obter_qualificacao", "listar_entregas", "listar_extracoes_do_caso", "listar_entrevistas",
    "obter_peticao_local", "listar_versoes_peticao", "listar_peticoes_anexas", "ultima_solicitacao_peticao",
)
#: Catálogos do escritório lidos direto do SQL Server (fora do `armazenamento`), com cache em memória.
CATALOGOS_EM_CACHE = ("tipos_caso._catalogo_em_cache", "tipos_documento._marcacoes_em_cache", "tipos_documento._todos_em_cache")
VARIAVEIS_DE_BANCO = re.compile(r"^(SQLSERVER_|PGVECTOR_|DATABASE_URL$|JOBS_DATABASE_URL$|JURISPRUDENCE_DATABASE_URL$|REDIS_URL$)")
_SO_LEITURA = re.compile(r"^\s*(select|with)\b", re.I)
_ESCRITA = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|grant|revoke|into)\b", re.I)


# ── serialização ────────────────────────────────────────────────────────────────────────────────────

def _para_json(valor: Any) -> Any:
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(valor)).decode("ascii")}
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, set):
        return sorted(valor, key=str)
    return str(valor)


def _de_json(obj: dict[str, Any]) -> Any:
    if set(obj) == {"__b64__"}:
        return base64.b64decode(obj["__b64__"])
    return obj


def _chave(nome: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return f"{nome}|{json.dumps([list(args), kwargs], default=str, sort_keys=True, ensure_ascii=False)}"


def _gravar(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, default=_para_json, ensure_ascii=False, indent=1), encoding="utf-8")


def _ler(caminho: Path) -> Any:
    return json.loads(caminho.read_text(encoding="utf-8"), object_hook=_de_json)


# ── exportar (somente leitura) ──────────────────────────────────────────────────────────────────────

def _exigir_select(sql: str) -> None:
    if not _SO_LEITURA.match(sql) or _ESCRITA.search(sql) or ";" in sql.strip().rstrip(";"):
        raise PermissionError(f"E2E: só SELECT é permitido na exportação; recusado: {sql.strip()[:120]!r}")


def _travar_somente_leitura() -> None:
    import pyodbc

    from app import armazenamento, banco

    if "SQLSERVER_DRIVER" not in os.environ:
        instalados = [d for d in pyodbc.drivers() if "SQL Server" in d]
        if instalados:
            os.environ["SQLSERVER_DRIVER"] = sorted(instalados)[-1]

    class SoLeitura(banco.Conexao):
        def execute(self, sql: str, params: Any = ()) -> Any:  # type: ignore[override]
            _exigir_select(sql)
            return super().execute(sql, params)

        def executemany(self, sql: str, seq: Any) -> None:  # type: ignore[override]
            raise PermissionError("E2E: executemany é escrita; recusado na exportação.")

        def commit(self) -> None:
            self._bruta.rollback()

    @contextmanager
    def conectar(timeout: int = 15) -> Iterator[Any]:
        bruta = pyodbc.connect(banco.dsn() + "ApplicationIntent=ReadOnly;", timeout=max(1, timeout), autocommit=False)
        try:
            yield SoLeitura(bruta)
        finally:
            try:
                bruta.rollback()
            finally:
                bruta.close()

    @contextmanager
    def sessao() -> Iterator[Any]:
        with conectar() as con:
            yield con

    original = banco.conectar
    for nome, modulo in list(sys.modules.items()):
        if (nome == "app" or nome.startswith("app.")) and getattr(modulo, "conectar", None) is original:
            modulo.conectar = conectar  # type: ignore[attr-defined]
    banco.sessao = sessao  # type: ignore[assignment]
    assert armazenamento.conectar is conectar


def exportar(caso_id: str, saida: Path) -> Path:
    from app import armazenamento, peticao_local, tipos_caso, tipos_documento  # noqa: F401 — carregados antes da trava

    _travar_somente_leitura()

    leituras: dict[str, Any] = {}
    erros: dict[str, str] = {}
    chamadas: list[tuple[str, tuple[Any, ...]]] = [(nome, (caso_id,)) for nome in LEITURAS_DO_CASO]
    chamadas += [("obter_modelo", (codigo,)) for codigo in
                 (peticao_local.MODELO_VISUAL_GERAL, peticao_local.MODELO_VISUAL_LOGO, peticao_local.MODELO_VISUAL_CONFIG)]
    for nome, args in chamadas:
        try:
            leituras[_chave(nome, args, {})] = getattr(armazenamento, nome)(*args)
        except Exception as erro:  # noqa: BLE001
            erros[nome] = f"{type(erro).__name__}: {str(erro)[:200]}"
    import importlib

    for alvo in CATALOGOS_EM_CACHE:
        modulo, funcao = alvo.split(".")
        try:
            leituras[alvo] = getattr(importlib.import_module(f"app.{modulo}"), funcao)()
        except Exception as erro:  # noqa: BLE001
            erros[alvo] = f"{type(erro).__name__}: {str(erro)[:200]}"
    if not leituras.get(_chave("obter_caso", (caso_id,), {})):
        raise SystemExit(f"Caso {caso_id} não encontrado (erros: {erros}).")
    destino = saida / "snapshot.json"
    _gravar(destino, {"caso_id": caso_id, "exportado_em": datetime.now().isoformat(timespec="seconds"),
                      "leituras": leituras, "erros": erros})
    return destino


# ── gerar (offline) ─────────────────────────────────────────────────────────────────────────────────

class Armazenamento:
    """Substitui o módulo `armazenamento`: leituras do snapshot, escritas só em memória."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.leituras = snapshot["leituras"]
        self.escritas: list[dict[str, Any]] = []
        self.leituras_sem_snapshot: list[str] = []
        self.peticao_salva: dict[str, Any] | None = None

    def funcao(self, nome: str) -> Callable[..., Any]:
        def chamar(*args: Any, **kwargs: Any) -> Any:
            chave = _chave(nome, args, kwargs)
            if chave in self.leituras:
                return copy.deepcopy(self.leituras[chave])
            if nome == "salvar_peticao_local":
                self.peticao_salva = {"dados": args[1] if len(args) > 1 else kwargs.get("dados"),
                                      "docx": args[2] if len(args) > 2 else kwargs.get("docx")}
            if nome.startswith(("obter_", "listar_", "ultima_", "caminho_", "conteudo_", "contar_", "buscar_")):
                self.leituras_sem_snapshot.append(chave[:200])
                return [] if nome.startswith("listar_") else None
            self.escritas.append({"funcao": nome, "args": repr(args)[:160]})
            return None
        return chamar


def _isolar_do_banco() -> None:
    for nome in [n for n in os.environ if VARIAVEIS_DE_BANCO.match(n)]:
        del os.environ[nome]
    from app import ambiente

    ambiente.carregar = lambda *a, **k: None  # type: ignore[assignment]

    def recusar(*_a: Any, **_k: Any) -> Any:
        raise ConnectionRefusedError("E2E offline: conexão com banco bloqueada")

    import pyodbc
    pyodbc.connect = recusar  # type: ignore[assignment]
    try:
        import psycopg
        psycopg.connect = recusar  # type: ignore[assignment]
    except ImportError:
        pass


def _substituir_armazenamento(falso: Armazenamento) -> None:
    import inspect

    from app import armazenamento, banco

    import importlib

    banco._carregar_env = lambda *a, **k: None  # type: ignore[assignment]  # noqa: SLF001
    for alvo in CATALOGOS_EM_CACHE:
        modulo, funcao = alvo.split(".")
        valor = falso.leituras.get(alvo)
        valor = tuple(valor) if isinstance(valor, list) else (valor if valor is not None else ())
        setattr(importlib.import_module(f"app.{modulo}"), funcao, lambda v=valor: copy.deepcopy(v))
    for nome, obj in list(vars(armazenamento).items()):
        if nome.startswith("_") or not inspect.isfunction(obj) or obj.__module__ != armazenamento.__name__:
            continue
        setattr(armazenamento, nome, falso.funcao(nome))


class _ResultadoVazio:
    rowcount = 0

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _ConexaoQueSoRegistra:
    """Quem fala com o SQL Server direto (custos, auditoria) cai aqui: nada sai do processo."""

    def __init__(self, registro: list[str]) -> None:
        self.registro = registro

    def execute(self, sql: str, params: Any = ()) -> _ResultadoVazio:
        self.registro.append(" ".join(sql.split())[:140])
        return _ResultadoVazio()

    def executemany(self, sql: str, seq: Any) -> None:
        self.registro.append(" ".join(sql.split())[:140])

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def _desviar_conexoes_sql_server(registro: list[str]) -> None:
    from app import banco

    original = banco.conectar

    @contextmanager
    def conectar(timeout: int = 15) -> Iterator[Any]:
        yield _ConexaoQueSoRegistra(registro)

    for nome, modulo in list(sys.modules.items()):
        if (nome == "app" or nome.startswith("app.")) and getattr(modulo, "conectar", None) is original:
            modulo.conectar = conectar  # type: ignore[attr-defined]
    banco.sessao = conectar  # type: ignore[assignment]


def _carregar_autoridades(arquivo: Path) -> None:
    from app.juridico import autoridades as aut, repositorio

    linhas = json.loads(arquivo.read_text(encoding="utf-8"))
    base = aut.de_registro_bruto(linhas)
    repositorio.carregar_autoridades = lambda organization_id="": (list(base), "")  # type: ignore[assignment]
    repositorio.carregar_dispositivos = lambda chaves: ([], "")  # type: ignore[assignment]


def gerar(saida: Path, modo: str, autoridades: Path | None) -> Path:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Defina DEEPSEEK_API_KEY no ambiente deste processo (não grave em arquivo).")
    _isolar_do_banco()
    snapshot = _ler(saida / "snapshot.json")
    falso = Armazenamento(snapshot)
    _substituir_armazenamento(falso)
    if autoridades:
        _carregar_autoridades(autoridades)
    os.environ["PETICAO_PIPELINE_JURIDICO_MODE"] = modo
    os.environ.pop("PETICAO_PIPELINE_JURIDICO", None)

    from app import peticao_local
    from app.agente import peticao_fluxo

    sql_interceptado: list[str] = []
    _desviar_conexoes_sql_server(sql_interceptado)
    caso_id = snapshot["caso_id"]
    inicio = time.monotonic()
    resultado: dict[str, Any] = {"modo": modo, "caso_id": caso_id, "autoridades_arquivo": str(autoridades or "")}
    try:
        entrevista = peticao_fluxo.transcricao(caso_id)
        dados = peticao_local.gerar(caso_id, texto_entrevista=entrevista["texto"])
        resultado["dados"] = {k: v for k, v in dados.items() if k != "_docx"}
    except Exception as erro:  # noqa: BLE001
        resultado["erro"] = f"{type(erro).__name__}: {erro}"
        resultado["traceback"] = traceback.format_exc()[-4000:]
    resultado["duracao_s"] = round(time.monotonic() - inicio, 1)
    resultado["escritas_interceptadas"] = falso.escritas
    resultado["sql_interceptado"] = sql_interceptado
    resultado["leituras_sem_snapshot"] = sorted(set(falso.leituras_sem_snapshot))
    if falso.peticao_salva and falso.peticao_salva.get("docx"):
        (saida / f"minuta_{modo}.docx").write_bytes(falso.peticao_salva["docx"])
    destino = saida / f"geracao_{modo}.json"
    _gravar(destino, resultado)
    return destino


# ── relatório ───────────────────────────────────────────────────────────────────────────────────────

def _secoes(dados: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (dados.get("sections") or dados.get("secoes") or []) if isinstance(s, dict)]


def _texto(secoes: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"## {s.get('label') or s.get('title') or s.get('code') or ''}\n{s.get('content') or ''}" for s in secoes)


def _pipeline(dados: dict[str, Any]) -> dict[str, Any]:
    return ((dados.get("trace") or {}).get("pipeline")) or dados.get("pipeline") or {}


def _fontes_do_snapshot(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    caso_id = snapshot["caso_id"]
    leituras = snapshot["leituras"]
    fontes = []
    for e in leituras.get(_chave("listar_extracoes_do_caso", (caso_id,), {})) or []:
        texto = str((e.get("extracao") or {}).get("texto_completo") or "")
        if texto.strip():
            fontes.append({"tipo": "documento", "nome": e.get("arquivo") or e.get("id"), "texto": texto})
    entrevistas = [x for x in leituras.get(_chave("listar_entrevistas", (caso_id,), {})) or [] if (x.get("texto") or "").strip()]
    entrevista = str(max(entrevistas, key=lambda x: x.get("criado_em") or "")["texto"]) if entrevistas else ""
    if entrevista:
        fontes.append({"tipo": "entrevista", "nome": "entrevista", "texto": entrevista})
    return fontes, entrevista


def auditar_peca_gravada(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Etapas determinísticas da camada (sem modelo, sem banco) sobre a peça que está em produção."""
    from app import documento_final, peticao_skill_arquivos
    from app.juridico import auditores, autoridades as aut, fatos, teses

    caso_id = snapshot["caso_id"]
    dados = snapshot["leituras"].get(_chave("obter_peticao_local", (caso_id,), {})) or {}
    secoes = _secoes(dados)
    pipeline = _pipeline(dados)
    plano_est = pipeline.get("plano_estruturado") or pipeline.get("petition_plan") or {}
    fontes, _ = _fontes_do_snapshot(snapshot)
    matriz = fatos.montar(plano_est, case_facts=plano_est.get("case_facts"), fontes=fontes)
    catalogo = teses.catalogo_da_skill(teses.textos_da_skill_ativa())
    registro = aut.Registro([], alertas=["base de autoridades indisponível offline"])
    legal = auditores.auditar_legal(secoes, registro, date.today())
    texto_fontes = "\n".join(f["texto"] for f in fontes)
    fato = auditores.auditar_fatos(secoes, matriz, calculos=[], texto_das_fontes=texto_fontes)
    conta = auditores.auditar_calculos(secoes, plano_est.get("pedidos") or [], [])
    params = peticao_skill_arquivos.validacoes_da_skill()["parametros"]
    ausentes = documento_final.pedidos_obrigatorios_ausentes(secoes, params)
    cobertura = [{"item": f"{k['id']} {k['tema']}", "arquivo": k.get("arquivo")} for k in catalogo]
    return {"secoes": len(secoes), "readiness": dados.get("readiness"), "modelo": (dados.get("trace") or {}).get("modelo") or dados.get("modelo"),
            "atualizado_em": dados.get("updated_at"), "matriz": matriz, "catalogo": cobertura,
            "auditor_legal": legal, "auditor_fatos": fato, "auditor_calculos": conta, "pedidos_obrigatorios_ausentes": ausentes,
            "texto": _texto(secoes)}


def _md_achados(achados: list[dict[str, Any]], limite: int = 30) -> list[str]:
    from collections import Counter

    contagem = Counter((a.get("severidade"), a.get("codigo"), (a.get("trecho") or a.get("detalhe") or "")[:180]) for a in achados)
    linhas = [f"- **{sev}** `{cod}` — {trecho}" + (f" (×{n})" if n > 1 else "") for (sev, cod, trecho), n in list(contagem.items())[:limite]]
    if len(contagem) > limite:
        linhas.append(f"- … mais {len(contagem) - limite} distintos")
    return linhas or ["- nenhum achado"]


def _md_geracao(g: dict[str, Any], saida: Path) -> list[str]:
    modo = g["modo"]
    out = [f"## Geração offline — modo `{modo}`", "", f"- duração: {g.get('duracao_s')} s"]
    if g.get("erro"):
        return out + [f"- **ERRO**: `{g['erro']}`", "", "```", g.get("traceback", "")[-1500:], "```", ""]
    dados = g["dados"]
    secoes = _secoes(dados)
    (saida / f"minuta_{modo}.md").write_text(_texto(secoes), encoding="utf-8")
    pipeline = _pipeline(dados)
    jur = pipeline.get("juridico") or {}
    out += [f"- seções: {len(secoes)} — minuta: `minuta_{modo}.md`", f"- readiness: `{json.dumps(dados.get('readiness'), ensure_ascii=False)[:400]}`",
            f"- escritas interceptadas (nada foi gravado): {len(g.get('escritas_interceptadas') or [])}",
            f"- leituras fora do snapshot (devolveram vazio): {g.get('leituras_sem_snapshot') or 'nenhuma'}",
            f"- fallbacks do diagnóstico: {(pipeline.get('diagnostico') or {}).get('fallbacks') or pipeline.get('fallbacks') or '—'}", ""]
    if not jur:
        return out + ["Camada jurídica: não executada neste modo.", ""]
    out += [f"### Camada jurídica (`{jur.get('modo')}`)", "", f"- falhas: {jur.get('falhas') or 'nenhuma'}", ""]
    out += ["#### Fatos extraídos", ""]
    for f in (jur.get("fatos") or [])[:80]:
        out.append(f"- `{f.get('id')}` [{f.get('estado') or f.get('status')}] {f.get('chave') or ''} {('= ' + str(f.get('valor'))) if f.get('valor') not in (None, '') else ''} {f.get('fato') or ''}"[:220])
    out += ["", "#### Catálogo de teses avaliado", ""]
    for t in jur.get("teses") or []:
        out.append(f"- **{t.get('decisao')}** — {t.get('tese')} · motivo: {(t.get('motivo') or '')[:200]}")
        for fd in (t.get("fatos_detalhados") or [])[:6]:
            out.append(f"  - fato `{fd.get('id')}` [{fd.get('estado')}] {str(fd.get('texto') or fd.get('fato') or '')[:140]}")
    if jur.get("nao_avaliadas"):
        out.append(f"- não avaliadas pelo modelo: {jur['nao_avaliadas']}")
    out += ["", "#### Autoridades recuperadas", ""]
    por_tese = jur.get("autoridades_por_tese") or {}
    out += [f"- {tese}: {[a.get('titulo') or a.get('id') if isinstance(a, dict) else a for a in lista]}" for tese, lista in por_tese.items()] or ["- nenhuma (base vazia ou indisponível)"]
    out += ["", "#### Plano final", "", f"- valor da causa calculado: {jur.get('valor_da_causa')}", f"- pendências: {jur.get('pendencias')}",
            f"- tabelas: {jur.get('tabelas')}", "", "#### Os quatro auditores", ""]
    aud = jur.get("auditoria") or {}
    out.append(f"- veredito: `{json.dumps(aud.get('veredito'), ensure_ascii=False)[:500]}`")
    out += _md_achados(aud.get("achados") or [], 40)
    if jur.get("comparacao_com_legado"):
        out += ["", "#### Comparação com o legado (shadow)", "", "```json", json.dumps(jur["comparacao_com_legado"], ensure_ascii=False, indent=1)[:4000], "```"]
    return out + [""]


def _md_diferencas(nome_a: str, texto_a: str, nome_b: str, texto_b: str) -> list[str]:
    from app.juridico import autoridades as aut

    cit_a = {c.trecho for c in aut.extrair_citacoes(texto_a)}
    cit_b = {c.trecho for c in aut.extrair_citacoes(texto_b)}
    tit = lambda t: [l[3:].strip() for l in t.splitlines() if l.startswith("## ")]  # noqa: E731
    sm = difflib.SequenceMatcher(None, texto_a, texto_b, autojunk=False)
    return [f"## Diferenças: {nome_a} × {nome_b}", "",
            f"- tamanho: {len(texto_a)} × {len(texto_b)} caracteres · similaridade {sm.quick_ratio():.0%}",
            f"- seções só em {nome_a}: {sorted(set(tit(texto_a)) - set(tit(texto_b)))}",
            f"- seções só em {nome_b}: {sorted(set(tit(texto_b)) - set(tit(texto_a)))}",
            f"- citações só em {nome_a}: {sorted(cit_a - cit_b)[:40]}",
            f"- citações só em {nome_b}: {sorted(cit_b - cit_a)[:40]}", ""]


def relatorio(saida: Path, referencia: Path | None) -> Path:
    _isolar_do_banco()
    snapshot = _ler(saida / "snapshot.json")
    caso = snapshot["leituras"].get(_chave("obter_caso", (snapshot["caso_id"],), {})) or {}
    fontes, entrevista = _fontes_do_snapshot(snapshot)
    gravada = auditar_peca_gravada(snapshot)
    out = [f"# E2E camada jurídica — caso `{snapshot['caso_id']}`", "",
           f"- categoria: {caso.get('categoria')} · snapshot de {snapshot['exportado_em']} (somente leitura)",
           f"- fontes: {sum(f['tipo'] == 'documento' for f in fontes)} documentos com OCR · entrevista {len(entrevista)} caracteres",
           f"- erros de leitura na exportação: {snapshot.get('erros') or 'nenhum'}", "",
           "## Peça gravada em produção (fluxo legado) — auditoria determinística", "",
           f"- seções: {gravada['secoes']} · modelo: {gravada['modelo']} · atualizada em {gravada['atualizado_em']}",
           f"- readiness gravado: `{json.dumps(gravada['readiness'], ensure_ascii=False)[:300]}`",
           f"- matriz de fatos (sem o modelo): {gravada['matriz'].get('resumo')}",
           f"- pedidos obrigatórios da skill ausentes: {gravada['pedidos_obrigatorios_ausentes'] or 'nenhum'}", "",
           "### Matriz de fatos do plano gravado × fontes (sem o modelo)", ""]
    for f in gravada["matriz"]["fatos"]:
        valor = f" = {f['valor']}" if f.get("valor") else ""
        out.append(f"- `{f['id']}` [{f['estado']}] {f.get('chave') or ''}{valor} {'' if f.get('chave') else f['fato'][:150]}"
                   f" · fonte: {(f.get('documento') or f.get('fonte') or '—')[:80]}" + (f" · CONTRADIÇÃO {f['contradicoes']}" if f.get("contradicoes") else ""))
    out += ["", f"### Auditor legal — {len(gravada['auditor_legal'].get('citacoes') or [])} citações (base de autoridades indisponível offline)", ""]
    out += _md_achados(gravada["auditor_legal"].get("achados") or [])
    out += ["", "### Auditor de fatos", ""] + _md_achados(gravada["auditor_fatos"].get("achados") or [])
    out += ["", "### Auditor de cálculos", ""] + _md_achados(gravada["auditor_calculos"].get("achados") or [])
    out += ["", f"### Catálogo da skill: {len(gravada['catalogo'])} itens — avaliados só pelo issue spotting (modo strict/shadow), "
            "não por comparação de palavras", ""]
    (saida / "minuta_producao.md").write_text(gravada["texto"], encoding="utf-8")
    textos = {"producao": gravada["texto"]}
    for arq in sorted(saida.glob("geracao_*.json")):
        g = _ler(arq)
        out += [""] + _md_geracao(g, saida)
        if not g.get("erro"):
            textos[g["modo"]] = _texto(_secoes(g["dados"]))
    if referencia and referencia.exists():
        textos["referencia"] = referencia.read_text(encoding="utf-8", errors="replace")
    nomes = list(textos)
    for i, a in enumerate(nomes):
        for b in nomes[i + 1:]:
            out += _md_diferencas(a, textos[a], b, textos[b])
    destino = saida / "relatorio.md"
    destino.write_text("\n".join(out), encoding="utf-8")
    return destino


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar")
    e.add_argument("caso_id")
    e.add_argument("--saida", type=Path, required=True)
    g = sub.add_parser("gerar")
    g.add_argument("--saida", type=Path, required=True)
    g.add_argument("--modos", default="off,strict")
    g.add_argument("--autoridades", type=Path)
    r = sub.add_parser("relatorio")
    r.add_argument("--saida", type=Path, required=True)
    r.add_argument("--referencia", type=Path)
    a = p.parse_args()
    if a.saida.resolve().is_relative_to(RAIZ.parent.resolve()):
        raise SystemExit("--saida tem de ficar fora do repositório (o snapshot tem dado pessoal do cliente).")
    if a.cmd == "exportar":
        print(exportar(a.caso_id, a.saida))
    elif a.cmd == "gerar":
        for modo in [m.strip() for m in a.modos.split(",") if m.strip()]:
            # Um processo por modo: os módulos guardam estado (skill, caches) e o modo é lido do ambiente.
            if len(a.modos.split(",")) > 1:
                import subprocess
                cmd = [sys.executable, "-m", "scripts.e2e_peticao_juridica", "gerar", "--saida", str(a.saida), "--modos", modo]
                if a.autoridades:
                    cmd += ["--autoridades", str(a.autoridades)]
                subprocess.run(cmd, cwd=RAIZ, check=False)
            else:
                print(gerar(a.saida, modo, a.autoridades))
    else:
        print(relatorio(a.saida, a.referencia))


if __name__ == "__main__":
    main()
