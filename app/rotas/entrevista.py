"""Processamento da entrevista: relatório, escuta, análise, triagem, estratégia e consultas de CEP/CPF."""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import (
    analise_resposta,
    auth,
    consultas,
    escuta,
    jobs,
    rag,
    recomendacao,
    relatorio,
    roteiros,
    triagem,
)
from .. import entrevista as entrevista_lib
from ..tasks.documentos import gerar_relatorio as gerar_relatorio_job
from ..tasks.ia import gerar_estrategia as gerar_estrategia_job
from .comum import log

roteador = APIRouter()


class PedidoRelatorio(BaseModel):
    """As respostas da entrevista concluída."""

    respostas: dict[str, Any]
    roteiro: str = Field(default=roteiros.ROTEIRO_PADRAO, max_length=60)
    entrevistador: str = Field(default="", max_length=120)
    #: O relato corrido da entrevista — é dele que sai a análise por precedentes.
    #: A tela já o monta para a triagem; mandá-lo aqui evita reconstruí-lo.
    relato: str = Field(default="", max_length=20_000)
    #: Gerar a seção de análise (busca de precedentes + DeepSeek). Melhor-esforço:
    #: base fora do ar não impede o relatório, só troca a seção por uma nota.
    analisar: bool = True


@roteador.post("/api/entrevista/relatorio/jobs", status_code=202)
async def enfileirar_relatorio(pedido: PedidoRelatorio):
    await run_in_threadpool(jobs.inicializar)
    job_id = await run_in_threadpool(jobs.criar, "PDF")
    tarefa = gerar_relatorio_job.apply_async(
        args=(job_id, pedido.model_dump()), queue="documents", priority=4
    )
    await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
    return {"job_id": job_id, "task_id": tarefa.id, "status": "QUEUED", "progresso": 0}


@roteador.post("/api/entrevista/relatorio")
async def gerar_relatorio(pedido: PedidoRelatorio):
    """O relatório ANALISADO da entrevista, em PDF, com o símbolo do escritório.

    É a entrega que a saudação do roteiro promete ao cliente. Quem o recebe não
    estava na conversa, então ele diz o que foi perguntado, o que foi respondido
    e — principalmente — o que ficou sem resposta (ver `app/relatorio.py`).

    Traz também uma análise assistida por precedentes (o mesmo motor do
    `/api/estrategia`): síntese, ações sugeridas, riscos e lacunas, cada um
    citando o precedente que o sustenta. É apoio à decisão, não conclusão — a
    classificação jurídica continua sendo da equipe.
    """
    analise: dict[str, Any] | None = None
    if pedido.analisar and pedido.relato.strip():
        try:
            analise = await run_in_threadpool(rag.sugerir_acoes, pedido.relato)
        except Exception:
            # Base instável é o caso esperado, não a exceção (ver CONTEXTO.md). O
            # relatório sai com a nota em vez de esperar ou falhar por causa dela.
            log.warning("Análise do relatório indisponível", exc_info=True)
            analise = {
                "indisponivel": (
                    "A base de precedentes não respondeu a tempo. O relatório "
                    "organiza as respostas; a análise por precedentes pode ser "
                    "gerada depois, na triagem do caso."
                )
            }

    try:
        pdf, dados = await run_in_threadpool(
            relatorio.gerar_pdf,
            pedido.respostas,
            pedido.roteiro,
            pedido.entrevistador,
            analise,
        )
    except relatorio.ErroRelatorio as exc:
        raise HTTPException(400, str(exc)) from exc

    arquivo = f"Relatório de entrevista - {dados['cliente']}.pdf".replace(
        "/", "-"
    ).replace("\\", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="entrevista.pdf"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            # A tela precisa saber o que ficou pendente sem abrir o arquivo.
            "X-Pendencias": str(len(dados["faltando_obrigatorias"])),
            "X-Impedimentos": str(len(dados["impedimentos"])),
            # E se a análise entrou, para a tela poder avisar.
            "X-Analise": (
                "indisponivel"
                if analise and analise.get("indisponivel")
                else "sim"
                if analise
                else "nao"
            ),
        },
    )


class PedidoEscuta(BaseModel):
    """Um trecho de fala recém-transcrito, com o estado atual da entrevista."""

    trecho: str = Field(max_length=8_000)
    respostas: dict[str, Any] = Field(default_factory=dict)
    roteiro: str = Field(default=roteiros.ROTEIRO_PADRAO, max_length=60)
    #: Snapshot da versão que está na tela. É necessário para edições usadas
    #: apenas nesta sessão, que ainda não existem no catálogo do servidor.
    roteiro_snapshot: dict[str, Any] | None = None
    #: Qual pergunta está na vez NA TELA. Sem ela o backend adivinha "a primeira
    #: em aberto", e erra sempre que a condução pula adiante — que é o normal.
    pergunta_atual: str = Field(default="", max_length=80)


class PedidoProcessamentoEntrevista(BaseModel):
    """A conversa completa, enviada uma única vez depois do encerramento."""

    transcricao: str = Field(min_length=1, max_length=80_000)
    respostas: dict[str, Any] = Field(default_factory=dict)
    roteiro: str = Field(default=roteiros.ROTEIRO_PADRAO, max_length=60)
    #: A versão efetivamente exibida, inclusive quando editada só na sessão.
    roteiro_snapshot: dict[str, Any] | None = None
    #: Buscar precedentes no pgvector para sugerir perguntas e apontar lacunas.
    #: Melhor-esforço: banco fora do ar não impede o preenchimento do formulário.
    analisar: bool = True


def _roteiro_ativo(
    codigo: str, snapshot: dict[str, Any] | None
) -> roteiros.Roteiro | None:
    """Valida o snapshot vindo da tela e impede código/versão desencontrados."""
    try:
        return roteiros.snapshot_ativo(codigo, snapshot)
    except roteiros.RoteiroInvalido as exc:
        raise HTTPException(422, f"Roteiro ativo inválido: {exc}") from exc


@roteador.post("/api/entrevista/escuta")
async def escutar_entrevista(pedido: PedidoEscuta):
    """O que este trecho de fala respondeu do roteiro, e o que ainda falta.

    É o que sustenta a entrevista de microfone aberto: em vez de o entrevistador
    apertar gravar a cada uma das 86 perguntas, a conversa corre e o roteiro se
    preenche atrás dela (ver `app/escuta.py`).

    Devolve os três de uma vez — o que entrou, o que ficou pela metade e o que
    ninguém falou. Separados não servem: saber o que falta sem ver o que já
    entrou faz repetir pergunta, que é do que o escritório reclamou.
    """
    roteiro_ativo = _roteiro_ativo(pedido.roteiro, pedido.roteiro_snapshot)
    try:
        return await run_in_threadpool(
            escuta.escutar,
            pedido.trecho,
            pedido.respostas,
            pedido.roteiro,
            pedido.pergunta_atual,
            roteiro_ativo,
        )
    except escuta.ErroEscuta as exc:
        raise HTTPException(503, str(exc)) from exc


@roteador.post("/api/entrevista/processar")
async def processar_entrevista(pedido: PedidoProcessamentoEntrevista):
    """Consolida a transcrição, preenche o formulário e diz o que mais perguntar.

    Duas leituras independentes, em PARALELO porque nenhuma depende da outra e
    quem conduz está esperando com o cliente ainda na sala:

    - `escuta.processar_entrevista` diz o que a conversa respondeu do roteiro,
      cada campo com o trecho da transcrição que o sustenta;
    - `rag.sugerir_acoes` compara o relato com o acervo vetorial e devolve o que
      processos parecidos mostraram ser necessário — perguntas que valem a pena
      e lacunas que costumam custar caro.

    Separadas de propósito. Num prompt só, o precedente contaminaria a leitura: o
    modelo passaria a "encontrar" na conversa o que a jurisprudência sugeriu que
    deveria estar lá, e o campo preenchido deixaria de ser o que o cliente disse.
    """
    analise: dict[str, Any] | None = None
    erro_analise = ""
    roteiro_ativo = _roteiro_ativo(pedido.roteiro, pedido.roteiro_snapshot)

    def _analisar() -> None:
        nonlocal analise, erro_analise
        if not pedido.analisar:
            return
        try:
            analise = rag.sugerir_acoes(pedido.transcricao[:12_000])
        except Exception as exc:  # noqa: BLE001 — melhor-esforço, ver docstring
            # O formulário não pode cair junto com o banco de precedentes: ele é
            # a parte que o escritório não consegue refazer à mão, e o pgvector
            # já ficou fora do ar (CONTEXTO.md).
            erro_analise = str(exc)[:200]
            log.warning("Análise por precedentes falhou: %s", erro_analise)

    tarefa = threading.Thread(
        target=_analisar, name="entrevista-precedentes", daemon=True
    )
    tarefa.start()

    try:
        resultado = await run_in_threadpool(
            escuta.processar_entrevista,
            pedido.transcricao,
            pedido.respostas,
            pedido.roteiro,
            roteiro_ativo,
        )
    except escuta.ErroEscuta as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        # Esperar aqui é o que permite devolver as duas juntas: a tela mostra um
        # resultado só, no fim da entrevista.
        tarefa.join(timeout=escuta.TEMPO_PROCESSAMENTO_S)

    return {**resultado, "analise": analise, "analise_indisponivel": erro_analise}


class PedidoAnaliseResposta(BaseModel):
    """Uma resposta narrativa recém-dada, para conferência imediata."""

    pergunta_id: str = Field(max_length=120)
    pergunta: str = Field(max_length=1_000)
    resposta: str = Field(max_length=20_000)
    #: O pouco que já se sabe do caso — a categoria triada, tipicamente. Evita
    #: que a análise peça o que outra pergunta do roteiro já respondeu.
    contexto: str = Field(default="", max_length=4_000)


class PedidoRecomendacao(BaseModel):
    """Estado consolidado da entrevista, nunca fragmento provisório do Whisper."""

    relato: str = Field(min_length=40, max_length=40_000)
    lacunas_obrigatorias: list[str] = Field(default_factory=list, max_length=120)
    contexto_roteiro: str = Field(default="", max_length=12_000)
    limite_precedentes: int = Field(default=12, ge=4, le=30)


@roteador.post("/api/entrevista/analise")
async def analisar_resposta(pedido: PedidoAnaliseResposta):
    """O que esta resposta ainda não trouxe — em três itens, durante a entrevista.

    Roda uma vez por pergunta narrativa, então é deliberadamente mais curta que
    o `/api/estrategia`: o que não cabe entre uma pergunta e a seguinte não é
    lido (ver `app/analise_resposta.py`).

    Sai com `com_precedentes: false` quando o banco de precedentes não responde.
    A análise ainda vale, mas passa a ser a leitura do modelo sobre o texto — e
    não o que os processos semelhantes mostram. A tela precisa separar as duas.
    """
    try:
        # `analisar` é síncrona de ponta a ponta (psycopg e httpx bloqueantes);
        # rodá-la no laço de eventos travaria a transcrição ao vivo das outras
        # perguntas, que compartilha este processo.
        return await run_in_threadpool(
            analise_resposta.analisar,
            pedido.pergunta_id,
            pedido.pergunta,
            pedido.resposta,
            pedido.contexto,
        )
    except analise_resposta.ErroAnalise as exc:
        raise HTTPException(503, str(exc)) from exc


@roteador.post("/api/entrevista/recomendacao")
async def recomendar_entrevista(pedido: PedidoRecomendacao):
    """Diz se vale abrir o caso, apoiado na amostra semelhante do pgvector.

    É uma decisão de triagem reversível, não previsão de êxito. A rota recebe
    somente respostas já consolidadas e roda fora do event loop para não
    interromper a transcrição ao vivo enquanto consulta banco e embeddings.
    """
    lacunas = [
        str(item).strip()[:500]
        for item in pedido.lacunas_obrigatorias
        if str(item).strip()
    ]
    try:
        return await run_in_threadpool(
            recomendacao.recomendar,
            pedido.relato,
            lacunas_obrigatorias=lacunas,
            contexto_roteiro=pedido.contexto_roteiro,
            limite=pedido.limite_precedentes,
            # 6s era apertado: o pgvector fica atrás da VPN, com ~80ms de
            # latência e servidor compartilhado. Uma oscilação dentro desses 6
            # segundos virava "indisponível" numa consulta que costuma completar.
            connect_timeout=20,
            detalhar=True,
        )
    except recomendacao.ErroRecomendacao as exc:
        raise HTTPException(422, str(exc)) from exc
    except recomendacao.BaseIndisponivel as exc:
        # Causa dita, e não "indisponível": os dois consertos são diferentes —
        # este é checar a VPN e o servidor, não esperar nem refazer a entrevista.
        log.warning("Banco de precedentes fora: %s", str(exc)[:200])
        raise HTTPException(
            503,
            "O banco de precedentes não respondeu (ele fica atrás da VPN). "
            "A entrevista continua normalmente; a recomendação volta sozinha "
            "quando a conexão voltar.",
        ) from exc
    except Exception as exc:
        log.exception("Recomendação da entrevista falhou")
        raise HTTPException(
            503,
            "A recomendação falhou por um erro inesperado — está no log do "
            "servidor. A entrevista continua normalmente.",
        ) from exc


@roteador.get("/api/cep/{cep}")
async def consultar_cep(cep: str):
    """Endereço a partir do CEP, para adiantar o preenchimento da entrevista.

    Sai daqui apenas o CEP: nenhum dado do cliente acompanha a consulta. Ver
    `app/consultas.py` para o que as bases públicas resolvem — e o que não
    resolvem, que é praticamente tudo o mais.
    """
    try:
        return await consultas.buscar_cep(cep)
    except consultas.ErroConsulta as exc:
        # 422: o CEP é sintaticamente válido mas não existe, ou a base caiu. Não
        # é 404 da nossa rota — ela existe e respondeu.
        raise HTTPException(422, str(exc)) from exc


class PedidoCpf(BaseModel):
    """O CPF a consultar. Vai no CORPO, e não na URL, de propósito: caminho de
    URL entra em log de acesso, histórico de proxy e referer — e isto é dado
    pessoal de cidadão identificado, diferente do CEP."""

    cpf: str = Field(min_length=11, max_length=14)


@roteador.post("/api/cpf", dependencies=[Depends(auth.usuario_atual)])
async def consultar_cpf(pedido: PedidoCpf):
    """Qualificação do cidadão pela Receita, para adiantar a entrevista.

    Fecha o buraco que o `app/consultas.py` documenta desde o começo: nome, nome
    da mãe, nascimento, endereço e telefone deixam de ser datilografados (ou
    ouvidos errado) e vêm da fonte. Devolve os campos já nos ids das perguntas
    do roteiro; quem preenche o formulário é a tela, e só onde estiver vazio.

    Exige login — ao contrário do CEP, que é dado público e roda solto. Aqui
    cada consulta é um acesso a dado pessoal amparado pelo Termo de
    Responsabilidade do Conecta, e acesso sem autor identificado não se audita.
    """
    try:
        return await consultas.buscar_cpf(pedido.cpf)
    except consultas.ErroConsulta as exc:
        raise HTTPException(422, str(exc)) from exc


@roteador.post("/api/triagem")
async def triar_entrevista(
    texto: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    """Lê a entrevista e sugere a categoria do caso — sem criar nada.

    Devolve um ranking com a evidência de cada categoria. Quem decide é o
    advogado: errar a categoria é errar o checklist inteiro, e o sistema passaria
    a cobrar documentos que a ação não usa.
    """
    conteudo = texto or ""

    if arquivo is not None and arquivo.filename:
        bruto = await arquivo.read()
        if len(bruto) > 2 * 1024 * 1024:
            raise HTTPException(
                400, "Arquivo grande demais para uma entrevista (máx. 2 MB)."
            )
        try:
            conteudo = entrevista_lib.extrair_texto(arquivo.filename, bruto)
        except entrevista_lib.ErroDeLeitura as exc:
            raise HTTPException(400, str(exc)) from exc

    if not conteudo.strip():
        raise HTTPException(400, "Cole a entrevista ou envie um arquivo com texto.")

    resultado = triagem.triar(conteudo)
    resultado["dados"] = triagem.extrair_dados_do_cliente(conteudo)
    resultado["caracteres"] = len(conteudo)
    resultado["texto_extraido"] = conteudo
    return resultado


class PedidoEstrategia(BaseModel):
    relato: str = Field(min_length=30, max_length=50_000)
    limite_precedentes: int = Field(default=8, ge=3, le=15)


@roteador.post("/api/estrategia/jobs", status_code=202)
async def enfileirar_estrategia(pedido: PedidoEstrategia):
    await run_in_threadpool(jobs.inicializar)
    job_id = await run_in_threadpool(jobs.criar, "AI")
    tarefa = gerar_estrategia_job.apply_async(
        args=(job_id, pedido.relato, pedido.limite_precedentes), queue="ai", priority=5
    )
    await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
    return {"job_id": job_id, "task_id": tarefa.id, "status": "QUEUED", "progresso": 0}


@roteador.post("/api/estrategia")
async def estrategia(pedido: PedidoEstrategia):
    """Sugere próximos atos com precedentes recuperados antes da geração.

    Esta rota não é pública: passa pelo Keycloak. A resposta é apoio à decisão
    e inclui número, fonte, resultado e similaridade de cada precedente usado.
    """
    try:
        return await run_in_threadpool(
            rag.sugerir_acoes, pedido.relato, limite=pedido.limite_precedentes
        )
    except rag.ErroRAG as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Falha na análise estratégica")
        raise HTTPException(
            status_code=503, detail="Base estratégica indisponível."
        ) from exc
