"""Entrevistas do caso e gravações temporárias."""

from __future__ import annotations

import threading
import uuid
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import armazenamento, auth
from .. import entrevista as entrevista_lib
from .comum import MAX_BYTES, log
from .registro_documentos import _ler_entrevista_no_agente, _resumir_entrevista_em_fundo

roteador = APIRouter()


# ---------------------------------------------------------------- entrevista
#
# A entrevista é do caso, não do agente: o arquivo do atendimento existe mesmo com a
# integração desligada, e é aqui que ele fica. Assim que o arquivo é guardado, uma
# thread de fundo (`_ler_entrevista_no_agente`) já manda o texto para o agente virar
# fato — a rota `POST /api/agente/casos/{caso_id}/entrevista/{entrevista_id}` em
# `app/agente/rotas.py` continua existindo só para reenvio manual (ex.: agente estava
# fora do ar no momento do envio automático).


@roteador.post("/api/casos/{caso_id}/entrevista", status_code=201)
async def enviar_entrevista(
    request: Request,
    caso_id: str,
    arquivo: UploadFile = File(...),
    realizada_em: str = Form(""),
    entrevistador: str = Form(""),
):
    """Guarda o arquivo da entrevista e o texto lido dele.

    Sem `entrevistador` no formulário, assume QUEM ESTÁ LOGADO. O campo era texto
    livre e ficava vazio: de sete entrevistas gravadas, seis não diziam quem as
    fez, e a única preenchida trazia um nome digitado à mão. Assim não havia como
    responder "quantas cada um fez" — que é justamente o que a supervisão precisa
    (ver `app/supervisao.py`).

    O campo continua aceito, e continua vencendo quando vem preenchido: quem
    digita ali está registrando que OUTRA pessoa conduziu — uma entrevista antiga
    sendo cadastrada depois, por exemplo. Sobrescrever isso com o usuário da
    sessão trocaria um dado certo por um palpite.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, "Arquivo grande demais.")

    nome = Path(arquivo.filename or "entrevista.txt").name
    try:
        texto = entrevista_lib.extrair_texto(nome, conteudo)
    except entrevista_lib.ErroDeLeitura as erro:
        raise HTTPException(400, str(erro)) from erro

    destino = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{uuid.uuid4().hex[:8]}-{nome}"
    caminho.write_bytes(conteudo)

    entrevista = armazenamento.registrar_entrevista(
        caso_id,
        arquivo=nome,
        caminho=caminho,
        texto=texto,
        realizada_em=realizada_em.strip(),
        entrevistador=entrevistador.strip() or _quem_conduziu(request),
        entrevistador_id=_id_de_quem_conduziu(request),
    )

    threading.Thread(
        target=_ler_entrevista_no_agente,
        args=(caso_id, entrevista["id"]),
        name=f"agente-entrevista-{entrevista['id'][:8]}",
        daemon=True,
    ).start()

    # O arquivo é uma entrevista completa: gera o resumo por IA junto, à parte do
    # agente (ver a rota do atendimento ao vivo).
    if texto:
        threading.Thread(
            target=_resumir_entrevista_em_fundo,
            args=(entrevista["id"], texto),
            name=f"resumo-entrevista-{entrevista['id'][:8]}",
            daemon=True,
        ).start()

    return entrevista


def _quem_conduziu(request: Request) -> str:
    """Nome de quem está logado, para atribuir a entrevista.

    Grava o NOME e não o `sub` porque é o que a supervisão mostra na tela e o que
    a coluna `entrevistador` já guardava — trocar para identificador tornaria
    ilegíveis as linhas antigas sem ganhar nada. Com `-SemAuth` volta vazio, que
    é honesto: sem autenticação não há quem atribuir.
    """
    usuario = getattr(request.state, "usuario", None)
    if usuario is None or usuario is auth.USUARIO_ABERTO:
        return ""
    return (usuario.nome or usuario.usuario or "").strip()[:120]


def _id_de_quem_conduziu(request: Request) -> str:
    usuario = getattr(request.state, "usuario", None)
    if usuario is None or usuario is auth.USUARIO_ABERTO:
        return ""
    return str(usuario.id or "").strip()[:160]


class TranscricaoAoVivo(BaseModel):
    """A conversa que o roteiro guiado transcreveu, indo para o caso."""

    #: Id da gravação no serviço de transcrição (porta 8200). É a chave da entrevista.
    gravacao_id: str = Field(min_length=1, max_length=64)
    #: A transcrição BRUTA, como saiu do Whisper — não o relato montado a partir
    #: das respostas. Ver o cabeçalho da rota.
    texto: str = ""
    realizada_em: str = ""
    #: O cliente avaliou o escritório no Google, confirmado na chamada.
    avaliacao_google: bool = False
    #: O atendimento foi ENCERRADO, não apenas salvo no meio do caminho.
    concluida: bool = False


@roteador.put("/api/casos/{caso_id}/entrevista-ao-vivo")
async def gravar_entrevista_ao_vivo(
    request: Request, caso_id: str, dados: TranscricaoAoVivo
):
    """Guarda no caso a entrevista que foi CONDUZIDA pelo roteiro guiado.

    O BURACO QUE ISTO FECHA

    Só existia um jeito de uma entrevista virar linha em `entrevistas`: alguém
    anexar um arquivo ao caso, à mão, depois. O atendimento ao vivo — roteiro,
    escuta, gravação — não gravava nada: a conversa transcrita ficava na aba do
    navegador e morria com ela. Como a supervisão lê essa tabela (ver
    `app/supervisao.py`), o fluxo em que o roteiro é REALMENTE seguido era o único
    que ela não enxergava. Ela media uma amostra e parecia medir o escritório.

    O QUE VAI GRAVADO É A TRANSCRIÇÃO BRUTA, NÃO O RELATO

    A tela tem os dois: o relato montado a partir das respostas e a conversa como
    o Whisper a ouviu. Aqui entra a segunda, e a diferença é a razão de a auditoria
    existir. O roteiro preenchido diz o que a escuta conseguiu extrair; auditá-lo
    mediria o acerto do reconhecimento de voz. A transcrição diz o que foi
    perguntado e respondido — que é a condução, e é ela que está em avaliação (ver
    o cabeçalho de `app/auditoria.py`).

    POR QUE PUT, E CHAMADA MAIS DE UMA VEZ

    O atendimento não termina quando o caso nasce: o caso é criado no meio da
    rolagem, com o cliente ainda na linha, e depois dele vêm a avaliação no Google,
    os documentos e o fechamento lido do roteiro. A tela grava ao criar o caso — para
    não perder tudo se a aba morrer — e de novo ao encerrar, com a conversa
    completa. `gravacao_id` é a chave: a segunda chamada REESCREVE a primeira em vez
    de criar outra entrevista, senão a supervisão contaria em dobro o trabalho de
    quem conduziu.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    texto = dados.texto.strip()
    existente = armazenamento.obter_entrevista_por_gravacao(dados.gravacao_id)

    # Uma gravação pertence a UM caso. Se ela já está noutro, o atendente criou dois
    # casos na mesma conversa — mover a entrevista em silêncio faria o primeiro caso
    # perder a entrevista dele sem ninguém saber.
    if existente and existente.get("caso_id") != caso_id:
        raise HTTPException(
            409,
            "Esta gravação já está registrada em outro caso. "
            "Anexe a entrevista ao caso certo pelo dossiê.",
        )

    destino = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    nome = f"Entrevista guiada {dados.realizada_em or date.today().isoformat()}.txt"

    if existente:
        # O arquivo em disco acompanha o texto: é ele que o dossiê baixa, e um
        # arquivo com a conversa pela metade ao lado de uma transcrição completa
        # seria pior que não ter arquivo.
        Path(existente["caminho"]).write_text(texto, encoding="utf-8")
        armazenamento.atualizar_transcricao(
            existente["id"],
            texto,
            dados.realizada_em or existente.get("realizada_em") or "",
        )
        entrevista = armazenamento.obter_entrevista(existente["id"]) or existente
    else:
        caminho = destino / f"{uuid.uuid4().hex[:8]}-{nome}"
        caminho.write_text(texto, encoding="utf-8")
        entrevista = armazenamento.registrar_entrevista(
            caso_id,
            arquivo=nome,
            caminho=caminho,
            texto=texto,
            realizada_em=dados.realizada_em or date.today().isoformat(),
            entrevistador=_quem_conduziu(request),
            entrevistador_id=_id_de_quem_conduziu(request),
            gravacao_id=dados.gravacao_id,
        )

    # A marcação da avaliação vem de quem estava na chamada, no momento em que ela
    # aconteceu — que é o único momento em que ela significa o que afirma. A
    # supervisão pode corrigi-la depois, mas não é ela quem deveria criá-la.
    armazenamento.marcar_avaliacao_google(entrevista["id"], dados.avaliacao_google)

    # O agente só lê a entrevista ENCERRADA. Mandar a conversa pela metade geraria
    # fatos a partir de um relato que ainda ia mudar, e o dossiê guarda fato, não
    # rascunho. `enviada` evita reenviar quando o atendente volta ao roteiro.
    if dados.concluida and texto and not entrevista.get("enviada"):
        threading.Thread(
            target=_ler_entrevista_no_agente,
            args=(caso_id, entrevista["id"]),
            name=f"agente-entrevista-{entrevista['id'][:8]}",
            daemon=True,
        ).start()

    # O resumo por IA sai no encerramento, à parte do agente: não depende do
    # serviço externo, então acontece mesmo quando o caso não está ligado a ele.
    if dados.concluida and texto:
        threading.Thread(
            target=_resumir_entrevista_em_fundo,
            args=(entrevista["id"], texto),
            name=f"resumo-entrevista-{entrevista['id'][:8]}",
            daemon=True,
        ).start()

    return armazenamento.obter_entrevista(entrevista["id"]) or entrevista


@roteador.get("/api/casos/{caso_id}/entrevistas")
def listar_entrevistas(caso_id: str):
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return {"entrevistas": armazenamento.listar_entrevistas(caso_id)}


@roteador.get("/api/casos/{caso_id}/entrevista/{entrevista_id}")
def obter_entrevista(caso_id: str, entrevista_id: str):
    """A entrevista com o texto inteiro — é o que o advogado abre para reler."""
    return _entrevista_do_caso(caso_id, entrevista_id)


@roteador.get("/api/casos/{caso_id}/entrevista/{entrevista_id}/arquivo")
def baixar_entrevista(caso_id: str, entrevista_id: str):
    """O arquivo original ou, se o volume mudou, a transcrição preservada no banco."""
    registro = _entrevista_do_caso(caso_id, entrevista_id)
    caminho = Path(registro["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() in caminho.parents and caminho.is_file():
        return FileResponse(
            caminho,
            filename=registro["arquivo"],
            media_type="application/octet-stream",
        )

    # Atendimentos criados dentro do container guardavam ``/app/dados/...``. Quando a
    # API roda no host Windows esse caminho não existe, embora a transcrição integral
    # continue na coluna ``texto``. O download não pode depender de onde o volume foi
    # montado: para entrevista textual, o conteúdo preservado é o próprio artefato.
    texto = str(registro.get("texto") or "")
    if not texto.strip():
        raise HTTPException(404, "Arquivo e transcrição da entrevista não encontrados.")
    nome = str(registro.get("arquivo") or f"Entrevista {entrevista_id}.txt")
    if not nome.casefold().endswith(".txt"):
        nome = f"{Path(nome).stem or 'Entrevista'}.txt"
    return Response(
        content=texto.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"},
    )


# O vídeo das entrevistas é persistente: cada pedaço é salvo no banco e fica
# disponível para a supervisão depois que o atendimento termina.
LIMITE_MIDIA_NO_BANCO = 1536 * 1024 * 1024


@roteador.post("/api/gravacoes-temporarias", status_code=201)
async def guardar_gravacao_temporaria(
    arquivo: UploadFile = File(...),
    tipo: str = Form(""),
    entrevista_id: str = Form(""),
    nome: str = Form(""),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > LIMITE_MIDIA_NO_BANCO:
        raise HTTPException(413, "Arquivo grande demais para guardar no banco.")
    try:
        return await run_in_threadpool(
            armazenamento.salvar_gravacao_temporaria,
            tipo=(tipo or "video")[:20],
            entrevista_id=entrevista_id[:64],
            nome_arquivo=(nome or arquivo.filename or "gravacao")[:400],
            mime=(arquivo.content_type or "application/octet-stream")[:100],
            conteudo=conteudo,
            enviado_por=usuario.nome,
        )
    except Exception as exc:
        log.exception("Falha ao guardar gravação temporária no banco")
        raise HTTPException(503, f"Não foi possível guardar a gravação no banco: {exc}") from exc


@roteador.get("/api/gravacoes-temporarias")
def listar_gravacoes_temporarias(_usuario: auth.Usuario = Depends(auth.usuario_atual)):
    return {"gravacoes": armazenamento.listar_gravacoes_temporarias()}


class PedidoTrechoTranscricao(BaseModel):
    entrevista_id: str = Field(min_length=1, max_length=64)
    quando: int = 0
    texto: str = Field(min_length=1, max_length=20000)


@roteador.post("/api/gravacoes-temporarias/pedacos", status_code=201)
async def guardar_pedaco_de_video(
    arquivo: UploadFile = File(...),
    sessao_id: str = Form(...),
    entrevista_id: str = Form(""),
    ordem: int = Form(...),
    nome: str = Form(""),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    sessao = sessao_id.strip()[:64]
    if not sessao or ordem < 0:
        raise HTTPException(400, "Sessão ou ordem inválida.")
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Pedaço vazio.")
    if len(conteudo) > 64 * 1024 * 1024:
        raise HTTPException(413, "Pedaço grande demais.")
    try:
        await run_in_threadpool(
            armazenamento.salvar_pedaco_gravacao,
            sessao_id=sessao,
            entrevista_id=entrevista_id.strip()[:64],
            ordem=ordem,
            nome_arquivo=(nome or arquivo.filename or "Entrevista.webm")[:400],
            mime=(arquivo.content_type or "application/octet-stream")[:100],
            conteudo=conteudo,
            enviado_por=usuario.nome,
        )
    except Exception as exc:
        log.exception("Falha ao guardar pedaço de vídeo no banco")
        raise HTTPException(503, f"Não foi possível guardar o pedaço do vídeo: {exc}") from exc
    return {"sessao_id": sessao, "ordem": ordem, "tamanho": len(conteudo)}


@roteador.get("/api/gravacoes-temporarias/videos")
def listar_videos_em_pedacos(_usuario: auth.Usuario = Depends(auth.usuario_atual)):
    return {"videos": armazenamento.listar_sessoes_gravacao()}


@roteador.get("/api/gravacoes-temporarias/videos/{sessao_id}")
def baixar_video_em_pedacos(sessao_id: str, _usuario: auth.Usuario = Depends(auth.usuario_atual)):
    pedacos = armazenamento.pedacos_da_gravacao(sessao_id)
    if not pedacos:
        raise HTTPException(404, "Vídeo não encontrado.")
    nome = str(pedacos[0]["nome_arquivo"] or "Entrevista.webm")
    return Response(
        content=b"".join(bytes(p["conteudo"]) for p in pedacos),
        media_type=str(pedacos[0]["mime"] or "application/octet-stream").split(";")[0],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"},
    )


@roteador.post("/api/gravacoes-temporarias/trechos", status_code=201)
def guardar_trecho_de_transcricao(
    pedido: PedidoTrechoTranscricao,
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    try:
        armazenamento.salvar_trecho_transcricao(
            entrevista_id=pedido.entrevista_id,
            quando=pedido.quando,
            texto=pedido.texto,
            enviado_por=usuario.nome,
        )
    except Exception as exc:
        log.exception("Falha ao guardar trecho da transcrição no banco")
        raise HTTPException(503, f"Não foi possível guardar o trecho da transcrição: {exc}") from exc
    return {"ok": True}


@roteador.get("/api/gravacoes-temporarias/transcricoes")
def listar_transcricoes_parciais(_usuario: auth.Usuario = Depends(auth.usuario_atual)):
    return {"transcricoes": armazenamento.listar_transcricoes_parciais()}


@roteador.get("/api/gravacoes-temporarias/transcricoes/{entrevista_id}")
def baixar_transcricao_parcial(entrevista_id: str, _usuario: auth.Usuario = Depends(auth.usuario_atual)):
    trechos = armazenamento.trechos_da_transcricao(entrevista_id)
    if not trechos:
        raise HTTPException(404, "Transcrição não encontrada.")
    fuso = timezone(timedelta(hours=-3))
    linhas = [
        f"[{datetime.fromtimestamp(int(t['quando']) / 1000, fuso).strftime('%d/%m/%Y %H:%M:%S')}] {t['texto']}"
        for t in trechos
    ]
    return Response(
        content="\n".join(linhas).encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'Transcricao {entrevista_id}.txt')}"},
    )


@roteador.get("/api/gravacoes-temporarias/{gravacao_id}")
def baixar_gravacao_temporaria(gravacao_id: str, _usuario: auth.Usuario = Depends(auth.usuario_atual)):
    registro = armazenamento.obter_gravacao_temporaria(gravacao_id)
    if not registro:
        raise HTTPException(404, "Gravação não encontrada.")
    return Response(
        content=bytes(registro["conteudo"]),
        media_type=str(registro["mime"] or "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(str(registro['nome_arquivo']))}"},
    )


@roteador.delete("/api/casos/{caso_id}/entrevista/{entrevista_id}")
def excluir_entrevista(caso_id: str, entrevista_id: str):
    """Remove a entrevista do caso. Os fatos que ela gerou continuam no agente."""
    _entrevista_do_caso(caso_id, entrevista_id)
    armazenamento.excluir_entrevista(entrevista_id)
    return {"removido": True}


def _entrevista_do_caso(caso_id: str, entrevista_id: str) -> dict[str, Any]:
    registro = armazenamento.obter_entrevista(entrevista_id)
    if registro is None or registro["caso_id"] != caso_id:
        raise HTTPException(404, "Entrevista não encontrada neste caso.")
    return registro
