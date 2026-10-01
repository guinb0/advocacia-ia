"""Classifica as peças já indexadas em `pecas_conteudo` por assunto/tese/pedidos.

POR QUE ISTO EXISTE

`ingerir_pasta_pecas.py` grava só `{origem, caminho_original, extensao}` em
`metadados` — o retrieval de `rag.buscar_pecas_conteudisticas` depende 100% de
similaridade vetorial do texto inteiro do caso contra o corpus inteiro. Um caso
de acidente de trabalho nos Correios não favorece peças de acidente de
trabalho: qualquer peça trabalhista com vocabulário parecido concorre igual.

Este script NÃO reindexa nem reembeda nada — os chunks e embeddings de
`ingerir_pasta_pecas.py` continuam os mesmos. Só lê `texto_integral` (já
extraído) e ACRESCENTA classificação ao `metadados` de `pecas_conteudo`
(merge, nunca substitui as chaves que já existem — origem/caminho continuam
lá). Chamada única por peça, sem chunking: o assunto de uma petição inteira não
precisa do texto inteiro, os primeiros milhares de caracteres (endereçamento,
qualificação, início dos fatos e do direito) já entregam o suficiente.

`assunto` usa o MESMO vocabulário fechado das referências da skill de arquivo
(`app/peticao_skill_arquivos._MAPA_ASSUNTOS`, arquivo sem `.md`) — é o que
permite `rag.buscar_pecas_conteudisticas` filtrar por assunto depois, com o
mesmo identificador que já classifica o CASO (ver `peticao_skill_arquivos`).

RETOMÁVEL: roda de novo sobre o que já tem `metadados.assunto` só com
`--forcar`. Uma peça que falhar (erro de rede, resposta ilegível) fica sem
classificação e entra de novo na próxima passada — não trava o lote inteiro.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import sys

import httpx
import psycopg
from psycopg.rows import dict_row

from app import ambiente

# Console do Windows abre em cp1252 por padrão — nome de arquivo com "ç"/"ã"
# (comuns nas peças) derrubava o `print` no meio de um lote de 800. UTF-8 com
# `errors="replace"` garante que uma saída de log nunca seja o que interrompe
# a classificação em si.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Mesmo vocabulário de `app/peticao_skill_arquivos.py` — não importa daqui
#: para não acoplar o script de banco ao módulo de prompt; mantidos em sync à
#: mão, e a duplicação está documentada nos dois lugares.
ASSUNTOS = (
    "assalto_carteiro",
    "verbas_rescisorias",
    "horas_extras",
    "doenca_ocupacional_acidente_trabalho",
    "equiparacao_salarial_acumulo_funcao",
    "assedio_moral_dano_moral_trabalhista",
    "vinculo_terceirizacao",
    "estabilidades",
    "adicional_insalubridade_periculosidade",
    "justa_causa_dispensa_discriminatoria",
    "fgts_diferencas_salariais",
    "outros_assuntos",
)

TIPOS_PECA = (
    "peticao_inicial", "quesitos_pericia", "impugnacao_contestacao", "recurso",
    "manifestacao_laudo", "calculos", "contestacao", "outro",
)

#: Caracteres do início da peça que bastam para identificar assunto/teses/
#: pedidos — endereçamento, qualificação, boa parte dos fatos e o começo do
#: direito. Testado: petições de 8-15 páginas têm o essencial nos primeiros
#: 8 mil caracteres; ir além só encarece sem mudar a classificação.
JANELA_TEXTO = 8_000

INSTRUCAO = f"""Você classifica uma petição trabalhista já pronta, para um acervo de
referência interno de um escritório. Leia o início da peça abaixo e devolva
APENAS JSON:

{{
  "assunto": "um destes, o que MAIS combina: {', '.join(ASSUNTOS)}",
  "subteses": ["até 5 subteses jurídicas específicas tratadas, ex.: 'nexo causal',
                'responsabilidade objetiva', 'estabilidade acidentária'"],
  "pedidos": ["até 8 tipos de pedido formulados, ex.: 'indenização por dano moral',
               'horas extras e reflexos', 'reintegração'"],
  "tipo_peca": "a FASE/ESPÉCIE da peça, um de: peticao_inicial|quesitos_pericia|impugnacao_contestacao|
                 recurso|manifestacao_laudo|calculos|contestacao|outro",
  "tipo_vinculo": "um de: clt|terceirizado|pejotizado|domestico|indefinido",
  "empregador_setor": "o ramo/setor do empregador em poucas palavras, se identificável
                        pela peça (ex.: 'correios', 'construção civil', 'varejo'), ou
                        vazio se não der para saber"
}}

Não invente informação que não esteja no texto. "assunto" é sempre um dos valores
da lista, nunca outro texto — use "outros_assuntos" se nenhum combinar bem."""


def _chamar_modelo(texto: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("DEEPSEEK_API_KEY ausente — configure no .env.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    ultimo_erro: Exception | None = None
    for tentativa in (1, 2):
        try:
            resposta = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {chave}"},
                json={
                    "model": modelo,
                    "temperature": 0,
                    "max_tokens": 1200,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": INSTRUCAO},
                        {"role": "user", "content": texto[:JANELA_TEXTO]},
                    ],
                },
                timeout=90.0,
            )
            resposta.raise_for_status()
            conteudo = resposta.json()["choices"][0]["message"]["content"]
            saida = json.loads(conteudo)
            if not isinstance(saida, dict):
                raise ValueError(f"esperava objeto JSON, veio {type(saida).__name__}")
            return saida
        except Exception as erro:  # noqa: BLE001 - tentativa de novo, não propaga ainda
            ultimo_erro = erro
            time.sleep(1.5)
    raise RuntimeError(f"modelo não respondeu: {ultimo_erro}")


def _normalizar_saida(bruto: dict[str, Any]) -> dict[str, Any]:
    assunto = str(bruto.get("assunto") or "").strip()
    if assunto not in ASSUNTOS:
        assunto = "outros_assuntos"
    return {
        "assunto": assunto,
        "subteses": [str(s).strip() for s in (bruto.get("subteses") or []) if str(s).strip()][:5],
        "pedidos": [str(p).strip() for p in (bruto.get("pedidos") or []) if str(p).strip()][:8],
        "tipo_peca": (
            str(bruto.get("tipo_peca") or "outro").strip().lower()
            if str(bruto.get("tipo_peca") or "").strip().lower() in TIPOS_PECA else "outro"
        ),
        "tipo_vinculo": str(bruto.get("tipo_vinculo") or "indefinido").strip().lower(),
        "empregador_setor": str(bruto.get("empregador_setor") or "").strip(),
        "classificado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def classificar(*, limite: int | None, forcar: bool, chave: str = "assunto") -> None:
    ambiente.carregar()
    # `--chave tipo_peca`: completa só o campo novo nas peças já classificadas por
    # assunto, sem refazer (e pagar de novo) o que já existe.
    condicao = "" if forcar else f"WHERE NOT (metadados ? '{chave}')"
    limite_sql = f"LIMIT {int(limite)}" if limite else ""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as con:
        linhas = con.execute(
            f"SELECT id, nome_arquivo, texto_integral FROM pecas_conteudo "
            f"{condicao} ORDER BY id {limite_sql}"
        ).fetchall()
        if not linhas:
            print("Nada para classificar (use --forcar para reclassificar tudo).", flush=True)
            return
        ok = falhas = 0
        for indice, linha in enumerate(linhas, start=1):
            try:
                bruto = _chamar_modelo(linha["texto_integral"] or "")
                classificacao = _normalizar_saida(bruto)
                con.execute(
                    "UPDATE pecas_conteudo SET metadados = metadados || %s::jsonb, "
                    "atualizado_em = now() WHERE id = %s",
                    (json.dumps(classificacao, ensure_ascii=False), linha["id"]),
                )
                con.commit()
                ok += 1
                print(
                    f"[{indice}/{len(linhas)}] {linha['nome_arquivo']}: "
                    f"{classificacao['assunto']} ({', '.join(classificacao['subteses'][:2])})",
                    flush=True,
                )
            except Exception as erro:  # noqa: BLE001 - uma peça ruim não derruba o lote
                con.rollback()
                falhas += 1
                print(f"[{indice}/{len(linhas)}] falhou: {linha['nome_arquivo']}: {erro}", flush=True)
        print(f"Concluído: {ok} classificada(s), {falhas} falha(s) de {len(linhas)}.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite", type=int, default=None, help="Classifica só as N primeiras (teste).")
    parser.add_argument("--forcar", action="store_true", help="Reclassifica mesmo quem já tem assunto.")
    parser.add_argument("--chave", default="assunto", choices=["assunto", "tipo_peca"],
                        help="Qual campo falta: classifica só as peças sem ele.")
    args = parser.parse_args()
    classificar(limite=args.limite, forcar=args.forcar, chave=args.chave)


if __name__ == "__main__":
    main()
