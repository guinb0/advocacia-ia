from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging

from celery.signals import worker_ready

from .. import (
    armazenamento,
    casos,
    categorias,
    indexacao_documento,
    jobs,
    pipeline,
    roteamento,
)
from ..celery_app import celery_app

log = logging.getLogger("ocr-worker")


def _executar_ocr(caminho: str, nome: str, idioma: str, tipo: str | None) -> dict:
    conteudo = Path(caminho).read_bytes()
    return pipeline.processar(conteudo, nome, idioma, tipo)


def _ler_anexo(entrega_id: str, caminho: str) -> bytes:
    """O binário do documento, venha ele do disco ou do banco.

    QUEM GRAVA E QUEM LÊ PODEM NÃO SER A MESMA MÁQUINA.

    O caminho que chega aqui foi escrito pela API, no disco DELA. Na estação de
    trabalho isso é o mesmo disco e ninguém nota. Em container — e em qualquer
    worker rodando fora da máquina da API, que é o modo de escalar descrito em
    `docs/CELERY.md` — o caminho pode simplesmente não existir deste lado.

    Ler direto do caminho transformava isso em `FileNotFoundError`, que a task
    reconhece como `OSError` e tenta de novo três vezes antes de desistir: quatro
    leituras condenadas a falhar por um arquivo que está inteiro no SQL Server,
    em `entregas.conteudo`. `caminho_duravel_da_entrega` restaura a cópia local a
    partir dele, conferindo o checksum antes de servir.
    """
    arquivo = Path(caminho)
    if arquivo.is_file():
        return arquivo.read_bytes()

    restaurado = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if restaurado is None:
        # De propósito NÃO é um `OSError`: `autoretry_for` o repetiria três vezes,
        # e nada disto melhora com o tempo — ou o binário está no banco, ou não
        # está. Falhar na hora põe o pedido de reenvio na tela do advogado agora.
        raise RuntimeError(
            "O arquivo enviado não está no disco deste leitor nem tem cópia íntegra "
            "no banco. Peça o reenvio do documento."
        )
    log.info("anexo da entrega %s restaurado do banco para %s", entrega_id, restaurado)
    return restaurado.read_bytes()


def _entregar_ao_agente(caso_id: str, entrega_id: str) -> None:
    """Enfileira a integracao sem manter o worker pesado esperando HTTP."""
    try:
        from .agente import enviar_entrega_ao_agente

        enviar_entrega_ao_agente.apply_async(
            args=(caso_id, entrega_id),
            queue="default",
            priority=6,
        )
    except Exception:
        # O documento ja esta persistido e continua pendente no vinculo. Abrir o dossie
        # ainda executa a sincronizacao idempotente; perder a notificacao nunca perde OCR.
        log.warning(
            "nao foi possivel enfileirar a entrega %s ao agente juridico",
            entrega_id,
            exc_info=True,
        )


@worker_ready.connect
def aquecer_worker_ocr(sender=None, **_kwargs):
    """Carrega o modelo no worker, sem prender o boot numa inferência completa."""
    hostname = str(getattr(sender, "hostname", ""))
    if not hostname.lower().startswith("ocr@"):
        return
    try:
        from ..ocr_engine import aquecer

        aquecer()
        log.info("Mistral OCR configurada no worker %s.", hostname)
    except Exception:
        # O primeiro job tenta novamente; worker vivo é melhor que abortar toda
        # a fila por uma falha transitória de modelo no boot.
        log.exception("Falha ao configurar Mistral OCR no worker %s.", hostname)


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_documento",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def processar_documento(self, job_id: str, caminho: str, nome: str, idioma: str, tipo: str | None):
    inicio = datetime.now(timezone.utc)
    jobs.atualizar(job_id, status="STARTED", progresso=5, iniciado_em=inicio)
    try:
        jobs.atualizar(job_id, status="PROCESSING", progresso=15)
        jobs.atualizar(job_id, progresso=30)
        resultado = _executar_ocr(caminho, nome, idioma, tipo)
        jobs.atualizar(
            job_id,
            status="COMPLETED",
            progresso=100,
            resultado=resultado,
            finalizado_em=datetime.now(timezone.utc),
        )
        Path(caminho).unlink(missing_ok=True)
        return resultado
    except Exception as exc:
        # Se houver retry, a próxima execução volta o estado para STARTED.
        jobs.atualizar(job_id, status="FAILED", erro=str(exc), finalizado_em=datetime.now(timezone.utc))
        raise


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_entrega",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def processar_entrega(
    self,
    entrega_id: str,
    caso_id: str,
    caminho: str,
    nome: str,
    item_codigo: str,
    categoria_codigo: str,
    idioma: str,
    usar_para_rg_e_cpf: bool,
):
    """Lê documento do checklist no worker dedicado ao OCR."""
    try:
        armazenamento.marcar_entrega_processando(entrega_id)
        categoria = categorias.obter(categoria_codigo)
        if categoria is None:
            raise ValueError(f"Categoria {categoria_codigo!r} não existe mais.")

        # `ITEM_TRIAGEM` é o envio sem destino — o cliente mandou o arquivo e não
        # disse (ou não soube dizer) que documento é. Aqui isso não é erro: quem
        # decide o item é `roteamento.decidir`, depois de ler.
        em_triagem = item_codigo == categorias.ITEM_TRIAGEM
        item = None if em_triagem else next(
            (i for i in categoria.itens if i.codigo == item_codigo), None
        )
        if item is None and not em_triagem:
            raise ValueError(f"Item {item_codigo!r} não pertence ao checklist.")

        conteudo = _ler_anexo(entrega_id, caminho)
        if item is None:
            # Sem item não há tipo a forçar: o classificador decide sozinho, e a
            # extração de campos já sai pelo tipo que ele detectou.
            tipo_extracao = None
        else:
            tipo_extracao = (
                "cin" if usar_para_rg_e_cpf and item.tipo_ocr in {"rg", "cpf"}
                else item.tipo_ocr
            )
        # O checklist persiste o JSON no banco e conserva o original em `dados`.
        # Gravar ainda outro JSON e XML em `tmp` era I/O sem consumidor.
        extensao = Path(nome).suffix.lower()
        formato_lido = extensao in pipeline.EXTENSOES_OCR
        if formato_lido:
            resultado = pipeline.processar(
                conteudo,
                nome,
                idioma,
                tipo_extracao,
                gerar_arquivos_temporarios=False,
            )
        else:
            # Receber não é o mesmo que conseguir aplicar OCR. Word, planilha,
            # áudio, vídeo, ZIP e qualquer formato futuro ficam preservados no
            # caso. Um envio associado a um item permanece nesse item para
            # conferência; no envio em massa, fica na triagem para uma pessoa.
            rotulo = extensao or "sem extensão"
            resultado = {
                "arquivo": nome,
                "tipo": {
                    "codigo": "desconhecido",
                    "detectado": "desconhecido",
                    "descricao": "Formato preservado sem OCR",
                    "descricao_detectado": "Formato preservado sem OCR",
                    "confianca_classificacao": 0,
                },
                "campos": [],
                "validacao": {
                    "veredito": "NAO_ANALISADO",
                    "dados_utilizaveis": False,
                    "texto_utilizavel": False,
                    "score_legibilidade": None,
                    "erros": [f"O formato {rotulo} foi recebido, mas não possui leitura OCR automática."],
                },
            }

        # A QUE ITEM ESTE ARQUIVO RESPONDE
        #
        # A escolha de quem enviou é um palpite; o documento é que decide (ver
        # `app/roteamento.py`). Quando o roteamento consulta o modelo, a leitura
        # que ele devolve é a MESMA classificação semântica que esta task
        # gravava por conta própria — reaproveitá-la evita a segunda chamada.
        destino = roteamento.decidir(resultado, categoria, item)
        if not formato_lido:
            motivo_formato = (
                f"Arquivo {extensao or 'sem extensão'} preservado sem leitura OCR automática."
            )
            destino = roteamento.Destino(
                [item.codigo] if item is not None else [],
                roteamento.ESCOLHA if item is not None else roteamento.TRIAGEM,
                30 if item is not None else 0,
                motivo_formato,
            )
        if destino.analise:
            semantica = {
                **destino.analise,
                "classificador": "deepseek",
                "tipo_semantico": str(destino.analise.get("documento") or "indefinido"),
            }
            resultado["classificacao_semantica"] = semantica
            indexacao_documento.aplicar_interpretacao(resultado, semantica)
        elif formato_lido and resultado.get("validacao", {}).get("texto_utilizavel"):
            # O roteamento determinístico já decidiu o item, mas a interpretação
            # da main ainda agrega achados semânticos úteis ao documento. Ela não
            # muda o destino escolhido acima.
            try:
                documentos_esperados = [
                    {"codigo": esperado.codigo, "nome": esperado.nome}
                    for esperado in categoria.itens
                ]
                semantica = indexacao_documento.classificar(
                    resultado, categoria.nome, documentos_esperados
                )
                resultado["classificacao_semantica"] = semantica
                indexacao_documento.aplicar_interpretacao(resultado, semantica)
            except Exception as exc:
                log.warning("classificação semântica falhou para %s: %s", entrega_id, exc)
                resultado["classificacao_semantica"] = {
                    "status": "indisponivel",
                    "erro": str(exc)[:200],
                }

        # A identidade unificada marcada à mão continua valendo sobre tudo: quem
        # marcou olhou o documento, e nenhum classificador desmente isso.
        if usar_para_rg_e_cpf and item is not None:
            try:
                itens_atendidos = casos.itens_para_identidade_unificada(categoria, item)
                destino = roteamento.Destino(
                    itens_atendidos,
                    roteamento.ESCOLHA,
                    100,
                    "Identidade unificada confirmada no envio.",
                    destino.analise,
                )
            except ValueError:
                pass

        itens_atendidos = list(destino.itens)
        item_destino = next(
            (i for i in categoria.itens if itens_atendidos and i.codigo == itens_atendidos[0]),
            None,
        )
        detectado = resultado.get("tipo", {}).get("detectado")
        confere = (
            casos.tipo_confere(item_destino, detectado, len(itens_atendidos) > 1)
            if item_destino is not None
            else None
        )
        armazenamento.concluir_entrega(
            entrega_id,
            resultado,
            confere,
            itens_atendidos,
            item_codigo=itens_atendidos[0] if itens_atendidos else categorias.ITEM_TRIAGEM,
            origem=destino.origem,
            confianca=destino.confianca,
            motivo=destino.motivo,
        )
        if destino.em_triagem:
            log.info("entrega %s ficou em triagem: %s", entrega_id, destino.motivo)
        if resultado.get("classificacao_semantica", {}).get("tipo_semantico"):
            try:
                indexacao_documento.indexar(entrega_id, caso_id, nome, resultado)
            except Exception:
                # Upload e OCR já estão persistidos; indisponibilidade de OpenRouter
                # ou PGVector não pode transformar uma entrega válida em erro.
                log.warning("indexação vetorial falhou para %s", entrega_id, exc_info=True)
        _entregar_ao_agente(caso_id, entrega_id)
        return {"entrega_id": entrega_id, "concluida": True}
    except Exception as exc:
        log.exception("Falha ao ler o documento da entrega %s", entrega_id)
        armazenamento.falhar_entrega(entrega_id, str(exc))
        raise
