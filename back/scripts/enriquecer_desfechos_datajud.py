"""Preenche desfecho e vara dos precedentes com o registro OFICIAL do CNJ.

O BURACO QUE ISTO FECHA

Medido em 12/09/2026, no acervo vetorial:

    trt8_juris     43106 chunks | com rotulo: 43106 | com orgao: 43106
    datajud_djen    8123 chunks | com rotulo:     0 | com orgao:     0

A origem `datajud_djen` (as publicações do DJEN, incluindo os 500 processos da vara
preparados por `scripts/preparar_base_vara.py`) entra sem desfecho e sem órgão
julgador. Consequência concreta: `rag._estatisticas_amostra` só conta processo COM
`rotulo`, então esses 8 mil chunks **não entram** no "24/30 favoráveis no mérito"
que a tela mostra — e na lista de decisões consultadas eles aparecem como
"desfecho não informado; órgão não informado".

POR QUE DATAJUD, E NÃO LER O TEXTO DA PUBLICAÇÃO

Porque desfecho é FATO, e o DJEN publica aviso, não sentença estruturada.
"Julgo procedente" aparece em dezenas de formas, e uma intimação frequentemente
cita decisão de OUTRO processo — um `PROCEDENTE` errado entraria na estatística que
o advogado usa para decidir se entra com a ação, e ninguém teria como perceber.

O DataJud é a base pública do CNJ: cada processo vem com seus movimentos, e cada
movimento traz o código e o NOME da Tabela Processual Unificada. É registro
oficial do que foi decidido, não interpretação.

COMO O RÓTULO É DECIDIDO

Pelo NOME do movimento, cruzado com o código — e não pelo código de memória. O
nome vem na própria resposta da API, então é ele a fonte da verdade aqui; o código
serve de conferência. Movimento que não casar com nenhuma das regras abaixo deixa
o processo SEM rótulo, exatamente como está hoje: ausência de dado é melhor que
dado inventado.

Vale o movimento de julgamento MAIS RECENTE — uma sentença reformada em recurso
tem os dois movimentos, e o que valeu é o último.

POR QUE É RETOMÁVEL

A API do CNJ limita requisição (429) e às vezes recusa execução por fila cheia
(`es_rejected_execution_exception`). Então este script trabalha como o
`scripts/vetorizar_pendentes`: pega o que ainda está sem rótulo, respeita o limite,
e pode ser rodado quantas vezes for preciso — cada passada preenche o que conseguir.

Uso:
  .venv\\Scripts\\python.exe -m scripts.enriquecer_desfechos_datajud --limite 20
  .venv\\Scripts\\python.exe -m scripts.enriquecer_desfechos_datajud --tribunal TRT8
  .venv\\Scripts\\python.exe -m scripts.enriquecer_desfechos_datajud --confirmar
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag  # noqa: E402

#: Um por tribunal, como a API pública do CNJ expõe.
BASE_DATAJUD = "https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search"

#: Rótulos que o acervo já usa (ver `rag._estatisticas_amostra`): favoráveis são
#: PROCEDENTE + PARCIAL + ACORDO; o mérito conta PROCEDENTE + PARCIAL + IMPROCEDENTE.
#: Qualquer valor novo aqui mudaria silenciosamente aquelas contas.
PROCEDENTE = "PROCEDENTE"
PARCIAL = "PARCIAL"
IMPROCEDENTE = "IMPROCEDENTE"
ACORDO = "ACORDO"

#: Marca de "este processo já foi perguntado ao CNJ e a base não tem nada dele".
#:
#: POR QUE ELA EXISTE
#:
#: Sem ela, processo que o DataJud não conhece não recebe gravação nenhuma — e volta
#: para a fila em TODA passada seguinte, consumindo a cota da API do CNJ para receber
#: o mesmo nada. É o único recurso escasso deste script (429 e fila cheia), e o
#: desperdício cresce a cada rodada: ele é o que sobra na fila quando o resto já foi
#: preenchido. A marca não é desfecho nem entra em estatística — `rag` só lê `rotulo`
#: e `orgao_julgador`. Para perguntar de novo (a base do CNJ é atualizada), use
#: `--rever-sem-dado`.
SEM_DADO = "datajud_sem_dado"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn"
    ).lower()


def rotulo_do_movimento(codigo: Any, nome: str) -> str:
    """O desfecho que este movimento registra, ou "" quando não é julgamento.

    A ordem das conferências importa: "procedência em parte" e "improcedência"
    contêm a palavra "procedencia", então precisam ser testadas ANTES dela.
    """
    texto = _sem_acento(nome)
    try:
        cod = int(codigo)
    except (TypeError, ValueError):
        cod = -1

    # Acordo homologado: desfecho favorável, mas NÃO é mérito (o acervo já separa
    # os dois — ver o `criterio` em `_estatisticas_amostra`).
    if "homologacao de acordo" in texto or "homologacao de transacao" in texto or cod == 466:
        return ACORDO
    if "em parte" in texto or "parcialmente procedente" in texto or cod == 221:
        return PARCIAL
    if "improcedencia" in texto or "improcedente" in texto or cod == 220:
        return IMPROCEDENTE
    if "procedencia" in texto or "procedente" in texto or cod == 219:
        return PROCEDENTE
    return ""


def desfecho_do_processo(fonte: dict[str, Any]) -> tuple[str, str]:
    """(rótulo, nome do órgão julgador) a partir do documento do DataJud.

    Vale o movimento de julgamento mais RECENTE: sentença reformada em recurso
    deixa os dois registrados, e o que vale é o último.
    """
    orgao = str((fonte.get("orgaoJulgador") or {}).get("nome") or "").strip()
    julgamentos: list[tuple[str, str]] = []
    for movimento in fonte.get("movimentos") or []:
        rotulo = rotulo_do_movimento(movimento.get("codigo"), movimento.get("nome") or "")
        if rotulo:
            julgamentos.append((str(movimento.get("dataHora") or ""), rotulo))
    if not julgamentos:
        return "", orgao
    julgamentos.sort(key=lambda par: par[0])
    return julgamentos[-1][1], orgao


def _alias_do_tribunal(numero: str) -> str:
    """`trt8` a partir do número CNJ — o alias do índice do DataJud."""
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) != 20 or digitos[13] != "5":
        return ""
    try:
        regional = int(digitos[14:16])
    except ValueError:
        return ""
    return f"trt{regional}" if 1 <= regional <= 24 else ""


def _url_pg() -> str:
    rag.carregar_env()
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


def processos_sem_rotulo(limite: int, origem: str, rever_sem_dado: bool = False) -> list[str]:
    """Números de processo que ainda não foram consultados no DataJud.

    "Sem rótulo" NÃO basta como critério. Processo em andamento existe no DataJud,
    tem órgão julgador, e simplesmente ainda não foi julgado — consultá-lo de novo a
    cada passada nunca produziria rótulo e gastaria a cota da API do CNJ, que é o
    recurso escasso aqui (429 e fila cheia). O que marca "já consultei este" é o
    `orgao_julgador`, gravado sempre que o processo é encontrado, e a marca
    `SEM_DADO` quando o CNJ não conhece o processo. `rever_sem_dado` traz os
    marcados de volta para a fila.
    """
    with psycopg.connect(_url_pg(), connect_timeout=15) as con:
        linhas = con.execute(
            """
            SELECT DISTINCT metadados->>'numero_processo' AS numero
              FROM knowledge_chunks
             WHERE metadados->>'origem' = %s
               AND metadados->>'numero_processo' IS NOT NULL
               AND (metadados->>'rotulo') IS NULL
               AND (metadados->>'orgao_julgador') IS NULL
               AND (%s OR (metadados->>'{marca}') IS NULL)
             LIMIT %s
            """.format(marca=SEM_DADO),
            (origem, bool(rever_sem_dado), limite),
        ).fetchall()
    return [linha[0] for linha in linhas if linha[0]]


def gravar(numero: str, rotulo: str, orgao: str) -> int:
    """Escreve rótulo e órgão em todos os chunks daquele processo. Devolve quantos."""
    patch: dict[str, str] = {}
    if rotulo:
        patch["rotulo"] = rotulo
    if orgao:
        patch["orgao_julgador"] = orgao
    if not patch:
        return 0
    return _patch(numero, patch)


def _patch(numero: str, patch: dict[str, str]) -> int:
    with psycopg.connect(_url_pg(), connect_timeout=15) as con:
        cursor = con.execute(
            """
            UPDATE knowledge_chunks
               SET metadados = metadados || %s::jsonb
             WHERE metadados->>'numero_processo' = %s
            """,
            (json.dumps(patch, ensure_ascii=False), numero),
        )
        return cursor.rowcount or 0


def marcar_sem_dado(numero: str) -> int:
    """Registra que o CNJ não devolveu nada para este processo. Devolve quantos chunks."""
    return _patch(numero, {SEM_DADO: "1"})


def consultar(cliente: httpx.Client, chave: str, numero: str) -> dict[str, Any] | None:
    """O documento do processo no DataJud, com espera em 429 e em fila cheia."""
    alias = _alias_do_tribunal(numero)
    if not alias:
        return None
    atraso = 2.0
    for tentativa in range(5):
        try:
            resposta = cliente.post(
                BASE_DATAJUD.format(alias=alias),
                headers={"Authorization": chave, "Content-Type": "application/json"},
                json={"size": 1, "query": {"match": {"numeroProcesso": numero}}},
            )
        except httpx.HTTPError:
            time.sleep(atraso)
            atraso *= 2
            continue
        if resposta.status_code == 429 or "rejected_execution" in resposta.text[:400]:
            # Limite da API ou fila cheia do cluster: esperar é a única saída, e
            # desistir aqui perderia a passada inteira.
            time.sleep(atraso)
            atraso *= 2
            continue
        if resposta.status_code != 200:
            return None
        hits = ((resposta.json().get("hits") or {}).get("hits")) or []
        return hits[0]["_source"] if hits else None
    return None


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--limite", type=int, default=50, help="quantos processos nesta passada.")
    p.add_argument("--origem", default="datajud_djen", help="origem dos chunks a enriquecer.")
    p.add_argument("--por-segundo", type=float, default=0.7, help="requisições por segundo.")
    p.add_argument(
        "--rever-sem-dado",
        action="store_true",
        help="pergunta de novo os processos que o CNJ não conhecia (a base é atualizada).",
    )
    p.add_argument("--confirmar", action="store_true", help="grava. Sem isto, só mostra.")
    args = p.parse_args()

    rag.carregar_env()
    chave = os.getenv("DATAJUD_API_KEY", "").strip()
    if not chave:
        print("Falta DATAJUD_API_KEY no .env.")
        return 1
    # O valor no `.env` já vem com o prefixo `APIKey `. Passá-lo cru é o que
    # autentica; acrescentar o prefixo de novo dá 401 com "Illegal base64 character".
    if not chave.lower().startswith("apikey "):
        chave = f"APIKey {chave}"

    numeros = processos_sem_rotulo(args.limite, args.origem, args.rever_sem_dado)
    print(f"processos sem desfecho na origem {args.origem!r}: {len(numeros)} nesta passada")
    if not numeros:
        print("Nada a enriquecer.")
        return 0

    intervalo = 1.0 / max(0.05, args.por_segundo)
    achados = 0
    gravados = 0
    sem_dados = 0
    marcados = 0
    with httpx.Client(timeout=60.0) as cliente:
        for numero in numeros:
            fonte = consultar(cliente, chave, numero)
            time.sleep(intervalo)
            if not fonte:
                sem_dados += 1
                if args.confirmar:
                    marcados += marcar_sem_dado(numero)
                continue
            rotulo, orgao = desfecho_do_processo(fonte)
            if not rotulo and not orgao:
                sem_dados += 1
                if args.confirmar:
                    marcados += marcar_sem_dado(numero)
                continue
            achados += 1
            marca = rotulo or "(sem julgamento registrado)"
            print(f"  {numero}  {marca:14} {orgao[:44]}")
            if args.confirmar:
                gravados += gravar(numero, rotulo, orgao)

    print(f"\ncom dado no DataJud: {achados} | sem dado: {sem_dados}")
    if args.confirmar:
        print(f"chunks atualizados: {gravados}")
        if marcados:
            print(f"chunks marcados como sem dado no CNJ: {marcados} (não voltam à fila)")
    else:
        print("\n--- NADA FOI GRAVADO --- rode com --confirmar.")
    print(
        "\nA API do CNJ limita requisição: rode de novo para continuar de onde parou."
        "\nEsta passada só olha processo que ainda NÃO foi consultado."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
