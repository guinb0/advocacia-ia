"""Acompanhamento da equipe: quem entrevistou, quanto, e o que foi dito.

PARA QUE ISTO EXISTE

O secretário do escritório precisa responder duas perguntas que nenhuma tela
respondia: quantas entrevistas cada pessoa fez, e o que foi dito em cada uma.
Antes, entrevista só aparecia dentro do caso — para ter o total de alguém era
preciso abrir caso por caso e somar de cabeça.

DE ONDE VEM A ATRIBUIÇÃO, E O QUE ELA NÃO ALCANÇA

Da coluna `entrevistador`. Ela sempre existiu, mas era texto livre preenchido à
mão e ficava vazia: das sete entrevistas já gravadas, seis não dizem quem as fez.
A rota de envio passou a assumir quem está logado (ver `_quem_conduziu` em
`main.py`), então isso se resolve DAQUI PARA A FRENTE — o que já está gravado sem
nome continua sem nome, e aparece agrupado como "não identificado" em vez de ser
escondido. Sumir com elas faria a soma da tela não bater com a realidade.

POR QUE SÓ O SECRETÁRIO

Ver a transcrição de todas as entrevistas do escritório é acesso amplo a relato
de cliente. O advogado já alcança o que é dos casos dele; esta visão atravessa
todos, e por isso é do papel cuja função é justamente essa.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import armazenamento, auditoria, contrato
from .auth import exigir_papel
from .cache_leitura import por_alguns_segundos

log = logging.getLogger("supervisao")

roteador = APIRouter(prefix="/api/supervisao", tags=["supervisao"])

SoSecretario = Depends(exigir_papel("secretario"))

#: Como aparece quem conduziu entrevista antes de a atribuição existir.
SEM_NOME = "não identificado"


def _chave(nome: object) -> str:
    """Junta grafias do mesmo nome sem inventar identidade.

    Compara sem caixa e sem espaço duplicado — "  Dra. Helena  Prado" e
    "Dra. Helena Prado" são a mesma pessoa. NÃO tenta casar apelido com nome
    completo: errar isso somaria o trabalho de uma pessoa na conta de outra, que
    é pior que mostrar duas linhas parecidas e deixar quem olha decidir.
    """
    return " ".join(str(nome or "").split()).casefold()


def _data_curta(bruto: object) -> str:
    """dd/mm/aaaa a partir do que estiver gravado, seja lá em que formato.

    `realizada_em` é texto livre digitado à mão, e o acervo tem os dois formatos
    convivendo: "2026-08-21" (ISO, do `criado_em` e do que a tela nova grava) e
    "12/08/2026" (brasileiro, do que foi digitado). Mostrar os dois lado a lado numa
    coluna de tabela faz a data parecer erro de dado — e aqui ela é só a resposta a
    "quando foi a última", que precisa ser comparável de bater o olho.
    """
    texto = str(bruto or "").strip()[:10]
    if len(texto) == 10 and texto[4] == "-" and texto[7] == "-":
        return f"{texto[8:10]}/{texto[5:7]}/{texto[0:4]}"
    return texto


@roteador.get("/entrevistas", dependencies=[SoSecretario])
@por_alguns_segundos(5)
def por_entrevistador() -> dict[str, Any]:
    """Quantas entrevistas cada um fez, e a lista de cada pessoa."""
    entrevistas = armazenamento.listar_resumo_supervisao()
    # O nome do cliente não está na entrevista, e abrir caso a caso seria uma
    # consulta por linha. Uma leitura da lista de casos resolve todas de uma vez:
    # a tela mostra "Helena Prado — 12 entrevistas" e, dentro, de quem foi cada
    # uma; data sozinha não diz ao secretário qual atendimento ele está abrindo.

    pessoas: dict[str, dict[str, Any]] = {}
    for e in entrevistas:
        nome = " ".join(str(e.get("entrevistador") or "").split())
        chave = _chave(nome) or SEM_NOME
        grupo = pessoas.setdefault(
            chave, {"entrevistador": nome or SEM_NOME, "quantidade": 0, "entrevistas": []}
        )
        grupo["quantidade"] += 1
        grupo["entrevistas"].append(
            {
                "id": e.get("id"),
                "caso_id": e.get("caso_id"),
                "cliente": e.get("cliente") or "",
                "arquivo": e.get("arquivo"),
                "realizada_em": e.get("realizada_em"),
                "criado_em": e.get("criado_em"),
                # O tamanho dá noção do que há para ler sem despejar o texto
                # inteiro numa lista que pode ter centenas de linhas.
                "caracteres": int(e.get("caracteres") or 0),
                "fatos_gerados": e.get("fatos_gerados"),
                # Os dois sinais que a lista consegue dar SEM ir ao modelo. Ficam
                # aqui para o secretário ver a pendência antes de abrir a
                # entrevista — a conferência do roteiro custa uma ida ao modelo e
                # não pode rodar em lote para trinta linhas de uma lista.
                "avaliacao_google": bool(e.get("avaliacao_google")),
                "enviada": bool(e.get("enviada")),
                # Vazio = anexada como arquivo; preenchida = conduzida ao vivo pelo
                # roteiro, e só essa tem áudio para o secretário ouvir.
                "gravacao_id": e.get("gravacao_id") or "",
            }
        )

    itens = sorted(
        pessoas.values(),
        # Quem mais fez primeiro; "não identificado" vai para o fim mesmo sendo
        # grande, porque é pendência de dado, não desempenho de ninguém.
        key=lambda p: (p["entrevistador"] == SEM_NOME, -p["quantidade"]),
    )
    for pessoa in itens:
        pessoa["entrevistas"].sort(key=lambda x: str(x.get("criado_em") or ""), reverse=True)
        # O resumo de cada um, calculado AQUI e não na tela.
        #
        # A tela precisa ordenar por "quem tem mais pendência" e desenhar barra de
        # proporção; fazer essa conta no navegador significaria refazê-la a cada
        # render e, pior, tê-la escrita em dois lugares no dia em que a supervisão
        # ganhar um segundo consumidor (um relatório, um e-mail semanal).
        lista = pessoa["entrevistas"]
        pessoa["com_avaliacao"] = sum(1 for e in lista if e["avaliacao_google"])
        pessoa["com_dossie"] = sum(1 for e in lista if e["enviada"])
        pessoa["ao_vivo"] = sum(1 for e in lista if e["gravacao_id"])
        pessoa["ultima_em"] = next(
            (_data_curta(e.get("realizada_em") or e.get("criado_em")) for e in lista), ""
        )

    total = len(entrevistas)
    return {
        "itens": itens,
        "total_entrevistas": total,
        "total_pessoas": sum(1 for p in itens if p["entrevistador"] != SEM_NOME),
        "sem_atribuicao": sum(
            p["quantidade"] for p in itens if p["entrevistador"] == SEM_NOME
        ),
        # O que o escritório inteiro deve, em número — é o topo do painel. São
        # PENDÊNCIAS e não acertos de propósito: o secretário abre esta tela para
        # descobrir o que cobrar hoje, e "21 com avaliação" o obrigaria a subtrair
        # de cabeça para chegar no número que ele veio buscar.
        "pendencias": {
            "sem_avaliacao": sum(1 for e in entrevistas if not e.get("avaliacao_google")),
            "sem_dossie": sum(1 for e in entrevistas if not e.get("enviada")),
            "sem_quem_conduziu": sum(
                1 for e in entrevistas if not str(e.get("entrevistador") or "").strip()
            ),
            "ao_vivo": sum(1 for e in entrevistas if e.get("gravacao_id")),
            "anexadas": sum(1 for e in entrevistas if not e.get("gravacao_id")),
        },
    }


@roteador.get("/entrevistas/{entrevista_id}", dependencies=[SoSecretario])
def transcricao(entrevista_id: str) -> dict[str, Any]:
    """A transcrição inteira de uma entrevista, com o que o agente extraiu dela."""
    e = armazenamento.obter_entrevista(entrevista_id)
    if e is None:
        raise HTTPException(404, "Entrevista não encontrada.")
    return {
        "id": e.get("id"),
        "caso_id": e.get("caso_id"),
        "entrevistador": e.get("entrevistador") or SEM_NOME,
        "arquivo": e.get("arquivo"),
        "realizada_em": e.get("realizada_em"),
        "criado_em": e.get("criado_em"),
        "texto": e.get("texto") or "",
        "resumo": e.get("resumo") or "",
        "perguntas": e.get("perguntas") or [],
        "fatos_gerados": e.get("fatos_gerados"),
        "avaliacao_google": bool(e.get("avaliacao_google")),
        "gravacao_id": e.get("gravacao_id") or "",
    }


@roteador.post("/entrevistas/{entrevista_id}/auditoria", dependencies=[SoSecretario])
def auditar_entrevista(entrevista_id: str) -> dict[str, Any]:
    """Lê a transcrição bruta e diz o que do roteiro não aparece nela.

    É POST e não GET porque cada chamada custa uma ida ao modelo: com GET, um
    refresh da tela dispararia a análise de novo, e o secretário abre esta lista
    o dia inteiro.
    """
    e = armazenamento.obter_entrevista(entrevista_id)
    if e is None:
        raise HTTPException(404, "Entrevista não encontrada.")
    try:
        relatorio = auditoria.auditar(str(e.get("texto") or ""))
    except auditoria.ErroAuditoria as exc:
        # 503 e não 500: falta de chave ou modelo fora do ar é indisponibilidade,
        # e a mensagem já diz o que fazer.
        raise HTTPException(503, str(exc)) from exc
    relatorio["entrevista_id"] = entrevista_id
    relatorio["entrevistador"] = e.get("entrevistador") or SEM_NOME
    return relatorio


# --------------------------------------------------------------- checklist


#: Situações possíveis de um item do checklist.
#:
#: `incerto` existe porque nem tudo que a tela mostra é fato: o que vem da leitura do
#: modelo pode ser erro de reconhecimento de voz, e marcar como pendente o que só está
#: ilegível manda o secretário cobrar trabalho que foi feito. `nao_aplica` sai da conta
#: do progresso — cobrar assinatura de um atendimento que ainda não gerou papelada
#: deixaria todo checklist eternamente incompleto.
SITUACOES = ("feito", "pendente", "incerto", "nao_aplica")


def _item(
    identificador: str,
    titulo: str,
    detalhe: str,
    etiqueta: str,
    situacao: str,
    *,
    critico: bool = False,
) -> dict[str, Any]:
    """Uma linha do checklist. `critico` é o que não tem segunda chance."""
    return {
        "id": identificador,
        "titulo": titulo,
        "detalhe": detalhe,
        "etiqueta": etiqueta,
        "situacao": situacao if situacao in SITUACOES else "incerto",
        "critico": critico,
    }


def _fase(codigo: str, titulo: str, descricao: str, itens: list[dict[str, Any]]) -> dict[str, Any]:
    return {"codigo": codigo, "titulo": titulo, "descricao": descricao, "itens": itens}


def _fase_avaliacao(entrevista: dict[str, Any]) -> dict[str, Any]:
    """Google Meu Negócio — a etapa que só acontece com o cliente ainda na chamada.

    O roteiro é explícito: a atendente pede a avaliação AGORA e permanece na
    videoconferência até confirmar que saiu. Por isso o item é crítico — desligada a
    chamada não há segunda chance, e "mandei o link" não é avaliação feita.
    """
    marcada = bool(entrevista.get("avaliacao_google"))
    quando = str(entrevista.get("avaliacao_google_em") or "")[:16].replace("T", " ")
    return _fase(
        "avaliacao",
        "Avaliação no Google Meu Negócio",
        "O fechamento do roteiro pede a avaliação com o cliente ainda na chamada.",
        [
            _item(
                "avaliacao-confirmada",
                "O cliente concluiu a avaliação, e o atendente confirmou na chamada",
                f"Marcada em {quando}."
                if marcada
                else (
                    "Sem marcação. Pode ter acontecido sem ninguém registrar — mas, "
                    "sem registro, não há como conferir."
                ),
                "Crítico",
                "feito" if marcada else "pendente",
                critico=True,
            )
        ],
    )


def _situacao_do_documento(registro: dict[str, Any] | None) -> tuple[str, str]:
    """Estado de um dos documentos assinados, e a frase que explica o estado."""
    if registro is None:
        return "pendente", "Não foi enviado para assinatura."
    estado = str(registro.get("estado") or "pendente")
    if estado == "assinado":
        return "feito", "Assinado por todos os signatários."
    if estado == "recusado":
        return "pendente", "Recusado por um dos signatários — precisa ser reenviado."
    faltam = [str(n).strip() for n in (registro.get("faltam") or []) if str(n).strip()]
    assinaram = registro.get("assinaram") or 0
    total = registro.get("total") or 0
    if faltam:
        return "pendente", f"{assinaram} de {total} assinaram. Falta: {', '.join(faltam[:3])}."
    return "pendente", f"Enviado; {assinaram} de {total} assinaram."


def _fase_papelada(caso_id: str, assinaturas: list[dict[str, Any]]) -> dict[str, Any]:
    """Contrato, procuração e declaração — a papelada que sai do mesmo atendimento.

    São os três de `contrato.MODELOS`, e não só o contrato: sem procuração não se
    peticiona, e sem declaração de hipossuficiência não há gratuidade de justiça. O
    casamento é pelo começo do nome gravado ("Contrato de honorários — Fulano"), que é
    como `main.py` o monta ao enviar para a ZapSign.
    """
    itens: list[dict[str, Any]] = []
    for modelo in contrato.MODELOS:
        rotulo = str(modelo["rotulo"])
        registro = next(
            (a for a in assinaturas if str(a.get("nome") or "").startswith(rotulo)), None
        )
        situacao, detalhe = _situacao_do_documento(registro)
        itens.append(
            _item(
                f"assinatura-{modelo['codigo']}",
                rotulo,
                detalhe if caso_id else "A entrevista não está vinculada a um caso.",
                "Assinatura",
                situacao if caso_id else "nao_aplica",
                critico=modelo["codigo"] in ("contrato", "procuracao"),
            )
        )
    return _fase(
        "papelada",
        "Papelada e assinaturas",
        "Os três documentos que o cliente assina saem do mesmo atendimento.",
        itens,
    )


def _fase_registro(entrevista: dict[str, Any], entregas: list[dict[str, Any]]) -> dict[str, Any]:
    """O que o atendimento deixou gravado — conferível sem ler a conversa."""
    entrevistador = " ".join(str(entrevista.get("entrevistador") or "").split())
    gravacao = str(entrevista.get("gravacao_id") or "")
    caracteres = len(str(entrevista.get("texto") or ""))
    fatos = int(entrevista.get("fatos_gerados") or 0)
    resumo = str(entrevista.get("resumo") or "").strip()
    realizada = str(entrevista.get("realizada_em") or "").strip()

    return _fase(
        "registro",
        "Registro do atendimento",
        "O rastro que o atendimento deixou no sistema.",
        [
            _item(
                "registro-entrevistador",
                "Quem conduziu está registrado",
                entrevistador
                or "Gravada antes de o sistema passar a atribuir a entrevista a quem a fez.",
                "Atribuição",
                "feito" if entrevistador else "pendente",
            ),
            _item(
                "registro-data",
                "Data da entrevista informada",
                realizada or "Sem data de realização — consta só quando o arquivo subiu.",
                "Cadastro",
                "feito" if realizada else "pendente",
            ),
            _item(
                "registro-transcricao",
                "Transcrição gravada e com conversa suficiente",
                f"{caracteres} caracteres."
                if caracteres >= auditoria.MINIMO_CONVERSA
                else "Texto curto demais para conferir a condução da entrevista.",
                "Transcrição",
                "feito" if caracteres >= auditoria.MINIMO_CONVERSA else "pendente",
                critico=True,
            ),
            _item(
                "registro-agente",
                "Entrevista lida pelo agente jurídico",
                f"{fatos} fato(s) gerados para o dossiê."
                if entrevista.get("enviada")
                else "Ainda não foi lida — o dossiê do caso não tem os fatos desta conversa.",
                "Dossiê",
                "feito" if entrevista.get("enviada") else "pendente",
            ),
            _item(
                "registro-resumo",
                "Resumo do atendimento disponível",
                resumo[:180] if resumo else "Sem resumo gravado.",
                "Dossiê",
                "feito" if resumo else "pendente",
            ),
            _item(
                "registro-audio",
                "Áudio do atendimento guardado",
                f"Gravação {gravacao[:8]} — dá para ouvir o trecho em vez de só ler."
                if gravacao
                else (
                    "Entrevista anexada como arquivo: não há gravação do atendimento "
                    "a que ligá-la."
                ),
                "Gravação",
                # Sem gravação não é falha de ninguém: a entrevista anexada à mão
                # nunca teve áudio para guardar. Cobrar isso apontaria pendência em
                # todo registro antigo do escritório.
                "feito" if gravacao else "nao_aplica",
            ),
            _item(
                "registro-documentos",
                "Documentos do cliente recebidos",
                f"{len(entregas)} documento(s) entregues no caso."
                if entregas
                else "Nenhum documento entregue até agora.",
                "Documentação",
                "feito" if entregas else "pendente",
            ),
        ],
    )


def _progresso(fases: list[dict[str, Any]]) -> dict[str, int]:
    """Quanto do que é conferível SEM ler a conversa já está feito.

    `nao_aplica` sai do denominador. `incerto` conta como não feito, mas a diferença
    entre um e outro aparece na linha, não no número.
    """
    itens = [i for f in fases for i in f["itens"] if i["situacao"] != "nao_aplica"]
    feitos = sum(1 for i in itens if i["situacao"] == "feito")
    return {
        "feitos": feitos,
        "total": len(itens),
        "percentual": round(feitos * 100 / len(itens)) if itens else 0,
    }


@roteador.get("/entrevistas/{entrevista_id}/checklist", dependencies=[SoSecretario])
def checklist(entrevista_id: str) -> dict[str, Any]:
    """A parte do checklist que sai do REGISTRO, sem ida ao modelo.

    Separada da auditoria de propósito. Assinatura, avaliação e documento são fato
    gravado: consultá-los é barato, não erra, e por isso pode carregar junto com a
    tela. Se estivessem na mesma rota da conferência do roteiro, o secretário só
    descobriria que faltou a procuração depois de pagar a leitura da conversa inteira
    — e não descobriria nada com o modelo fora do ar.
    """
    e = armazenamento.obter_entrevista(entrevista_id)
    if e is None:
        raise HTTPException(404, "Entrevista não encontrada.")

    caso_id = str(e.get("caso_id") or "")
    caso = armazenamento.obter_caso(caso_id) if caso_id else None
    assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id) if caso_id else []
    entregas = armazenamento.listar_entregas(caso_id) if caso_id else []

    fases = [
        _fase_avaliacao(e),
        _fase_papelada(caso_id, assinaturas),
        _fase_registro(e, entregas),
    ]

    return {
        "entrevista_id": entrevista_id,
        "entrevistador": e.get("entrevistador") or SEM_NOME,
        "caso": {
            "id": caso_id,
            "cliente": (caso or {}).get("cliente") or "",
            "categoria": (caso or {}).get("categoria") or "",
        },
        "realizada_em": e.get("realizada_em"),
        "criado_em": e.get("criado_em"),
        "avaliacao_google": bool(e.get("avaliacao_google")),
        # Por onde a entrevista entrou. "ao_vivo" foi conduzida pelo roteiro guiado
        # e tem áudio; "anexada" foi um arquivo que alguém subiu ao caso depois. A
        # tela usa isto para oferecer (ou não) o áudio, e para não cobrar da segunda
        # o que só a primeira pode ter.
        "origem": "ao_vivo" if e.get("gravacao_id") else "anexada",
        "gravacao_id": e.get("gravacao_id") or "",
        "fases": fases,
        "progresso": _progresso(fases),
    }


class MarcacaoAvaliacao(BaseModel):
    concluida: bool


@roteador.post("/entrevistas/{entrevista_id}/avaliacao-google", dependencies=[SoSecretario])
def corrigir_avaliacao_google(
    entrevista_id: str, marcacao: MarcacaoAvaliacao
) -> dict[str, Any]:
    """Registra que a avaliação no Google aconteceu, ou desfaz a marcação.

    ONDE ELA DEVERIA SER MARCADA, E POR QUE NÃO É AINDA

    O certo é o atendente marcar no ato, com o cliente ainda na videoconferência —
    é o que a caixa de `AvaliacaoGoogle.tsx` pede, e o que o `FECHAMENTO` do roteiro
    manda. Só que aquela marcação vive em estado de React e não tem onde pousar: o
    atendimento ao vivo não cria linha em `entrevistas` (só o anexo de arquivo cria,
    em `POST /api/casos/{id}/entrevista`), então não existe registro a que prendê-la.

    Enquanto isso não muda, quem grava é o secretário, aqui, conferindo com o
    atendente. É pior que marcar no ato — depende da memória de alguém — e por isso
    a linha do checklist diz "sem marcação", e não "não foi avaliada": a diferença
    entre não ter acontecido e não ter sido registrado é justamente o que esta tela
    não pode confundir.
    """
    if armazenamento.obter_entrevista(entrevista_id) is None:
        raise HTTPException(404, "Entrevista não encontrada.")
    armazenamento.marcar_avaliacao_google(entrevista_id, marcacao.concluida)
    return checklist(entrevista_id)
