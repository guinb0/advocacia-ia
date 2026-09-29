"""Entrada de documentos no caso: gravação, pacote ZIP, lote e leitura da entrevista.

É o caminho comum ao envio da equipe (`documentos`), ao portal do cliente
(`portal`) e à entrevista gravada (`entrevistas_caso`).
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from .. import (
    armazenamento,
    categorias,
    duplicidade,
    fila_sql,
    historico_alteracoes,
)
from .. import entrevista as entrevista_lib
from ..banco import sessao as sessao_banco
from ..tasks.ocr import processar_entrega
from .comum import (
    MAX_BYTES,
    _fila_sql_ocr_ativa,
    _ler_upload,
    log,
)

# O antigo `_ler_documento` (OCR do checklist numa thread da API) saiu daqui: quem
# lê o documento agora é `tasks.ocr.processar_entrega`, no worker que já mantém o
# Paddle aquecido. A ponte com o agente jurídico foi junto — a task chama
# `espelho.enviar_entrega` por conta própria, e não este `_entregar_ao_agente`.


def _ler_entrevista_no_agente(caso_id: str, entrevista_id: str) -> None:
    """Manda a entrevista recém-guardada para o agente virar fato, sem espera humana.

    Roda numa thread de fundo, fora do ciclo da requisição: quem anexou a entrevista
    não precisa mais clicar em "Ler no agente" depois — o fim da entrevista já é o
    gatilho. `espelho.enviar_entrevista` é idempotente (`enviada_em`), então um
    reenvio manual pela tela de sincronização não duplica fato.

    Falha aqui não pode escapar: a entrevista já está salva localmente, e derrubar
    esta thread por indisponibilidade do agente não desfaz esse registro.
    """
    try:
        from ..agente import espelho

        resposta = espelho.enviar_entrevista(caso_id, entrevista_id)
    except Exception:  # noqa: BLE001 - fronteira com serviço externo
        log.warning(
            "não foi possível ler a entrevista %s no agente",
            entrevista_id,
            exc_info=True,
        )
        return

    # A entrevista virou fato. Falta LER o caso inteiro com ela dentro — a
    # classificação e a jurisprudência saem dos fatos do caso, sem distinguir se
    # vieram de documento ou da conversa, e é essa leitura combinada que interessa
    # ao advogado. Ela existia só nos dois botões do dossiê, e no fim de um
    # atendimento ninguém clica: o cliente acabou de sair.
    #
    # Só quando a leitura ACONTECEU agora. `ja_enviada` e `failure` significam que
    # nenhum fato novo entrou, e reclassificar o caso por isso seria gastar duas
    # chamadas de modelo para chegar ao mesmo resultado.
    if resposta.get("ja_enviada") or resposta.get("failure"):
        return
    try:
        espelho.analisar_caso_inteiro(caso_id)
    except Exception:  # noqa: BLE001 - idem; a entrevista já está lida e salva
        log.warning(
            "não foi possível analisar o caso %s após a entrevista",
            caso_id,
            exc_info=True,
        )


def _resumir_entrevista_em_fundo(entrevista_id: str, texto: str) -> None:
    """Gera o resumo da entrevista por IA e o grava, fora do ciclo da requisição.

    Roda numa thread de fundo, como a leitura no agente: quem encerrou o
    atendimento não espera o modelo. É independente do agente jurídico — sai do
    DeepSeek direto. Falhar não desfaz nada: a transcrição bruta já está salva, e
    `entrevista.gerar_resumo` devolve "" em vez de levantar.
    """
    try:
        resumo = entrevista_lib.gerar_resumo(texto)
        if resumo:
            armazenamento.atualizar_resumo_entrevista(entrevista_id, resumo)
    except Exception:  # noqa: BLE001 - enriquecimento, nunca derruba o atendimento
        log.warning("não foi possível resumir a entrevista %s", entrevista_id, exc_info=True)


async def _registrar_documento(
    caso: dict[str, Any],
    item: str | None,
    arquivo: UploadFile,
    idioma: str,
    usar_para_rg_e_cpf: bool,
    lote_id: str | None = None,
    confirmar_duplicidade: bool = False,
    usuario: str | None = None,
) -> dict[str, Any]:
    """OCR + registro da entrega. Compartilhado pelo advogado e pelo portal.

    Arquivo idêntico a outro do caso é recusado antes de qualquer gravação (ver
    `app/duplicidade.py`). `confirmar_duplicidade` só chega da rota da equipe; o
    portal e o envio em lote nunca o passam.

    O cliente passa pelo mesmo caminho de propósito: a validação de tipo, a
    legibilidade e o vínculo RG/CPF não podem depender de quem enviou.

    `item` VAZIO é o envio sem destino — o cliente jogou o arquivo na área de
    envio em massa e não disse que documento é. A entrega nasce em triagem e o
    item sai da leitura, em `roteamento.decidir`. Quando o item vem preenchido,
    ele é um palpite: se o documento o desmentir, a entrega vai para o item certo.
    """
    caso_id = caso["id"]
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item = (item or "").strip() or None
    item_checklist = None
    if item is not None:
        item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
        if item_checklist is None:
            raise HTTPException(
                400, f"Item '{item}' não pertence ao checklist de {categoria.nome}."
            )

    # CPF e RG são itens autônomos. Mantemos o parâmetro apenas para responder
    # claramente a clientes antigos; novos envios não podem quitá-los juntos.
    if usar_para_rg_e_cpf:
        raise HTTPException(
            400,
            "CPF e RG são documentos distintos e devem ser enviados/classificados separadamente.",
        )

    conteudo = await _ler_upload(arquivo)
    nome = arquivo.filename or "sem-nome"

    # DUPLICIDADE ANTES DE GRAVAR QUALQUER COISA
    #
    # Mesmos bytes de outro arquivo do caso é o mesmo documento. Recusar aqui, antes
    # do disco e da fila, evita uma segunda leitura paga e um segundo documento
    # contando no checklist. A mesma consulta pega o arquivo repetido DENTRO de um
    # lote: o primeiro já foi gravado quando o segundo chega.
    repetidos = duplicidade.identicos(caso_id, hashlib.sha256(conteudo).hexdigest())
    if repetidos and not confirmar_duplicidade:
        raise duplicidade.DocumentoDuplicado(
            repetidos, f"{duplicidade.mensagem(repetidos)} Nada foi gravado."
        )

    item_codigo = item or categorias.ITEM_TRIAGEM

    # O arquivo vai para o disco e a entrega é criada antes de entrar na fila.
    # Assim o upload responde sem manter a conexão aberta durante a inferência.
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item_codigo}_{uuid.uuid4()}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    def registrar() -> dict[str, Any]:
        return armazenamento.registrar_entrega_pendente(
            caso_id, item_codigo, nome, caminho, conteudo=conteudo, lote_id=lote_id
        )

    if not repetidos:
        entrega = registrar()
    else:
        # Repetido aceito por decisão de alguém: a entrega e o registro de quem
        # decidiu entram juntos, ou nenhum dos dois.
        with sessao_banco():
            entrega = registrar()
            historico_alteracoes.registrar(
                historico_alteracoes.ENTIDADE_ENTREGA,
                entrega["id"],
                "duplicidade_confirmada",
                usuario=usuario or "escritório",
                depois={"duplicidades": [d.to_dict() for d in repetidos]},
                caso_id=caso_id,
                motivo="Arquivo idêntico enviado com confirmação.",
            )

    # O checklist antes abria uma thread na API e carregava outra cópia do
    # Paddle no primeiro envio (97–200s). O worker OCR já nasce aquecido e é o
    # único dono do modelo; a requisição continua voltando imediatamente.
    try:
        args = (
            entrega["id"], caso_id, str(caminho), nome, item_codigo,
            categoria.codigo, idioma, usar_para_rg_e_cpf,
        )
        task_id = str(uuid.uuid4())
        armazenamento.marcar_entrega_enfileirada(entrega["id"], task_id)
        log.info("event=UPLOAD document_id=%r caso_id=%r arquivo=%r", entrega["id"], caso_id, nome)
        if _fila_sql_ocr_ativa():
            task_id = fila_sql.enfileirar_ocr(args, job_id=task_id)
        else:
            processar_entrega.apply_async(
                args=args, queue="gpu_background", priority=7, task_id=task_id,
            )
    except Exception as exc:
        # Mensagem real: mascarar tudo como "fila indisponível" escondia a causa
        # (ex.: tabela sem qualificar em `_qualificar` → nome de objeto inválido).
        motivo = f"Não foi possível enfileirar a leitura: {type(exc).__name__}: {exc}"
        armazenamento.falhar_entrega(entrega["id"], motivo[:500])
        log.exception("Falha ao enfileirar a entrega %s", entrega["id"])
        raise HTTPException(503, motivo) from exc

    return {"entrega": entrega, "processando": True, "task_id": task_id}


#: Teto de arquivos por envio em massa. Não é limite de tamanho — é para o
#: cliente não despejar a galeria inteira do celular numa requisição só e ficar
#: Teto por request já EXPANDIDO — um ZIP conta pelos arquivos de dentro. A tela
#: parte uma pasta grande em blocos menores (ver `TAMANHO_LOTE_ENVIO`), então
#: aqui o teto existe para o ZIP: casa com `MAX_ITENS_ZIP` para que um pacote de
#: até 200 arquivos entre inteiro, sem nenhum ficar de fora.
MAX_ARQUIVOS_POR_LOTE = int(os.getenv("MAX_ARQUIVOS_POR_LOTE", "200"))


#: Guardas contra ZIP malicioso (zip bomb): teto de itens e de bytes já
#: descomprimidos. Um ZIP acima disto é recusado inteiro, com o motivo.
MAX_ITENS_ZIP = int(os.getenv("MAX_ITENS_ZIP", "200"))


MAX_BYTES_ZIP = int(os.getenv("MAX_BYTES_ZIP_DESCOMPRIMIDO", str(1024 * 1024 * 1024)))


# Um ZIP de documentos nunca precisa carregar binários executáveis. A lista é
# deliberadamente pequena: formatos fora dela recebem uma resposta explícita em
# vez de chegarem ao OCR como bytes sem semântica.
EXTENSOES_DOCUMENTO_ZIP = frozenset({
    ".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt",
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic",
})


MAX_RAZAO_COMPRESSAO_ZIP = float(os.getenv("MAX_RAZAO_COMPRESSAO_ZIP", "100"))


class _ArquivoEmMemoria:
    """Imita o mínimo de `UploadFile` que o registro usa: `filename` e `read()`.

    É o que um arquivo tirado de dentro de um ZIP vira, para seguir pelo MESMO
    caminho de um upload solto — mesma validação, mesmo OCR, mesma triagem.
    """

    def __init__(self, filename: str, conteudo: bytes):
        self.filename = filename
        self._conteudo = conteudo

    async def read(self) -> bytes:
        return self._conteudo


def _e_lixo_de_zip(nome: str) -> bool:
    """Entradas que todo desktop enfia no ZIP e que não são documento."""
    base = nome.rsplit("/", 1)[-1]
    return (
        not base
        or nome.endswith("/")
        or nome.startswith("__MACOSX/")
        or base in {".DS_Store", "Thumbs.db"}
        or base.startswith("._")
    )


def _validar_indice_zip(z: zipfile.ZipFile, nome_zip: str) -> list[zipfile.ZipInfo]:
    """Valida o índice antes de ler qualquer entrada de um ZIP enviado.

    Não extraímos para disco, mas ainda rejeitamos caminhos maliciosos, arquivos
    executáveis, entradas criptografadas e razões de compressão incompatíveis
    com documentos. Assim a mesma regra protege a criação rápida e o lote.
    """
    itens: list[zipfile.ZipInfo] = []
    total = 0
    for info in z.infolist():
        caminho = info.filename.replace("\\", "/")
        partes = [parte for parte in caminho.split("/") if parte]
        if info.is_dir() or _e_lixo_de_zip(caminho):
            continue
        if caminho.startswith("/") or any(parte in {".", ".."} for parte in partes):
            raise HTTPException(400, f"O ZIP '{nome_zip}' contém um caminho inválido.")
        if info.flag_bits & 0x1:
            raise HTTPException(400, f"O ZIP '{nome_zip}' contém arquivo protegido por senha.")
        extensao = Path(caminho).suffix.lower()
        if extensao == ".zip":
            # Não é aberto nem aceito como documento: impede cascatas de ZIP.
            continue
        if extensao not in EXTENSOES_DOCUMENTO_ZIP:
            raise HTTPException(
                400,
                f"O arquivo '{Path(caminho).name}' não é um formato de documento aceito.",
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise HTTPException(400, f"O ZIP '{nome_zip}' possui tamanho inválido.")
        if info.file_size and not info.compress_size:
            raise HTTPException(400, f"O ZIP '{nome_zip}' possui entrada com compressão inválida.")
        if info.compress_size and info.file_size / info.compress_size > MAX_RAZAO_COMPRESSAO_ZIP:
            raise HTTPException(400, f"O ZIP '{nome_zip}' excede a razão máxima de compressão.")
        itens.append(info)
        total += info.file_size
        if len(itens) > MAX_ITENS_ZIP:
            raise HTTPException(400, f"O ZIP '{nome_zip}' tem mais de {MAX_ITENS_ZIP} arquivos. Divida em partes menores.")
        if total > MAX_BYTES_ZIP:
            raise HTTPException(413, f"O conteúdo de '{nome_zip}' passa de {MAX_BYTES_ZIP // (1024 * 1024)}MB descomprimido.")
    return itens


_MARCADORES_DE_ENTREVISTA = (
    "entrevista",
    "transcricao",
    "tactiq",
    "google meet",
    "google-meet",
    "zoom",
    "microsoft teams",
    "microsoft-teams",
    "reuniao com cliente",
    "atendimento cliente",
)


def _arquivo_parece_entrevista(nome: str) -> bool:
    """Reconhece transcrição já pronta dentro de um lote/ZIP.

    Não basta a extensão: um PDF ou DOCX pode ser qualquer prova. O nome precisa
    também trazer um marcador de entrevista, para não tirar um documento do
    checklist por engano. A normalização cobre ``transcrição`` e caminhos internos
    de ZIP como ``Cliente/Entrevista inicial.txt``.
    """
    base = unicodedata.normalize("NFKD", Path(nome).name).encode("ascii", "ignore").decode().casefold()
    extensao = Path(base).suffix
    return extensao in entrevista_lib.EXTENSOES_ENTREVISTA and any(
        marcador in base for marcador in _MARCADORES_DE_ENTREVISTA
    )


async def _registrar_entrevista_do_lote(caso: dict[str, Any], arquivo: Any) -> dict[str, str] | None:
    """Move uma transcrição identificada no lote para a linha do tempo do caso.

    Só a assume como entrevista depois de extrair texto de verdade. Se o arquivo
    estiver corrompido, for uma imagem ou tiver nome enganoso, o fluxo normal de
    documentos continua responsável por guardá-lo e classificá-lo.
    """
    nome = Path(getattr(arquivo, "filename", "") or "entrevista.txt").name
    try:
        conteudo = await arquivo.read()
        if not conteudo or len(conteudo) > MAX_BYTES:
            return None
        texto = entrevista_lib.extrair_texto(nome, conteudo)
    except entrevista_lib.ErroDeLeitura:
        return None

    destino = armazenamento.DIR_ARQUIVOS / caso["id"] / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{uuid.uuid4().hex[:8]}-{nome}"
    caminho.write_bytes(conteudo)
    entrevista = armazenamento.registrar_entrevista(
        caso["id"],
        arquivo=nome,
        caminho=caminho,
        texto=texto,
        entrevistador="Importada com documentos",
    )
    threading.Thread(
        target=_ler_entrevista_no_agente,
        args=(caso["id"], entrevista["id"]),
        name=f"agente-entrevista-{entrevista['id'][:8]}",
        daemon=True,
    ).start()
    if texto:
        threading.Thread(
            target=_resumir_entrevista_em_fundo,
            args=(entrevista["id"], texto),
            name=f"resumo-entrevista-{entrevista['id'][:8]}",
            daemon=True,
        ).start()
    return {"arquivo": nome, "entrevista_id": entrevista["id"], "tipo": "entrevista"}


async def _expandir_zips(arquivos: list[Any]) -> list[Any]:
    """Troca cada `.zip` pelos arquivos que ele contém; deixa os demais intactos.

    Um envio pode misturar arquivos soltos e ZIPs — todos saem daqui como itens
    individuais. Subpasta dentro do ZIP vira parte do nome, para o escritório
    reconhecer de onde veio cada arquivo. ZIP dentro de ZIP não é aberto.
    """
    saida: list[Any] = []
    for arquivo in arquivos:
        nome = getattr(arquivo, "filename", "") or ""
        if not nome.lower().endswith(".zip"):
            saida.append(arquivo)
            continue
        bruto = await arquivo.read()
        try:
            with zipfile.ZipFile(io.BytesIO(bruto)) as z:
                itens = _validar_indice_zip(z, nome)
                if len(itens) > MAX_ITENS_ZIP:
                    raise HTTPException(
                        400,
                        f"O ZIP '{nome}' tem mais de {MAX_ITENS_ZIP} arquivos. "
                        "Divida em partes menores.",
                    )
                if sum(i.file_size for i in itens) > MAX_BYTES_ZIP:
                    raise HTTPException(
                        413,
                        f"O conteúdo de '{nome}' passa de "
                        f"{MAX_BYTES_ZIP // (1024 * 1024)}MB descomprimido.",
                    )
                for info in itens:
                    if info.filename.lower().endswith(".zip"):
                        continue  # ZIP aninhado não é aberto (evita bomba/loop).
                    dados = z.read(info)
                    if dados:
                        saida.append(_ArquivoEmMemoria(info.filename.replace("\\", "/"), dados))
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                400, f"'{nome}' não é um ZIP válido ou está corrompido."
            ) from exc
    return saida


async def _registrar_lote(
    caso: dict[str, Any],
    arquivos: list[UploadFile],
    idioma: str,
) -> dict[str, Any]:
    """Vários documentos de uma vez, cada um achando o próprio item.

    Um arquivo que falha não derruba os outros: o lote devolve o que entrou e o
    que não entrou, com o motivo, porque quem mandou doze fotos precisa saber
    qual das doze precisa repetir. Um ZIP é aberto antes: cada arquivo de dentro
    entra como se tivesse sido enviado solto.
    """
    if not arquivos:
        raise HTTPException(400, "Nenhum arquivo foi enviado.")

    arquivos = await _expandir_zips(arquivos)
    if not arquivos:
        raise HTTPException(400, "O ZIP não tinha nenhum arquivo aproveitável.")
    if len(arquivos) > MAX_ARQUIVOS_POR_LOTE:
        raise HTTPException(
            400,
            f"São aceitos até {MAX_ARQUIVOS_POR_LOTE} arquivos por envio "
            "(contando os de dentro de um ZIP). Divida em partes menores.",
        )

    lote_id = uuid.uuid4().hex
    aceitos: list[dict[str, Any]] = []
    recusados: list[dict[str, str]] = []
    for arquivo in arquivos:
        nome = arquivo.filename or "sem-nome"
        try:
            # ZIP com uma entrevista pronta não é "documento sem destino": entra
            # no mesmo acervo da entrevista feita no sistema, de onde a análise e
            # a geração de peça já sabem consumi-la.
            if _arquivo_parece_entrevista(nome):
                entrevista_importada = await _registrar_entrevista_do_lote(caso, arquivo)
                if entrevista_importada is not None:
                    aceitos.append(entrevista_importada)
                    continue
            registro = await _registrar_documento(
                caso, None, arquivo, idioma, False, lote_id
            )
            aceitos.append({"arquivo": nome, "entrega_id": registro["entrega"]["id"]})
        except HTTPException as exc:
            recusados.append({"arquivo": nome, "motivo": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - um arquivo ruim não perde o lote
            log.exception("falha ao registrar %s no lote %s", nome, lote_id)
            recusados.append({"arquivo": nome, "motivo": str(exc)[:200]})

    if not aceitos:
        raise HTTPException(
            400, recusados[0]["motivo"] if recusados else "Nenhum arquivo aceito."
        )

    return {
        "lote_id": lote_id,
        "recebidos": aceitos,
        "recusados": recusados,
        "processando": True,
    }
