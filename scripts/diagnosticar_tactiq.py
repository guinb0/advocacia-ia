"""Diagnóstico seguro do MCP: mostra ferramentas e erros, nunca tokens."""
from __future__ import annotations

import argparse

from app import ambiente


def main() -> None:
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--reunioes", action="store_true")
    argumentos.add_argument("--transcricao")
    argumentos.add_argument("--bruto-transcricao")
    opcoes = argumentos.parse_args()
    ambiente.carregar()
    # `auth.JWT_SECRET` é lido na importação; carregar o .env antes evita que o
    # diagnóstico simule uma instância de produção sem segredo.
    from app import tactiq
    from app.banco import conectar
    tactiq.inicializar()
    with conectar() as banco:
        linha = banco.execute(
            f"SELECT TOP 1 usuario_id FROM {tactiq.TABELA} WHERE access_token_cifrado IS NOT NULL ORDER BY atualizado_em DESC"
        ).fetchone()
    if not linha:
        raise SystemExit("Nenhuma conexão Tactiq ativa encontrada.")
    ferramentas = tactiq.ferramentas(str(linha["usuario_id"]))
    if opcoes.reunioes:
        for reuniao in tactiq.listar_reunioes(str(linha["usuario_id"])):
            print(reuniao)
        return
    if opcoes.transcricao:
        resultado = tactiq.transcricao(str(linha["usuario_id"]), opcoes.transcricao)
        print(resultado["titulo"], len(resultado["texto"]))
        return
    if opcoes.bruto_transcricao:
        def executar(cliente, cabecalho):
            ferramentas = tactiq._ferramentas_na_sessao(cliente, cabecalho)
            ferramenta = tactiq._ferramenta_por_nome(ferramentas, "get_transcript")
            return tactiq._chamar(cliente, cabecalho, ferramenta["name"], {"meetingId": opcoes.bruto_transcricao, "page": 1})
        print(tactiq._mcp(str(linha["usuario_id"]), executar))
        return
    for ferramenta in ferramentas:
        print(ferramenta.get("name"), "|", ferramenta.get("description") or "", "|", ferramenta.get("inputSchema") or {})


if __name__ == "__main__":
    main()
