from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import multiprocessing
import os

import httpx
from celery.signals import worker_ready

from .. import (
    armazenamento,
    casos,
    categorias,
    duplicidade,
    extracao_office,
    historico_alteracoes,
    indexacao_documento,
    jobs,
    pdf,
    pipeline,
    roteamento,
    visao_documento,
)
from ..celery_app import celery_app

log = logging.getLogger("ocr-worker")


def _processar_em_subprocesso(
    conexao,
    conteudo: bytes,
    nome: str,
    idioma: str,
    tipo: str | None,
    gerar_arquivos_temporarios: bool,
) -> None:
    """Executa o OCR fora do processo que consome a fila."""
    try:
        conexao.send(("ok", pipeline.processar(
            conteudo, nome, idioma, tipo,
            gerar_arquivos_temporarios=gerar_arquivos_temporarios,
        )))
    except BaseException as exc:  # fronteira de processo: devolve o erro ao pai
        conexao.send(("erro", f"{type(exc).__name__}: {exc}"))
    finally:
        conexao.close()


def _executar_ocr(caminho: str, nome: str, idioma: str, tipo: str | None) -> dict:
    return _executar_ocr_conteudo(Path(caminho).read_bytes(), nome, idioma, tipo)


def _executar_ocr_conteudo(
    conteudo: bytes,
    nome: str,
    idioma: str,
    tipo: str | None,
    *,
    gerar_arquivos_temporarios: bool = True,
) -> dict:
    # Em producao, cada leitura nasce em processo limpo. Se OpenCV ou PDFium
    # travar em codigo C, matar o filho libera o consumidor para a proxima
    # entrega, em vez de congelar toda a triagem atras de um documento.
    # `spawn` e intencional: `fork` herdaria o estado que causou o deadlock.
    isolar = os.getenv("OCR_ISOLAR_PROCESSO", "0").strip().lower() not in {
        "0", "false", "nao",
    }
    # Processo daemon não pode criar filhos. Com `daemon=True` no isolador, a
    # pipeline (e libs C) disparavam "daemonic processes are not allowed to
    # have children" e a entrega ia para erro — inclusive em reprocessamentos.
    if not isolar or multiprocessing.current_process().daemon:
        return pipeline.processar(
            conteudo, nome, idioma, tipo,
            gerar_arquivos_temporarios=gerar_arquivos_temporarios,
        )

    limite = float(os.getenv("OCR_EXECUCAO_TIMEOUT_S", "600"))
    if limite <= 0:
        raise ValueError("OCR_EXECUCAO_TIMEOUT_S deve ser maior que zero.")

    contexto = multiprocessing.get_context("spawn")
    pai, filho = contexto.Pipe(duplex=False)
    processo = contexto.Process(
        target=_processar_em_subprocesso,
        args=(filho, conteudo, nome, idioma, tipo, gerar_arquivos_temporarios),
        # Não-daemon: o filho pode criar netos (libs de OCR). O pai ainda
        # faz terminate()/join() no timeout — isolamento continua valendo.
        daemon=False,
    )
    processo.start()
    filho.close()
    try:
        if not pai.poll(limite):
            processo.terminate()
            processo.join(timeout=10)
            raise TimeoutError(f"OCR excedeu o limite de {limite:.0f}s; leitura interrompida.")
        estado, valor = pai.recv()
    finally:
        pai.close()
        if processo.is_alive():
            processo.terminate()
            processo.join(timeout=5)

    if processo.is_alive():
        processo.kill()
        processo.join(timeout=2)
    if estado == "erro":
        raise RuntimeError(valor)
    return valor


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


def _segurar_se_duplicado(
    entrega_id: str,
    caso_id: str,
    resultado: dict,
    destino: roteamento.Destino,
    categoria: categorias.Categoria,
) -> roteamento.Destino:
    """Documento que parece repetir outro do caso não conta no checklist sozinho.

    O envio já barrou o arquivo idêntico (`duplicidade.identicos`, na API). O que só
    a leitura revela — o mesmo número de documento em outra foto, o mesmo texto em
    outro arquivo — é verificado aqui, ANTES de a entrega marcar um item: a suspeita
    manda o documento para a triagem com o motivo, e é a pessoa que decide.

    Falhar nesta verificação não pode perder a leitura: o documento segue o destino
    que o roteamento deu, como antes desta regra existir.
    """
    if destino.em_triagem:
        return destino
    try:
        # Repetido aceito no envio já teve a decisão tomada por alguém.
        if historico_alteracoes.houve(
            historico_alteracoes.ENTIDADE_ENTREGA, entrega_id, "duplicidade_confirmada"
        ):
            return destino
        suspeitas = duplicidade.procurar(
            caso_id,
            {
                "id": entrega_id,
                "conteudo_sha256": duplicidade.sha_da_entrega(entrega_id),
                "tipo_detectado": (resultado.get("tipo") or {}).get("detectado"),
                "itens_atendidos": list(destino.itens),
                "roteamento_origem": destino.origem,
                "extracao": resultado,
            },
            categoria,
        )
    except Exception:
        log.warning("verificação de duplicidade falhou para %s", entrega_id, exc_info=True)
        return destino
    if not suspeitas:
        return destino

    resultado["duplicidade"] = {
        "suspeitas": [s.to_dict() for s in suspeitas],
        "destino_sugerido": list(destino.itens),
    }
    log.info("entrega %s segurada na triagem por duplicidade", entrega_id)
    return roteamento.Destino(
        [],
        roteamento.DUPLICIDADE,
        0,
        duplicidade.mensagem(suspeitas),
        destino.analise,
    )


@worker_ready.connect
def aquecer_worker_ocr(sender=None, **_kwargs):
    """Carrega o modelo no worker, sem prender o boot numa inferência completa."""
    hostname = str(getattr(sender, "hostname", ""))
    if not hostname.lower().startswith("ocr@"):
        return
    from ..ocr_heartbeat import iniciar
    iniciar(hostname)
    try:
        from ..ocr_engine import aquecer

        aquecer()
        log.info("OCR configurado no worker %s.", hostname)
    except Exception:
        # O primeiro job tenta novamente; worker vivo é melhor que abortar toda
        # a fila por uma falha transitória de modelo no boot.
        log.exception("Falha ao configurar Mistral OCR no worker %s.", hostname)


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_documento",
    # Limite proprio do OCR: nao deixa uma leitura pendurada ocupar a replica
    # indefinidamente. Com acks_late/reject_on_worker_lost a mensagem retorna.
    soft_time_limit=780,
    time_limit=840,
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 1},
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
    soft_time_limit=780,
    time_limit=840,
    # `httpx.HTTPError` cobre 402/429/5xx e queda de conexão dos provedores de
    # OCR: sem isto, um provedor fora do ar marcava a entrega em 'erro' na
    # primeira falha, sem repetir sozinho — só o botão manual reenfileirava.
    # Três tentativas automáticas (backoff crescente até 60s) cobrem o caso de
    # instabilidade curta; esgotadas, a entrega fica em 'erro' de verdade e o
    # botão "Tentar novamente" continua disponível.
    autoretry_for=(OSError, TimeoutError, httpx.HTTPError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 1},
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
        armazenamento.marcar_entrega_processando(
            entrega_id, str(self.request.id or ""), str(self.request.hostname or "")
        )
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
        formato_lido = False
        resultado: dict | None = None
        texto_nativo_pdf = pdf.extrair_texto_nativo(conteudo) if extensao == ".pdf" else ""
        if texto_nativo_pdf:
            # PDF gerado por sistema (protocolo do INSS, petição, portal da
            # Justiça) já tem o texto gravado — ler direto é mais fiel, mais
            # rápido e não gasta chamada de OCR. `pdf_para_imagem` nem entra
            # em jogo aqui, então o teto de páginas dele também não se aplica.
            formato_lido = True
            resultado = pipeline.processar_texto(
                texto_nativo_pdf, nome, idioma, tipo_extracao, gerar_arquivos_temporarios=False
            )
        elif extensao in pipeline.EXTENSOES_OCR:
            formato_lido = True
            resultado = _executar_ocr_conteudo(
                conteudo,
                nome,
                idioma,
                tipo_extracao,
                gerar_arquivos_temporarios=False,
            )
        elif extensao in {".mp4", ".m4a", ".mp3", ".wav", ".webm", ".opus", ".ogg", ".oga", ".3gp"}:
            # `.opus`/`.ogg` são o formato de áudio de voz do WhatsApp — sem eles
            # aqui, o áudio exportado do WhatsApp caía direto em "formato
            # preservado sem OCR" e nunca era transcrito.
            # Áudio/vídeo também é prova: transcreve antes de classificar para a
            # IA poder usar o relato como contexto, em vez de jogá-lo na triagem.
            try:
                import av
                import numpy as np
                from .. import transcricao
                import io
                partes = []
                with av.open(io.BytesIO(conteudo)) as midia:
                    resampler = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=16_000)
                    for frame in midia.decode(audio=0):
                        convertido = resampler.resample(frame)
                        for bloco in (convertido if isinstance(convertido, list) else [convertido]):
                            partes.append(bloco.to_ndarray().reshape(-1))
                texto = transcricao._transcrever(np.concatenate(partes)) if partes else ""
            except Exception as exc:
                log.warning("transcrição do vídeo falhou para %s: %s", entrega_id, exc)
                texto = ""
            if texto.strip():
                formato_lido = True
                resultado = pipeline.processar_texto(texto, nome, idioma, tipo_extracao, gerar_arquivos_temporarios=False)
        elif extensao in extracao_office.EXTENSOES_TEXTO:
            # DOCX e TXT já trazem o texto gravado: em vez de preservar sem ler,
            # extrai o texto digital e segue pelo MESMO caminho do OCR (campos +
            # classificação semântica), para que uma procuração em .docx tenha
            # nome, CPF e demais achados lidos e roteados como qualquer outro.
            try:
                texto = extracao_office.extrair_texto(conteudo, extensao)
            except Exception as exc:
                log.warning("leitura de texto falhou para %s (%s): %s", entrega_id, nome, exc)
                texto = ""
            if texto.strip():
                formato_lido = True
                resultado = pipeline.processar_texto(
                    texto,
                    nome,
                    idioma,
                    tipo_extracao,
                    gerar_arquivos_temporarios=False,
                )

        if not formato_lido:
            # Receber não é o mesmo que conseguir ler. Word binário (.doc),
            # planilha, áudio, vídeo, ZIP e qualquer formato futuro ficam
            # preservados no caso. Um envio associado a um item permanece nesse
            # item para conferência; no envio em massa, fica na triagem.
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
        from .. import fila_sql as _fila_sql_log

        _fila_sql_log._evento("CLASSIFICATION_STARTED", document_id=entrega_id)
        destino = roteamento.decidir(resultado, categoria, item)
        _fila_sql_log._evento(
            "CLASSIFICATION_COMPLETED",
            document_id=entrega_id,
            origem=destino.origem,
            itens=",".join(destino.itens) if destino.itens else "",
        )
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
        elif (
            formato_lido
            and resultado.get("validacao", {}).get("texto_utilizavel")
            # ÁLBUM DE FOTOS NÃO É DOCUMENTO COM TEXTO, por mais caracteres que
            # o OCR devolva. `texto_utilizavel` conta caracteres (>= 80), e um
            # PDF com cinco fotos devolve cinco `![img-N.jpeg](img-N.jpeg)` —
            # 125 caracteres, acima do corte. O arquivo vinha para cá, a
            # DeepSeek lia nomes de arquivo e respondia "Indefinido" com zero
            # dados, e a foto nunca era olhada por ninguém. Foi o que aconteceu
            # com `FOTOS LESAO POS-OPERATORIO.pdf`. Sem texto de verdade, quem
            # tem de ler é o modelo de visão, no ramo abaixo.
            and not visao_documento.so_referencias_de_imagem(
                str(resultado.get("texto_completo") or "")
            )
            and destino.origem != roteamento.DETERMINISTICO
        ):
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
        elif formato_lido and extensao in visao_documento.EXTENSOES_IMAGEM:
            # A FOTO QUE NÃO É DOCUMENTO — o caso que não caía em ramo nenhum.
            #
            # Chegar aqui significa: o OCR rodou (`formato_lido`) e NÃO achou
            # texto aproveitável (senão o ramo acima teria pego). Num escritório
            # trabalhista isso quase sempre é a foto do veículo amassado, da
            # máquina, do local ou da lesão — e até agora ela ia para a triagem
            # muda, com o advogado abrindo uma a uma para ver o que o cliente
            # mandou. `valor_documento` não alcança este caso por construção:
            # ele lê TEXTO, e aqui não há texto para ler.
            #
            # O retorno tem a mesma forma do semântico, então segue pelo mesmo
            # `aplicar_interpretacao` — inclusive a regra de não rebaixar
            # classificação determinística e de marcar campo interpretado com
            # confiança zero.
            try:
                pendentes = [
                    {"codigo": esperado.codigo, "nome": esperado.nome}
                    for esperado in categoria.itens
                ]
                visao = visao_documento.ler_imagem(
                    conteudo, extensao, categoria.nome, pendentes
                )
                semantica = {
                    **visao,
                    "classificador": "visao",
                    "tipo_semantico": str(visao.get("documento") or "indefinido"),
                }
                resultado["classificacao_semantica"] = semantica
                indexacao_documento.aplicar_interpretacao(resultado, semantica)
            except Exception as exc:
                # Foto não lida não trava o envio: o arquivo continua no caso e
                # na triagem, exatamente como estava antes desta adição.
                log.warning("leitura de imagem falhou para %s: %s", entrega_id, exc)
                resultado["classificacao_semantica"] = {
                    "status": "indisponivel",
                    "erro": str(exc)[:200],
                }

        if (
            formato_lido
            and extensao in visao_documento.EXTENSOES_IMAGEM
            and self.request.retries > 0
            and not (resultado.get("classificacao_semantica") or {}).get("tipo_semantico")
        ):
            # Ainda sem categoria numa tentativa automática (2ª/3ª do
            # `autoretry_for`): repetir a MESMA leitura de texto tende a
            # repetir a mesma falha. Pede uma segunda opinião ao modelo de
            # visão sobre a imagem original — abordagem diferente, chance real
            # de destravar o que o texto não deu conta.
            try:
                pendentes = [
                    {"codigo": esperado.codigo, "nome": esperado.nome}
                    for esperado in categoria.itens
                ]
                visao = visao_documento.ler_imagem(conteudo, extensao, categoria.nome, pendentes)
                semantica = {
                    **visao,
                    "classificador": "visao_retry",
                    "tipo_semantico": str(visao.get("documento") or "indefinido"),
                }
                resultado["classificacao_semantica"] = semantica
                indexacao_documento.aplicar_interpretacao(resultado, semantica)
            except Exception as exc:
                log.warning("segunda opinião por visão (retry) falhou para %s: %s", entrega_id, exc)

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

        destino = _segurar_se_duplicado(entrega_id, caso_id, resultado, destino, categoria)

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
        if (
            resultado.get("classificacao_semantica", {}).get("tipo_semantico")
            and not destino.em_triagem
            and destino.origem != roteamento.DUPLICIDADE
        ):
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
        # Com a fila SQL, o worker decide retry (PENDING + backoff) vs falha
        # definitiva. Marcar `erro` aqui matava o documento na 1ª tentativa
        # temporária e contradizia `fila_sql.falhar`.
        if os.getenv("OCR_FILA_SQL_HANDLER", "").strip() not in {"1", "true", "sim"}:
            armazenamento.falhar_entrega(entrega_id, str(exc))
        raise
