"""O que o sistema JÁ tem sobre um caso, pronto para aparecer dentro da conversa.

Este é o destino que não gasta modelo nenhum. Quando a pergunta é "quais documentos tem
o caso da Maria?", a resposta não precisa ser escrita por uma IA: ela está guardada, com
nome de arquivo, data e estado de conferência. Montá-la aqui é mais rápido, mais barato e
— o que importa mais — exatamente verdadeira, porque é a leitura do checklist e não um
resumo dele.

DUAS SAÍDAS, UMA FONTE

- `montar()` devolve o painel inteiro: entregas, pendências, entrevistas e peças. É o que
  a tela embute na conversa quando se clica em "Ver aqui";
- `resumir()` escreve o mesmo material em texto, que é o corpo da mensagem.

As duas leem a MESMA `casos.montar_situacao`. Se fossem duas leituras, o texto da
conversa e o painel embaixo dele poderiam discordar — e aí nenhum dos dois valeria.

O ARQUIVO EM SI não passa por aqui. Cada entrega carrega o caminho de onde baixá-la
(`/api/entregas/{id}/arquivo`), que é a rota que já existe e já confere a sessão de quem
pede. Copiar binário para dentro da resposta do chat só serviria para estourar a memória
de um processo que devia estar respondendo perguntas.
"""

from __future__ import annotations

from typing import Any

from .. import armazenamento, casos as casos_lib

__all__ = ["montar", "resumir"]

#: Quantas entregas vão no painel. Caso grande passa de cem arquivos, e o chat não é o
#: lugar de paginar o acervo — para isso existe o dossiê, e o atalho leva até lá.
_MAXIMO_DE_ENTREGAS = 30

#: Quantas peças e entrevistas acompanham. Poucas de propósito: são contexto, não lista.
_MAXIMO_DE_PECAS = 8


def montar(caso_id: str) -> dict[str, Any] | None:
    """O painel do caso, ou `None` quando o caso não está mais no acervo."""
    situacao = casos_lib.montar_situacao(caso_id)
    if situacao is None:
        return None

    caso = situacao["caso"]
    entregas = armazenamento.listar_entregas(caso_id)
    entrevistas = armazenamento.listar_entrevistas(caso_id)
    pecas = armazenamento.listar_peticoes_anexas(caso_id)

    return {
        "caso": {
            "id": caso.get("id"),
            "cliente": caso.get("cliente") or "",
            "categoria": str(caso.get("categoria") or "").replace("_", " "),
            "criado_em": caso.get("criado_em") or "",
        },
        "progresso": situacao.get("progresso") or {},
        "entregas": [_entrega(e) for e in entregas[:_MAXIMO_DE_ENTREGAS]],
        "entregas_ocultas": max(0, len(entregas) - _MAXIMO_DE_ENTREGAS),
        "pendentes": casos_lib.documentos_pendentes_da_situacao(situacao),
        "entrevistas": [
            {
                "id": e.get("id"),
                "realizada_em": e.get("realizada_em") or e.get("criado_em") or "",
                "entrevistador": e.get("entrevistador") or "",
                "resumo": str(e.get("resumo") or "")[:400],
            }
            for e in entrevistas[:_MAXIMO_DE_PECAS]
        ],
        "pecas": [
            {
                "id": p.get("id"),
                "titulo": p.get("titulo") or "Peça sem título",
                "criado_em": p.get("criado_em") or "",
            }
            for p in pecas[:_MAXIMO_DE_PECAS]
        ],
    }


def _entrega(registro: dict[str, Any]) -> dict[str, Any]:
    """Uma entrega como o chat a mostra: o que é, se confere, e onde abri-la.

    `tipo_confere` é `None` quando ninguém conferiu ainda, e essa diferença não pode
    virar "não confere" na tela: são estados distintos e levam a ações distintas.
    """
    return {
        "id": registro.get("id"),
        "arquivo": registro.get("arquivo") or "",
        "item": registro.get("item_codigo") or "",
        "tipo_detectado": registro.get("tipo_detectado") or "",
        "tipo_confere": registro.get("tipo_confere"),
        "status": registro.get("status_proc") or "",
        "recebido_em": registro.get("criado_em") or "",
        # A rota que já existe, com a conferência de sessão que já existe.
        "arquivo_url": f"/api/entregas/{registro.get('id')}/arquivo",
    }


def resumir(painel: dict[str, Any]) -> str:
    """O painel escrito como mensagem — o texto que fica gravado na transcrição.

    Escrito aqui, e não por um modelo, porque este é o tipo de resposta em que qualquer
    reescrita só pode piorar: nome de arquivo e contagem não melhoram com estilo, e um
    modelo que "resume" catorze documentos em "alguns documentos" apagou a resposta.
    """
    caso = painel["caso"]
    entregas = painel["entregas"]
    pendentes = painel["pendentes"]
    progresso = painel.get("progresso") or {}

    linhas = [f"**Documentos do caso de {caso['cliente']}**"]
    if caso.get("categoria"):
        linhas.append(f"Categoria: {caso['categoria']}.")

    entregues = progresso.get("obrigatorios_entregues")
    total = progresso.get("obrigatorios_total")
    if entregues is not None and total:
        linhas.append(
            f"Checklist: {entregues} de {total} documentos obrigatórios entregues."
        )
    if progresso.get("itens_a_conferir"):
        linhas.append(f"{progresso['itens_a_conferir']} item(ns) esperando conferência.")

    if entregas:
        ocultas = painel.get("entregas_ocultas") or 0
        cabecalho = f"\n**Entregues ({len(entregas)}"
        cabecalho += f" de {len(entregas) + ocultas}" if ocultas else ""
        linhas.append(cabecalho + ")**")
        for item in entregas:
            selo = _selo(item)
            rotulo = item["arquivo"] or item["tipo_detectado"] or "arquivo sem nome"
            linhas.append(f"- {rotulo}{selo}")
        if ocultas:
            linhas.append(f"- … e mais {ocultas} no dossiê do caso.")
    else:
        linhas.append("\nNenhum documento foi entregue neste caso ainda.")

    if pendentes:
        linhas.append(f"\n**Ainda faltam ({len(pendentes)})**")
        for item in pendentes[:12]:
            motivo = str(item.get("motivo") or "").strip()
            linhas.append(f"- {item.get('nome')}" + (f" — {motivo}" if motivo else ""))

    if painel.get("entrevistas"):
        linhas.append(f"\n{len(painel['entrevistas'])} entrevista(s) guardada(s) neste caso.")
    if painel.get("pecas"):
        titulos = ", ".join(p["titulo"] for p in painel["pecas"])
        linhas.append(f"Peças já geradas: {titulos}.")

    return "\n".join(linhas)


def _selo(entrega: dict[str, Any]) -> str:
    """A palavra entre parênteses depois do nome do arquivo.

    Três estados, e não dois: conferido, divergente e **não conferido**. Achatar o
    terceiro no segundo faria o chat acusar de errado o documento que ninguém olhou.
    """
    if entrega.get("tipo_confere") is True:
        return f" ({entrega['tipo_detectado']}, confere)" if entrega.get("tipo_detectado") else " (confere)"
    if entrega.get("tipo_confere") is False:
        detectado = entrega.get("tipo_detectado") or "outro tipo"
        return f" (lido como {detectado} — não bate com o item)"
    if entrega.get("status") and entrega["status"] not in ("ok", "concluido"):
        return f" (leitura: {entrega['status']})"
    return " (ainda não conferido)"
