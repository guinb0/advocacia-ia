"""Documentos e entregas do caso: envio, ZIP, reclassificação, downloads e releitura."""

from __future__ import annotations

import io
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    auth,
    casos,
    categorias,
    conversao_pdf,
    duplicidade,
    fila_sql,
    historico_alteracoes,
    pipeline,
    roteamento,
    skill_peticao,
    tipos_documento,
    valor_documento,
)
from ..banco import sessao as sessao_banco
from ..cache_leitura import por_alguns_segundos
from ..tasks.manutencao import _leitor_de_documentos_ativo
from ..tasks.ocr import EXTENSOES_MIDIA, processar_entrega
from .casos import listar_casos
from .comum import (
    _autor_da_acao,
    _criar_portal,
    _fila_sql_ocr_ativa,
    _ler_upload_zip,
    _processar,
    log,
)
from .registro_documentos import (
    _ArquivoEmMemoria,
    _registrar_documento,
    _registrar_lote,
    _validar_indice_zip,
)

roteador = APIRouter()


def _entregar_ao_agente(caso_id: str, entrega_id: str) -> None:
    """Empurra a extração recém-lida para o agente jurídico, se o caso estiver ligado.

    Só para caso **já vinculado**: vincular sozinho criaria caso no agente para toda
    foto que o cliente manda pelo portal, inclusive as de caso que ninguém abriu lá.

    Falha aqui não pode escapar. Já estamos fora da requisição, o documento está
    salvo e lido, e derrubar esta thread por indisponibilidade de outro serviço
    deixaria a entrega marcada como erro de leitura — que não foi o que aconteceu.
    """
    try:
        from ..agente import espelho

        espelho.enviar_entrega(caso_id, entrega_id)
    except Exception:  # noqa: BLE001 - fronteira com serviço externo
        log.warning(
            "não foi possível entregar %s ao agente jurídico", entrega_id, exc_info=True
        )


@roteador.post("/api/casos/{caso_id}/documentos", status_code=201)
async def enviar_documento(
    caso_id: str,
    item: str = Form(""),
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    usar_para_rg_e_cpf: bool = Form(False),
    confirmar_duplicidade: bool = Form(False),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """Recebe um documento, roda o OCR e marca o item do checklist.

    `item` é opcional: sem ele, quem decide o item é a leitura do documento.
    `confirmar_duplicidade` aceita um arquivo idêntico a outro do caso, e a
    confirmação fica no histórico do documento.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await _registrar_documento(
        caso,
        item,
        arquivo,
        idioma,
        usar_para_rg_e_cpf,
        confirmar_duplicidade=confirmar_duplicidade,
        usuario=_autor_da_acao(usuario),
    )


@roteador.post("/api/casos/{caso_id}/documentos/lote", status_code=201)
async def enviar_documentos_em_lote(
    caso_id: str,
    arquivos: list[UploadFile] = File(...),
    idioma: str = Form("pt"),
):
    """Envio em massa: N documentos, sem escolher item para nenhum deles."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await _registrar_lote(caso, arquivos, idioma)


async def _importar_zip_do_caso_em_fundo(
    caso_id: str, caminho_zip: str, nome: str, idioma: str
) -> None:
    """Registra o conteúdo de um ZIP depois de a tela já ter recebido o caso.

    Descompactar e criar até duzentas entregas pode levar bastante tempo em disco
    ou no banco. Não é OCR, mas também não deve segurar a tela de criação.
    """
    caminho = Path(caminho_zip)
    try:
        caso = await run_in_threadpool(armazenamento.obter_caso, caso_id)
        if caso is None:
            return
        conteudo = await run_in_threadpool(caminho.read_bytes)
        await _registrar_lote(caso, [_ArquivoEmMemoria(nome, conteudo)], idioma)
        listar_casos.limpar_cache()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - o caso já existe; registrar o erro é suficiente
        log.exception("Falha ao importar o ZIP do caso %s", caso_id)
    finally:
        caminho.unlink(missing_ok=True)


#: Casos cujo ZIP já foi agendado para importação em fundo — evita reagendar
#: (e reler um arquivo já apagado) quando um retry cai no mesmo caso memoizado
#: por `_criar_caso_por_zip_idempotente`. Guarda só o instante do agendamento
#: para podar entradas mais velhas que a janela de memoização (60s) a cada
#: chamada, em vez de crescer para sempre.
_casos_zip_agendados: dict[str, float] = {}


_trava_casos_zip_agendados = threading.Lock()


@por_alguns_segundos(60, maximo=64)
def _criar_caso_por_zip_idempotente(
    cliente: str, categoria: str, nome: str, conteudo: bytes, skill_juridica_id: str,
    telefone: str = "",
) -> dict[str, Any]:
    """Cria o caso e grava o ZIP em disco — parte síncrona de `criar_caso_por_zip`.

    Memoizada por (cliente, categoria, nome, conteúdo, skill_juridica_id, telefone):
    um duplo clique ou um reload da tela enquanto o upload ainda está "Montando"
    reenvia a mesma requisição, byte a byte, e cairia aqui de novo. Sem isso,
    cada retry criava um caso novo com seu próprio ZIP em disco.
    """
    caso = armazenamento.criar_caso(
        cliente, categoria, telefone=telefone, skill_juridica_id=skill_juridica_id
    )
    pasta = armazenamento.DIR_ARQUIVOS / caso["id"] / "importacoes"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}.zip"
    caminho.write_bytes(conteudo)
    return {"caso": caso, "caminho": str(caminho)}


@roteador.post("/api/casos/importar-zip", status_code=202)
async def criar_caso_por_zip(
    tarefas: BackgroundTasks,
    cliente: str = Form(...),
    categoria: str = Form("em_triagem"),
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    skill_juridica_id: str = Form(""),
    #: O mesmo WhatsApp opcional de `POST /api/casos`: sem ele a cobrança
    #: automática de documentos não tem para quem escrever.
    telefone: str = Form(""),
):
    """Abre um caso e importa uma pasta ZIP de uma vez.

    A pasta é expandida pelo mesmo caminho seguro do envio em lote. Arquivos
    chamados entrevista/transcrição em TXT, MD, DOCX ou PDF são promovidos à
    entrevista do caso; todos os demais entram na triagem para o OCR decidir.
    """
    nome = Path(arquivo.filename or "").name
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    if Path(nome).suffix.lower() != ".zip":
        raise HTTPException(400, "Envie uma pasta compactada no formato .zip.")
    if categorias.obter(categoria) is None:
        categoria = "em_triagem"
    try:
        await run_in_threadpool(skill_peticao.validar_para_caso, skill_juridica_id.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    conteudo = await _ler_upload_zip(arquivo)
    # Confere apenas o índice do ZIP agora. A leitura e o cadastro de cada
    # documento ficam para depois da resposta, para a página não parecer travada.
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            _validar_indice_zip(z, nome)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, f"'{nome}' não é um ZIP válido ou está corrompido.") from exc

    resultado = await run_in_threadpool(
        _criar_caso_por_zip_idempotente,
        cliente.strip(), categoria, nome, conteudo, skill_juridica_id, telefone.strip(),
    )
    caso = resultado["caso"]
    agora = time.monotonic()
    with _trava_casos_zip_agendados:
        for antigo_id, quando in list(_casos_zip_agendados.items()):
            if agora - quando > 60:
                del _casos_zip_agendados[antigo_id]
        ja_agendado = caso["id"] in _casos_zip_agendados
        _casos_zip_agendados[caso["id"]] = agora
    if not ja_agendado:
        tarefas.add_task(
            _importar_zip_do_caso_em_fundo, caso["id"], resultado["caminho"], nome, idioma
        )
        listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return {
        **caso,
        "portal": _criar_portal(caso["id"]),
        "lote": {"processando": True, "mensagem": "Importação do ZIP iniciada."},
    }


def _retrato_da_classificacao(
    entrega: dict[str, Any], categoria: categorias.Categoria | None
) -> dict[str, Any]:
    """Como o documento está classificado — o antes e o depois do histórico."""
    return {
        "itens_atendidos": list(entrega.get("itens_atendidos") or []),
        "item_codigo": entrega.get("item_codigo"),
        "tipo_detectado": entrega.get("tipo_detectado"),
        "tipo_documento": duplicidade.tipo_da_entrega(
            entrega, categoria, tipos_documento.codigos_conhecidos()
        ),
        "roteamento_origem": entrega.get("roteamento_origem"),
    }


def _tipo_para_reclassificacao(
    tipo: str | None, item: categorias.ItemChecklist
) -> tuple[str, str]:
    """Código e nome do tipo que a reclassificação vai gravar.

    Tipo escolhido na tela precisa existir e estar ativo no glossário. Sem escolha,
    vale o tipo que o item de checklist pede. O último recurso — item sem tipo — é
    o comportamento de antes do glossário, para um checklist novo não travar a
    reclassificação enquanto ninguém o vincula.
    """
    codigo = (tipo or "").strip()
    if codigo:
        registro = tipos_documento.obter(codigo)
        if registro is None:
            raise HTTPException(400, f"O tipo “{codigo}” não existe no glossário.")
        if not registro["ativo"]:
            raise HTTPException(
                400, f"O tipo “{registro['nome']}” está desativado no glossário."
            )
        return registro["codigo"], registro["nome"]

    codigo = item.tipo_documento or ""
    if codigo:
        registro = tipos_documento.obter(codigo)
        if registro is not None:
            return codigo, registro["nome"]
        semente = tipos_documento.SEMENTE_POR_CODIGO.get(codigo)
        if semente is not None:
            return codigo, semente.nome
    return item.tipo_ocr or item.codigo, item.nome


@roteador.patch("/api/entregas/{entrega_id}/itens")
def reatribuir_entrega(
    entrega_id: str,
    itens: list[str] = Body(..., embed=True),
    tipo: str | None = Body(None, embed=True),
    confirmar_duplicidade: bool = Body(False, embed=True),
    motivo: str = Body("", embed=True, max_length=600),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """Classifica ou reclassifica um documento já lido: item do checklist e tipo.

    É a palavra final sobre o roteamento automático, e a saída da triagem: o
    advogado olhou o arquivo e disse a que ele responde. Não refaz OCR — o texto
    e os campos já estão gravados, e o arquivo é o mesmo.

    `tipo` é um código do glossário (`app/tipos_documento.py`); sem ele, vale o
    tipo que o item pede. Antes de gravar, o documento é comparado com os demais
    do caso (`app/duplicidade.py`): havendo suspeita, a resposta é 409 com a lista,
    e só `confirmar_duplicidade` conclui. Toda mudança entra no histórico do
    documento, com quem fez, o antes e o depois.

    Lista vazia devolve a entrega para a triagem, que é como se desfaz uma
    atribuição errada sem apagar o documento.
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caso = armazenamento.obter_caso(entrega["caso_id"])
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    escolhidos = list(dict.fromkeys(i.strip() for i in itens if i and i.strip()))
    validos = {i.codigo: i for i in categoria.itens}
    desconhecidos = [i for i in escolhidos if i not in validos]
    if desconhecidos:
        raise HTTPException(
            400,
            f"Item(ns) fora do checklist de {categoria.nome}: {', '.join(desconhecidos)}.",
        )

    quem = _autor_da_acao(usuario)
    antes = _retrato_da_classificacao(entrega, categoria)

    if not escolhidos:
        with sessao_banco():
            devolvida = armazenamento.reatribuir_entrega(
                entrega_id,
                [],
                categorias.ITEM_TRIAGEM,
                roteamento.HUMANO,
                motivo="Devolvido à triagem pelo escritório.",
            )
            historico_alteracoes.registrar(
                historico_alteracoes.ENTIDADE_ENTREGA,
                entrega_id,
                "devolvida_triagem",
                usuario=quem,
                antes=antes,
                depois=_retrato_da_classificacao(devolvida or {}, categoria),
                caso_id=entrega["caso_id"],
                motivo=motivo,
            )
        return devolvida

    item_correto = validos[escolhidos[0]]
    tipo_codigo, tipo_nome = _tipo_para_reclassificacao(tipo, item_correto)

    suspeitas = duplicidade.procurar(
        entrega["caso_id"],
        {
            **entrega,
            "itens_atendidos": escolhidos,
            "roteamento_origem": roteamento.HUMANO,
            "tipo_documento": tipo_codigo,
        },
        categoria,
    )
    if suspeitas and not confirmar_duplicidade:
        raise duplicidade.DocumentoDuplicado(
            suspeitas,
            f"{duplicidade.mensagem(suspeitas)} Confirme para reclassificar mesmo assim.",
        )

    with sessao_banco():
        if len(escolhidos) > 1:
            confere = casos.tipo_confere(item_correto, entrega.get("tipo_detectado"), True)
            corrigida = armazenamento.reatribuir_entrega(
                entrega_id,
                escolhidos,
                escolhidos[0],
                roteamento.HUMANO,
                tipo_confere=confere,
                confianca=100,
                motivo=f"Atribuído por {quem}.",
            )
        else:
            corrigida = armazenamento.corrigir_classificacao_entrega(
                entrega_id,
                item_codigo=item_correto.codigo,
                tipo_correto=tipo_codigo,
                rotulo_correto=tipo_nome,
                categoria=categoria.codigo,
                corrigido_por=quem,
            )
        if corrigida is None:
            raise HTTPException(404, "Entrega não encontrada.")
        depois = _retrato_da_classificacao(corrigida, categoria)
        if suspeitas:
            depois["duplicidades_confirmadas"] = [s.to_dict() for s in suspeitas]
        historico_alteracoes.registrar(
            historico_alteracoes.ENTIDADE_ENTREGA,
            entrega_id,
            "reclassificada",
            usuario=quem,
            antes=antes,
            depois=depois,
            caso_id=entrega["caso_id"],
            motivo=motivo,
        )

    if len(escolhidos) == 1:
        threading.Thread(
            target=_entregar_ao_agente,
            args=(entrega["caso_id"], entrega_id),
            name=f"agente-correcao-{entrega_id[:8]}",
            daemon=True,
        ).start()
    return corrigida


@roteador.post("/api/casos/{caso_id}/documentos/teste", status_code=201)
async def enviar_documento_de_teste(
    caso_id: str, item: str = Form(...), texto: str = Form("")
):
    """Marca um item do checklist como entregue com dados falsos, sem OCR nem arquivo real.

    Existe só para agilizar teste manual e automatizado do dossiê e da ponte com o
    agente: preenche a validação e a extração com um resultado plausível e fixo, sem
    passar pelo PaddleOCR nem exigir que alguém suba um documento de verdade a cada
    rodada. `texto`, opcional, entra como `texto_completo` da extração — é o que o
    agente de documento do outro lado lê para propor fato (`fields`/`text` no prompt);
    sem ele o documento chega "existe, mas está em branco" e nenhum fato nasce dele.
    Desligado por padrão — só responde com `PERMITIR_DADOS_TESTE=true` no
    ambiente, para não virar um jeito de "entregar" documento em produção sem
    documento nenhum.
    """
    if os.getenv("PERMITIR_DADOS_TESTE", "").strip().lower() != "true":
        raise HTTPException(404, "Rota de dados de teste desativada.")

    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
    if item_checklist is None:
        raise HTTPException(
            400, f"Item '{item}' não pertence ao checklist de {categoria.nome}."
        )

    # `None` quando o item não tem classificador (procuração, CAT, laudos...) — como
    # o Paddle de verdade nunca teria opinião sobre esses, inventar um tipo aqui
    # ("documento") mandaria ao agente um valor que ele não reconhece e que o
    # classificador real jamais produziria.
    tipo = item_checklist.tipo_ocr
    nome = f"teste-{item}.pdf"
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{uuid.uuid4()}.pdf"
    caminho.write_bytes(b"%PDF-1.7 dado de teste, sem documento real por tras")

    extracao = {
        "tipo": {"codigo": tipo, "detectado": tipo, "descricao": item_checklist.nome},
        "validacao": {
            "veredito": "APROVADO",
            "dados_utilizaveis": True,
            "score_legibilidade": 100,
        },
        "campos": [],
        "texto_completo": texto,
    }
    tipo_confere = True if tipo else None

    entrega = armazenamento.registrar_entrega(
        caso_id,
        item,
        nome,
        caminho,
        extracao,
        tipo_confere,
        conteudo=caminho.read_bytes(),
    )

    threading.Thread(
        target=_entregar_ao_agente,
        args=(caso_id, entrega["id"]),
        name=f"agente-teste-{entrega['id'][:8]}",
        daemon=True,
    ).start()

    return entrega


@roteador.post("/api/casos/{caso_id}/identidade-unificada")
async def vincular_identidade_unificada(caso_id: str, entrega_id: str = Form(...)):
    """Faz uma entrega de RG/CPF existente valer para os dois itens quando for CIN."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None or entrega["caso_id"] != caso_id:
        raise HTTPException(404, "Entrega não encontrada neste caso.")

    categoria = categorias.obter(caso["categoria"])
    item = (
        next((i for i in categoria.itens if i.codigo == entrega["item_codigo"]), None)
        if categoria
        else None
    )
    if item is None:
        raise HTTPException(
            400, "Esta entrega não pertence a um item de checklist válido."
        )
    try:
        itens_atendidos = casos.itens_para_identidade_unificada(categoria, item)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410, "O anexo antigo não possui cópia recuperável; reenvie o arquivo."
        )
    bruto = caminho.read_bytes()

    # O botão é a confirmação expressa de que se trata de identidade unificada.
    # Reprocessamos no layout da CIN para extrair e validar o CPF sem depender de
    # o classificador conseguir nomear corretamente todas as versões do documento.
    resultado = await _processar(bruto, entrega["arquivo"], "pt", "cin")

    atualizada = armazenamento.atualizar_para_identidade_unificada(
        entrega_id, resultado, itens_atendidos
    )
    if atualizada is None:
        raise HTTPException(404, "Entrega não encontrada.")
    return {"entrega": atualizada, "extracao": resultado}


@roteador.get("/api/entregas/{entrega_id}")
def obter_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    entrega.pop("caminho", None)  # caminho no disco não interessa ao cliente HTTP
    entrega.pop("conteudo", None)
    entrega.pop("conteudo_sha256", None)
    return entrega


@roteador.post("/api/entregas/{entrega_id}/leitura")
async def ler_documento(entrega_id: str):
    """Interpreta o texto que o OCR extraiu: para que este documento serve.

    Existe porque o classificador do OCR conhece documento de IDENTIDADE, e os
    que decidem a ação — CAT, laudo, boletim, CNIS, contracheque — caem em
    "desconhecido" com o texto lido e ninguém para lê-lo (ver
    `app/valor_documento.py`).

    Não decide item do checklist: o status continua vindo do arquivo entregue,
    não de opinião de modelo. O que sai daqui é leitura, rotulada como tal.
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    if not entrega.get("extracao"):
        raise HTTPException(409, "O documento ainda está sendo lido pelo OCR.")

    # Só os itens em aberto: mandar os doze faria o modelo "resolver" o que já
    # foi entregue, e o prompt cresceria sem ganho.
    situacao = casos.montar_situacao(entrega["caso_id"])
    pendencias: list[dict[str, str]] = []
    categoria_nome = ""
    if situacao:
        categoria = situacao.get("categoria") or {}
        categoria_nome = str(
            (categoria.get("nome") if isinstance(categoria, dict) else categoria) or ""
        )
        pendencias = [
            {"codigo": str(i.get("codigo", "")), "nome": str(i.get("nome", ""))}
            for i in situacao.get("itens", [])
            if i.get("status") == "pendente"
        ]

    try:
        return await run_in_threadpool(
            valor_documento.ler, entrega["extracao"], pendencias, categoria_nome
        )
    except valor_documento.ErroValor as exc:
        raise HTTPException(503, str(exc)) from exc


@roteador.get("/api/entregas/{entrega_id}/arquivo")
def baixar_arquivo_entrega(entrega_id: str, download: bool = False):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410,
            "O registro existe, mas este anexo antigo não possui cópia recuperável. Reenvie o arquivo.",
        )

    # `inline` deixa o navegador exibir o arquivo em vez de baixá-lo, que é o que
    # permite a pré-visualização no checklist. Passar só `filename=` produzia
    # `Content-Disposition: attachment` e obrigava a baixar para ver o que chegou.
    # Com `?download=1` o comportamento antigo continua disponível.
    return FileResponse(
        caminho,
        filename=entrega["arquivo"],
        content_disposition_type="attachment" if download else "inline",
    )


@roteador.get("/api/entregas/{entrega_id}/arquivo.pdf")
def baixar_arquivo_entrega_pdf(entrega_id: str):
    """Preserva PDF original; converte imagem e .docx.

    Não serve só ao download: o visor do checklist pede este PDF para mostrar um
    .docx na tela — o navegador não desenha Word, e sem isto o documento só
    podia ser baixado."""
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410,
            "O registro existe, mas este anexo antigo não possui cópia recuperável. Reenvie o arquivo.",
        )

    destino = pipeline.TMP_DIR / f"entrega-{entrega_id}-{uuid.uuid4().hex}.pdf"
    try:
        pdf = conversao_pdf.converter_para_pdf(caminho, entrega["arquivo"], destino)
    except conversao_pdf.ErroConversaoPdf as exc:
        destino.unlink(missing_ok=True)
        raise HTTPException(415, str(exc)) from exc

    return FileResponse(
        pdf.caminho,
        media_type="application/pdf",
        filename=pdf.nome_download,
        background=BackgroundTask(pdf.caminho.unlink, missing_ok=True)
        if pdf.temporario
        else None,
    )


@roteador.get("/api/casos/{caso_id}/documentos.zip")
def baixar_documentos_do_caso(caso_id: str):
    """Tudo que o cliente enviou, num pacote só.

    Trinta documentos eram trinta cliques no checklist, um por linha, e a
    certeza de esquecer um. O pacote sai na ordem do checklist, com o nome do
    item em cada arquivo — do outro lado alguém confere contra a mesma lista.

    O ZIP é montado a cada pedido, e não guardado: documento novo entra no
    pacote seguinte sem ninguém precisar invalidar cache. Ele nasce em
    `pipeline.TMP_DIR`, que já é a pasta dos temporários, e é apagado assim que
    a resposta termina — arquivo de cliente não fica sobrando em disco.
    """
    destino = pipeline.TMP_DIR / f"documentos-{caso_id}-{uuid.uuid4().hex}.zip"
    resumo = casos.montar_zip(caso_id, destino)
    if resumo is None:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Caso não encontrado.")

    if resumo["arquivos"] == 0:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Este caso ainda não tem documentos enviados.")

    nome = re.sub(r"[^\w\- ]", "", resumo["cliente"]).strip() or caso_id[:8]
    return FileResponse(
        destino,
        media_type="application/zip",
        filename=f"Documentos - {nome}.zip",
        # Sem isto o .zip fica em disco até alguém limpar a pasta, e é papelada
        # de cliente. O `BackgroundTask` roda depois do último byte enviado.
        background=BackgroundTask(destino.unlink, missing_ok=True),
        headers={
            # O que NÃO entrou, para a tela poder avisar em vez de deixar o
            # atendente descobrir na hora de protocolar.
            "X-Arquivos": str(resumo["arquivos"]),
            "X-Faltando": str(len(resumo["faltando"])),
        },
    )


@roteador.get("/api/entregas/{entrega_id}/historico")
def historico_da_entrega(entrega_id: str):
    """Reclassificações, devoluções à triagem, repetidos aceitos e remoção."""
    return {
        "eventos": historico_alteracoes.listar(
            historico_alteracoes.ENTIDADE_ENTREGA, entrega_id
        )
    }


#: Tetos da seleção por classificação (rotas POST abaixo, ZIP e PDF). A
#: quantidade casa com o teto de itens de um ZIP recebido; o tamanho reusa o
#: mesmo número de bytes, porque documento é PDF/foto já comprimido e a soma
#: dos arquivos é ~o tamanho do pacote. Acima disto a rota recusa com 413 —
#: gerar assíncrono fica para depois.
MAX_ITENS_ZIP_SELECAO = int(os.getenv("MAX_ITENS_ZIP_SELECAO", "50"))


MAX_BYTES_ZIP_SELECAO = int(
    os.getenv("MAX_BYTES_ZIP_SELECAO", str(200 * 1024 * 1024))
)


#: Teto de páginas do PDF combinado (soma de vários documentos já aceitos no
#: caso). `pdf.pdf_para_imagem`, que roda o OCR por ARQUIVO enviado, não tem
#: teto de páginas — só de pixels renderizados (`pdf.MAX_PIXELS_RENDERIZADOS`).
MAX_PAGINAS_PDF_SELECAO = int(os.getenv("MAX_PAGINAS_PDF_SELECAO", "300"))


class PedidoSelecaoDocumentos(BaseModel):
    """Documentos marcados dentro de UMA classificação, para baixar juntos —
    em ZIP (`POST .../documentos.zip`) ou combinados num PDF só
    (`POST .../documentos.pdf`). O corpo é o mesmo nos dois formatos."""

    #: Código do item do checklist (a "classificação"), como vem em
    #: `GET /api/casos/{id}` → `itens[].codigo`.
    classificacao: str = Field(min_length=1, max_length=60)
    #: Ids das entregas marcadas. O teto alto aqui é só contra payload abusivo;
    #: o limite real, com mensagem amigável, é `MAX_ITENS_ZIP_SELECAO`.
    entregas: list[str] = Field(min_length=1, max_length=1000)


@roteador.post("/api/casos/{caso_id}/documentos.zip")
def baixar_selecao_de_documentos(
    caso_id: str,
    pedido: PedidoSelecaoDocumentos,
    _usuario: auth.Usuario = Depends(auth.exigir_modulo("casos")),
):
    """Um ZIP só com os documentos marcados dentro de UMA classificação.

    O GET desta mesma rota leva o caso inteiro. Aqui o atendente escolhe a
    classificação, marca alguns arquivos dela e leva só esses — cada arquivo sai
    prefixado pelo nome da classificação, para o outro lado conferir contra a
    mesma lista.

    Recusa o pedido inteiro se algum id não for daquela classificação (ou for de
    outro caso): nada de outra classificação entra por engano. O pacote nasce em
    `pipeline.TMP_DIR` e é apagado assim que a resposta termina.
    """
    destino = pipeline.TMP_DIR / f"selecao-{caso_id}-{uuid.uuid4().hex}.zip"
    try:
        resumo = casos.montar_zip_selecao(
            caso_id,
            pedido.classificacao,
            pedido.entregas,
            destino,
            limite_itens=MAX_ITENS_ZIP_SELECAO,
            limite_bytes=MAX_BYTES_ZIP_SELECAO,
        )
    except casos.SelecaoInvalida as exc:
        destino.unlink(missing_ok=True)
        raise HTTPException(exc.status, str(exc)) from exc

    if resumo is None:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Caso não encontrado.")

    if resumo["arquivos"] == 0:
        destino.unlink(missing_ok=True)
        raise HTTPException(
            404, "Nenhum dos documentos selecionados está disponível para download."
        )

    cliente = re.sub(r"[^\w\- ]", "", resumo["cliente"]).strip() or caso_id[:8]
    classificacao = (
        re.sub(r"[^\w\- ]", "", resumo["classificacao"]).strip() or "documentos"
    )
    return FileResponse(
        destino,
        media_type="application/zip",
        filename=f"Documentos - {cliente} - {classificacao}.zip",
        background=BackgroundTask(destino.unlink, missing_ok=True),
        headers={
            "X-Arquivos": str(resumo["arquivos"]),
            "X-Faltando": str(len(resumo["faltando"])),
        },
    )


@roteador.post("/api/casos/{caso_id}/documentos.pdf")
def baixar_selecao_de_documentos_em_pdf(
    caso_id: str,
    pedido: PedidoSelecaoDocumentos,
    _usuario: auth.Usuario = Depends(auth.exigir_modulo("casos")),
):
    """Os documentos marcados dentro de UMA classificação, juntos num PDF só.

    Irmã de `baixar_selecao_de_documentos`: mesma seleção, mesmas guardas —
    quantidade, classificação, permissão. A diferença é o formato de saída: em
    vez de um ZIP com N arquivos, um único PDF com as páginas de todos, na
    ordem em que foram marcados. PDF original entra intacto; imagem vira
    página, como no botão "baixar como PDF" de uma entrega avulsa.

    Recusa com 415 se algum arquivo não for PDF nem imagem, ou se a soma de
    páginas passar do teto — para esses casos o ZIP continua existindo.
    """
    destino = pipeline.TMP_DIR / f"selecao-{caso_id}-{uuid.uuid4().hex}.pdf"
    try:
        resumo = casos.montar_pdf_selecao(
            caso_id,
            pedido.classificacao,
            pedido.entregas,
            destino,
            limite_itens=MAX_ITENS_ZIP_SELECAO,
            limite_bytes=MAX_BYTES_ZIP_SELECAO,
            limite_paginas=MAX_PAGINAS_PDF_SELECAO,
        )
    except casos.SelecaoInvalida as exc:
        destino.unlink(missing_ok=True)
        raise HTTPException(exc.status, str(exc)) from exc

    if resumo is None:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Caso não encontrado.")

    if resumo["paginas"] == 0:
        destino.unlink(missing_ok=True)
        raise HTTPException(
            404, "Nenhum dos documentos selecionados está disponível para download."
        )

    cliente = re.sub(r"[^\w\- ]", "", resumo["cliente"]).strip() or caso_id[:8]
    classificacao = (
        re.sub(r"[^\w\- ]", "", resumo["classificacao"]).strip() or "documentos"
    )
    return FileResponse(
        destino,
        media_type="application/pdf",
        filename=f"Documentos - {cliente} - {classificacao}.pdf",
        background=BackgroundTask(destino.unlink, missing_ok=True),
        headers={
            "X-Arquivos": str(resumo["arquivos"]),
            "X-Paginas": str(resumo["paginas"]),
            "X-Faltando": str(len(resumo["faltando"])),
        },
    )


class _JaEmLeitura(Exception):
    """A entrega já está sendo processada por um worker agora."""


def _reenfileirar_leitura(
    entrega_id: str,
    caso_id: str,
    categoria: categorias.Categoria,
    item_codigo: str,
    arquivo: str,
    itens_atendidos: list[str],
    usuario: str,
    em_leitura: set[str],
    *,
    worker_ativo: bool,
    tarefas_locais: BackgroundTasks,
):
    """O miolo de "tentar novamente": restaura o arquivo e manda de volta pro OCR.

    Usado tanto pelo botão de UM documento quanto pelo de TODOS os documentos
    com erro de um caso — a lógica de reenfileirar é a mesma, só muda quem
    decide a lista de entregas. Levanta `RuntimeError` quando o arquivo já não
    existe (nem disco, nem banco) e `_JaEmLeitura` quando um worker já está com
    esta entrega em mãos — mandar de novo criaria DUAS tarefas correndo para o
    mesmo documento, e a que terminar por último vence calada, sem erro nenhum
    visível. `em_leitura` vem pronto do chamador para não repetir o `inspect`
    do broker a cada entrega, num lote com várias.

    Três níveis, na ordem: a fila SQL durável (`_fila_sql_ocr_ativa`, a
    migração para fora do Celery) quando estiver ligada; senão, com worker
    Celery ativo (`worker_ativo`, de `_leitor_de_documentos_ativo`), manda pra
    `gpu_background`; sem os dois, a PRÓPRIA API processa o documento
    (`processar_entrega.apply`, execução local, sem broker) numa tarefa de
    background do FastAPI — mais lento, mas não depende de ninguém reiniciar
    container nenhum.
    """
    if entrega_id in em_leitura:
        raise _JaEmLeitura("Esta entrega já está sendo lida agora por um worker.")

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise RuntimeError(
            "O arquivo enviado não está mais no servidor. Peça o reenvio do documento."
        )

    with sessao_banco():
        armazenamento.marcar_entrega_processando(entrega_id)
        historico_alteracoes.registrar(
            historico_alteracoes.ENTIDADE_ENTREGA,
            entrega_id,
            "reprocessamento_manual",
            usuario=usuario,
            caso_id=caso_id,
        )

    args = (
        entrega_id,
        caso_id,
        str(caminho),
        arquivo,
        item_codigo,
        categoria.codigo,
        "pt",
        len(itens_atendidos) > 1,
    )
    if _fila_sql_ocr_ativa():
        task_id = str(uuid.uuid4())
        armazenamento.marcar_entrega_enfileirada(entrega_id, task_id)
        fila_sql.enfileirar_ocr(args, job_id=task_id)
        return task_id
    if worker_ativo:
        return processar_entrega.apply_async(args=args, queue="gpu_background", priority=7)

    tarefas_locais.add_task(processar_entrega.apply, args=args)
    return None


def midia_sem_transcricao(entrega: dict[str, Any]) -> bool:
    """Áudio ou vídeo parado, sem texto: a transcrição falhou ou o envio é de antes
    de o formato ser aceito. Não é "erro", mas pedir de novo é o único jeito de ter o relato."""
    if Path(entrega.get("arquivo") or "").suffix.lower() not in EXTENSOES_MIDIA:
        return False
    if entrega.get("status_proc") in {"na_fila", "processando"}:
        return False
    extracao = entrega.get("extracao") or {}
    texto = extracao.get("texto_completo") or "".join(
        str(linha.get("texto") or "") for linha in extracao.get("texto_linhas") or [] if isinstance(linha, dict)
    )
    return not texto.strip()


@roteador.post("/api/entregas/{entrega_id}/tentar-novamente")
def tentar_novamente_entrega(
    entrega_id: str,
    tarefas: BackgroundTasks,
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """Reenfileira a leitura de um documento que falhou, sem reenviar o arquivo.

    `falhar_entrega` nunca apaga o binário — ele continua em disco ou no SQL
    Server (`caminho_duravel_da_entrega` restaura dos dois) — mas até aqui não
    havia como pedir uma nova leitura sem excluir a entrega e reenviar o mesmo
    arquivo. Um 402/429 na hora errada (crédito ou quota esgotados do lado do
    provedor de OCR) deixava o documento órfão na triagem por falta de botão,
    não por falta de arquivo.
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    if entrega.get("status_proc") != "erro" and not midia_sem_transcricao(entrega):
        raise HTTPException(409, "Esta entrega não está com falha de leitura.")

    caso = armazenamento.obter_caso(entrega["caso_id"])
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    worker_ativo, em_leitura = _leitor_de_documentos_ativo()
    try:
        tarefa = _reenfileirar_leitura(
            entrega_id,
            entrega["caso_id"],
            categoria,
            entrega["item_codigo"],
            entrega["arquivo"],
            entrega.get("itens_atendidos") or [],
            _autor_da_acao(usuario),
            em_leitura,
            worker_ativo=worker_ativo,
            tarefas_locais=tarefas,
        )
    except _JaEmLeitura as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        motivo = f"Não foi possível reenfileirar a leitura: {type(exc).__name__}: {exc}"
        armazenamento.falhar_entrega(entrega_id, motivo[:500])
        raise HTTPException(503, motivo) from exc

    return {
        "entrega": armazenamento.obter_entrega(entrega_id),
        "processando": True,
        "task_id": tarefa.id if hasattr(tarefa, "id") else tarefa,
    }


@roteador.post("/api/casos/{caso_id}/tentar-novamente")
def tentar_novamente_caso(
    caso_id: str,
    tarefas: BackgroundTasks,
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """Reprocessa de novo TODO documento com falha OU parado na triagem, de uma vez.

    Dois problemas diferentes levam ao mesmo lugar (a tela do caso cheia de
    "outros documentos"): (1) falha real de leitura (`status_proc = 'erro'`) e
    (2) leitura que funcionou mas não bateu com nenhum item do checklist —
    documento fica "Identificado" só sem categoria certeira. O primeiro é
    resolvido só repetindo; o segundo pode ter sido corrigido desde então (item
    novo no checklist, categoria do caso ajustada) e merece uma segunda chance
    de rotear — por isso reprocessa os DOIS, não só o que está em erro.

    Documento que já está no checklist (não em triagem, sem erro) não é
    tocado; um que falhar ao reenfileirar entra em `falharam` sem travar os
    demais. Usa a fila SQL durável quando ligada, senão worker Celery ativo,
    senão cada entrega processa localmente, uma de cada vez, em segundo plano
    na própria API (ver `_reenfileirar_leitura`).
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    com_erro = [
        e for e in armazenamento.listar_entregas(caso_id)
        if e.get("status_proc") == "erro" or e.get("item_codigo") == categorias.ITEM_TRIAGEM
    ]
    quem = _autor_da_acao(usuario)
    worker_ativo, em_leitura = _leitor_de_documentos_ativo()
    falharam: list[dict[str, str]] = []
    reenfileiradas = 0
    for entrega in com_erro:
        try:
            _reenfileirar_leitura(
                entrega["id"],
                caso_id,
                categoria,
                entrega["item_codigo"],
                entrega["arquivo"],
                entrega.get("itens_atendidos") or [],
                quem,
                em_leitura,
                worker_ativo=worker_ativo,
                tarefas_locais=tarefas,
            )
            reenfileiradas += 1
        except _JaEmLeitura:
            continue  # já sendo lida agora (ex.: retry automático em andamento) — nada a fazer
        except Exception as exc:
            falharam.append({"entrega_id": entrega["id"], "arquivo": entrega["arquivo"], "motivo": str(exc)[:200]})

    return {"reenfileiradas": reenfileiradas, "falharam": falharam}


@roteador.delete("/api/entregas/{entrega_id}")
def excluir_entrega(
    entrega_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)
):
    """Remove o documento e deixa no histórico o que ele era e quem o removeu.

    Remover é o desfecho natural de uma duplicidade confirmada como repetição, e é
    justamente o caso em que alguém pergunta depois "o que havia aqui".
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    caso = armazenamento.obter_caso(entrega["caso_id"])
    categoria = categorias.obter(caso["categoria"]) if caso else None
    antes = {"arquivo": entrega.get("arquivo"), **_retrato_da_classificacao(entrega, categoria)}

    with sessao_banco():
        if not armazenamento.excluir_entrega(entrega_id):
            raise HTTPException(404, "Entrega não encontrada.")
        historico_alteracoes.registrar(
            historico_alteracoes.ENTIDADE_ENTREGA,
            entrega_id,
            "removida",
            usuario=_autor_da_acao(usuario),
            antes=antes,
            caso_id=entrega["caso_id"],
        )
    return {"removido": True}
