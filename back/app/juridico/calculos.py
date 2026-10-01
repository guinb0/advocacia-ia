"""Cálculos trabalhistas determinísticos. O modelo informa PARÂMETROS do caso; a conta é do código.

Cada cálculo devolve valor, memória (linha a linha), parâmetros do caso e os parâmetros legais usados.
Parâmetro legal (percentual, divisor, dias de aviso) tem valor padrão marcado `origem="padrao"` e
`pesquisar=...`: o PETITION_PLAN exige que a base jurídica sustente cada um, e norma coletiva mais
benéfica entra por `parametros_legais` com `origem="informado"`.

O valor da causa é a SOMA dos pedidos cumulativos com valor — nunca reescrito a partir do texto.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from .autoridades import _data

#: Parâmetros legais padrão. São DADOS (sobrescrevíveis), cada um com o que a pesquisa jurídica deve confirmar.
PARAMETROS_LEGAIS_PADRAO: dict[str, dict[str, Any]] = {
    "divisor_mensal": {"valor": 220, "pesquisar": "divisor de horas para jornada de 44h semanais"},
    "adicional_hora_extra": {"valor": 0.50, "pesquisar": "adicional mínimo da hora extraordinária"},
    "adicional_noturno": {"valor": 0.20, "pesquisar": "adicional noturno urbano"},
    "minutos_hora_noturna": {"valor": 52.5, "pesquisar": "hora noturna reduzida"},
    "adicional_intervalo": {"valor": 0.50, "pesquisar": "natureza e adicional do intervalo intrajornada suprimido"},
    "aliquota_fgts": {"valor": 0.08, "pesquisar": "alíquota do depósito do FGTS"},
    "multa_fgts": {"valor": 0.40, "pesquisar": "indenização compensatória do FGTS na dispensa sem justa causa"},
    "fracao_ferias": {"valor": 1 / 3, "pesquisar": "terço constitucional de férias"},
    "aviso_dias_base": {"valor": 30, "pesquisar": "aviso prévio proporcional ao tempo de serviço"},
    "aviso_dias_por_ano": {"valor": 3, "pesquisar": "aviso prévio proporcional ao tempo de serviço"},
    "aviso_dias_maximo": {"valor": 90, "pesquisar": "aviso prévio proporcional ao tempo de serviço"},
    "dias_para_avo": {"valor": 15, "pesquisar": "fração igual ou superior a 15 dias para avos de 13º e férias"},
}


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def _r(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def brl(x: Any) -> str:
    v = _r(_d(x))
    inteiro, cent = f"{v:.2f}".split(".")
    return f"R$ {int(inteiro):,}".replace(",", ".") + f",{cent}"


@dataclass
class Calculo:
    rubrica: str
    valor: float
    memoria: list[str]
    parametros: dict[str, Any]
    parametros_legais: dict[str, dict[str, Any]] = field(default_factory=dict)
    pedido_id: str = ""
    tese_id: str = ""
    erro: str = ""

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


class Parametros:
    def __init__(self, legais: dict[str, Any] | None = None):
        self.informados = {k: v for k, v in (legais or {}).items() if v not in (None, "")}
        self.usados: dict[str, dict[str, Any]] = {}

    def __call__(self, nome: str) -> Decimal:
        if nome in self.informados:
            self.usados[nome] = {"valor": self.informados[nome], "origem": "informado"}
            return _d(self.informados[nome])
        p = PARAMETROS_LEGAIS_PADRAO[nome]
        self.usados[nome] = {"valor": p["valor"], "origem": "padrao", "pesquisar": p["pesquisar"]}
        return _d(p["valor"])


def avos_entre(inicio: Any, fim: Any, dias_para_avo: int = 15) -> int:
    """Meses (avos) entre duas datas; a fração final com `dias_para_avo` ou mais conta como mês."""
    a, b = _data(inicio), _data(fim)
    if not a or not b or b < a:
        return 0
    meses = (b.year - a.year) * 12 + (b.month - a.month)
    dias = b.day - a.day + 1
    if dias < 0:
        meses -= 1
        dias += 30
    return meses + (1 if dias >= dias_para_avo else 0)


def anos_completos(inicio: Any, fim: Any) -> int:
    a, b = _data(inicio), _data(fim)
    if not a or not b or b < a:
        return 0
    return b.year - a.year - ((b.month, b.day) < (a.month, a.day))


# ------------------------------------------------------------------ calculadoras

def saldo_salario(p: Parametros, *, salario: Any, dias: Any) -> tuple[Decimal, list[str]]:
    v = _d(salario) / 30 * _d(dias)
    return v, [f"{brl(salario)} ÷ 30 × {dias} dias = {brl(v)}"]


def aviso_previo(p: Parametros, *, salario: Any, anos: Any = None, admissao: Any = None, dispensa: Any = None) -> tuple[Decimal, list[str]]:
    n = int(anos) if anos not in (None, "") else anos_completos(admissao, dispensa)
    dias = min(p("aviso_dias_base") + p("aviso_dias_por_ano") * n, p("aviso_dias_maximo"))
    v = _d(salario) / 30 * dias
    return v, [f"{n} ano(s) completo(s) → {dias} dias", f"{brl(salario)} ÷ 30 × {dias} = {brl(v)}"]


def decimo_terceiro(p: Parametros, *, salario: Any, avos: Any = None, inicio: Any = None, fim: Any = None) -> tuple[Decimal, list[str]]:
    n = int(avos) if avos not in (None, "") else avos_entre(inicio, fim, int(p("dias_para_avo")))
    v = _d(salario) / 12 * n
    return v, [f"{brl(salario)} ÷ 12 × {n}/12 = {brl(v)}"]


def ferias(p: Parametros, *, salario: Any, avos: Any = 0, periodos_vencidos: Any = 0, em_dobro: Any = 0) -> tuple[Decimal, list[str]]:
    terco = p("fracao_ferias")
    prop = _d(salario) / 12 * _d(avos or 0)
    venc = _d(salario) * _d(periodos_vencidos or 0)
    dobro = _d(salario) * _d(em_dobro or 0)
    v = (prop + venc + dobro * 2) * (1 + terco)
    mem = []
    if avos:
        mem.append(f"proporcionais: {brl(salario)} ÷ 12 × {avos} = {brl(prop)}")
    if periodos_vencidos:
        mem.append(f"vencidas simples: {brl(salario)} × {periodos_vencidos} = {brl(venc)}")
    if em_dobro:
        mem.append(f"vencidas em dobro: {brl(salario)} × {em_dobro} × 2 = {brl(dobro * 2)}")
    mem.append(f"+ 1/3 → {brl(v)}")
    return v, mem


def valor_hora(p: Parametros, salario: Any, divisor: Any = None) -> Decimal:
    return _d(salario) / (_d(divisor) if divisor not in (None, "") else p("divisor_mensal"))


def horas_extras(p: Parametros, *, salario: Any, horas_mensais: Any, meses: Any, divisor: Any = None, adicional: Any = None) -> tuple[Decimal, list[str]]:
    vh = valor_hora(p, salario, divisor)
    ad = _d(adicional) if adicional not in (None, "") else p("adicional_hora_extra")
    v = vh * (1 + ad) * _d(horas_mensais) * _d(meses)
    return v, [f"valor-hora {brl(vh)} × (1 + {ad}) × {horas_mensais} h/mês × {meses} meses = {brl(v)}"]


def dsr_reflexo(p: Parametros, *, valor_variavel_total: Any, dias_uteis: Any, dias_descanso: Any) -> tuple[Decimal, list[str]]:
    v = _d(valor_variavel_total) / _d(dias_uteis) * _d(dias_descanso)
    return v, [f"{brl(valor_variavel_total)} ÷ {dias_uteis} dias úteis × {dias_descanso} descansos = {brl(v)}"]


def adicional_noturno(p: Parametros, *, salario: Any, horas_noturnas_mensais: Any, meses: Any, divisor: Any = None, adicional: Any = None, hora_reduzida: Any = True) -> tuple[Decimal, list[str]]:
    vh = valor_hora(p, salario, divisor)
    ad = _d(adicional) if adicional not in (None, "") else p("adicional_noturno")
    horas = _d(horas_noturnas_mensais) * (Decimal(60) / p("minutos_hora_noturna") if hora_reduzida else 1)
    v = vh * ad * horas * _d(meses)
    return v, [f"{horas_noturnas_mensais} h relógio → {_r(horas)} h noturnas", f"valor-hora {brl(vh)} × {ad} × {_r(horas)} h × {meses} meses = {brl(v)}"]


def intervalo_intrajornada(p: Parametros, *, salario: Any, minutos_suprimidos_dia: Any, dias_por_mes: Any, meses: Any, divisor: Any = None, adicional: Any = None) -> tuple[Decimal, list[str]]:
    vh = valor_hora(p, salario, divisor)
    ad = _d(adicional) if adicional not in (None, "") else p("adicional_intervalo")
    horas = _d(minutos_suprimidos_dia) / 60 * _d(dias_por_mes) * _d(meses)
    v = vh * (1 + ad) * horas
    return v, [f"{minutos_suprimidos_dia} min/dia × {dias_por_mes} dias × {meses} meses = {_r(horas)} h", f"valor-hora {brl(vh)} × (1 + {ad}) × {_r(horas)} h = {brl(v)}"]


def fgts(p: Parametros, *, base_mensal: Any, meses: Any, ja_depositado: Any = 0) -> tuple[Decimal, list[str]]:
    devido = _d(base_mensal) * p("aliquota_fgts") * _d(meses)
    v = max(devido - _d(ja_depositado or 0), Decimal(0))
    return v, [f"{brl(base_mensal)} × {p('aliquota_fgts')} × {meses} meses = {brl(devido)}", f"− depositado {brl(ja_depositado or 0)} = {brl(v)}"]


def multa_fgts(p: Parametros, *, saldo_fgts: Any, percentual: Any = None) -> tuple[Decimal, list[str]]:
    pc = _d(percentual) if percentual not in (None, "") else p("multa_fgts")
    v = _d(saldo_fgts) * pc
    return v, [f"{brl(saldo_fgts)} × {pc} = {brl(v)}"]


def honorarios(p: Parametros, *, base: Any, percentual: Any) -> tuple[Decimal, list[str]]:
    v = _d(base) * _d(percentual)
    return v, [f"{brl(base)} × {percentual} = {brl(v)}"]


def valor_informado(p: Parametros, *, valor: Any, criterio: Any = "") -> tuple[Decimal, list[str]]:
    """Valor arbitrado/estimado com critério declarado (ex.: indenização); a conta é só o registro do valor."""
    return _d(valor), [f"valor indicado: {brl(valor)}" + (f" — critério: {criterio}" if criterio else "")]


CALCULADORAS: dict[str, Callable[..., tuple[Decimal, list[str]]]] = {
    "saldo_salario": saldo_salario, "aviso_previo": aviso_previo, "decimo_terceiro": decimo_terceiro,
    "ferias": ferias, "horas_extras": horas_extras, "dsr_reflexo": dsr_reflexo, "adicional_noturno": adicional_noturno,
    "intervalo_intrajornada": intervalo_intrajornada, "fgts": fgts, "multa_fgts": multa_fgts,
    "honorarios": honorarios, "valor_informado": valor_informado,
}


def calcular(rubrica: str, parametros: dict[str, Any], *, parametros_legais: dict[str, Any] | None = None,
             pedido_id: str = "", tese_id: str = "") -> Calculo:
    funcao = CALCULADORAS.get(str(rubrica or "").strip())
    if funcao is None:
        return Calculo(rubrica, 0.0, [], dict(parametros or {}), pedido_id=pedido_id, tese_id=tese_id, erro="sem calculadora para a rubrica")
    p = Parametros(parametros_legais)
    limpos = {k: v for k, v in (parametros or {}).items() if v not in (None, "")}
    try:
        valor, memoria = funcao(p, **limpos)
    except (TypeError, ValueError, ArithmeticError, KeyError) as erro:
        return Calculo(rubrica, 0.0, [], limpos, p.usados, pedido_id, tese_id, erro=f"parâmetros insuficientes: {erro}")
    return Calculo(rubrica, float(_r(valor)), memoria, limpos, p.usados, pedido_id, tese_id)


def executar(especificacoes: list[dict[str, Any]], *, parametros_legais: dict[str, Any] | None = None) -> list[Calculo]:
    """[{rubrica, parametros, pedido_id?, tese_id?}] → cálculos. Falha de um não derruba os outros."""
    return [calcular(str(e.get("rubrica") or ""), e.get("parametros") or {}, parametros_legais=parametros_legais,
                     pedido_id=str(e.get("pedido_id") or ""), tese_id=str(e.get("tese_id") or ""))
            for e in especificacoes or [] if isinstance(e, dict)]


# ------------------------------------------------------------------ valor da causa

def valor_da_causa(pedidos: list[dict[str, Any]]) -> dict[str, Any]:
    """Soma dos pedidos cumulativos autônomos com valor. Subsidiário/alternativo e acessório não somam."""
    somados, fora = [], []
    total = Decimal(0)
    for p in pedidos or []:
        v = p.get("valor")
        if v in (None, ""):
            continue
        cumulativo = str(p.get("natureza") or "cumulativo") == "cumulativo" and str(p.get("tipo_de_item") or "autonomo") == "autonomo"
        (somados if cumulativo else fora).append(p.get("id"))
        if cumulativo:
            total += _d(v)
    return {"valor": float(_r(total)), "pedidos_somados": somados, "pedidos_fora_da_soma": fora}


def verificar_valor_da_causa(pedidos: list[dict[str, Any]], valores_declarados: list[float]) -> list[dict[str, Any]]:
    """Erros que BLOQUEIAM: dois valores da causa diferentes, ou valor declarado ≠ soma dos pedidos."""
    erros = []
    distintos = sorted({float(_r(_d(v))) for v in valores_declarados or []})
    if len(distintos) > 1:
        erros.append({"codigo": "VALOR_DA_CAUSA_DIVERGENTE", "detalhe": f"valores diferentes no texto: {', '.join(brl(v) for v in distintos)}"})
    soma = valor_da_causa(pedidos)["valor"]
    if distintos and soma and abs(distintos[-1] - soma) > 0.01 and len(distintos) == 1:
        erros.append({"codigo": "VALOR_DA_CAUSA_DIFERENTE_DA_SOMA", "detalhe": f"declarado {brl(distintos[0])} × soma dos pedidos {brl(soma)}"})
    return erros


def hoje() -> date:
    return date.today()
