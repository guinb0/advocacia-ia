"""Rotas do módulo do agente jurídico.

Todas sob `/api/agente` e protegidas pelo mesmo middleware das demais — o cliente do
portal não passa por aqui, e nenhuma delas é pública.

As de leitura respondem na hora com o que houver; as que **fazem** o agente trabalhar
(análise e pesquisa) devolvem 202 e o identificador da execução, porque do outro lado
elas rodam em worker (`AGENTS.md §14`). Prender a tela do advogado esperando um LLM é
justamente o que o Fast Path proíbe.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from .. import armazenamento, contrato
from . import dossie, espelho
from .cliente import AgenteIndisponivel, AgenteNaoConfigurado, Cliente, ErroDoAgente
from .config import config

log = logging.getLogger("agente")

roteador = APIRouter(prefix="/api/agente", tags=["agente"])


#: Recusas do agente que descrevem o **estado do caso**, e não uma falha da integração.
#:
#: São repassadas com o código e a mensagem originais porque cada uma diz ao advogado o que
#: fazer: `404` que o caso não existe mais do outro lado, `409` que falta um passo anterior
#: (pesquisa jurídica antes da jurimetria, por exemplo), `422` que os dados não sustentam a
#: operação. Achatá-las em `502 Bad Gateway` — como acontecia — trocava todas essas frases
#: por "erro no gateway", que não sugere ação nenhuma e ainda parece defeito de infra.
_REPASSADOS = frozenset(
    {
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    }
)


def _erro(erro: ErroDoAgente) -> HTTPException:
    """Traduz a falha para o código que a tela sabe tratar.

    `503` quando o agente não respondeu e `502` quando ele respondeu recusando por um
    motivo que o advogado não resolve: a primeira ele resolve tentando de novo; a segunda,
    não. As recusas de `_REPASSADOS` são a terceira categoria — ele resolve, mas mexendo no
    caso, e por isso precisam chegar inteiras à tela.
    """
    if isinstance(erro, AgenteNaoConfigurado):
        return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(erro))
    if isinstance(erro, AgenteIndisponivel):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(erro))
    if erro.status is not None and erro.status in _REPASSADOS:
        return HTTPException(erro.status, str(erro))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(erro))


@roteador.get("/config")
def configuracao() -> dict[str, Any]:
    """A tela pergunta antes de oferecer o botão — como já faz com a ZapSign."""
    cfg = config()
    resposta: dict[str, Any] = {
        "ligado": cfg.ligado,
        "url": cfg.url,
        "jurisdicao_padrao": espelho.jurisdicao_padrao(),
        "disponivel": False,
    }
    if not cfg.ligado:
        return resposta

    try:
        Cliente(cfg).saude()
        resposta["disponivel"] = True
    except ErroDoAgente as erro:
        # Configurado e fora do ar é diferente de não configurado: a tela precisa
        # dizer "não respondeu", não "não existe".
        resposta["motivo"] = str(erro)
    return resposta


@roteador.get("/saude")
def saude_do_agente() -> dict[str, Any]:
    """Latência dos dois bancos do agente e o desempenho de cada agente de IA nas
    últimas 24h — o `/health/inspection` de lá, repassado para a tela não precisar
    falar HTTP com outro serviço nem conhecer o token dele.
    """
    if not config().ligado:
        return {"ligado": False}
    try:
        dados = Cliente().inspecao()
    except ErroDoAgente as erro:
        raise _erro(erro) from erro
    dados["ligado"] = True
    return dados


@roteador.get("/casos/{caso_id}")
def dossie_do_caso(caso_id: str) -> dict[str, Any]:
    """Tudo que o escritório sabe do caso, dos dois lados."""
    montado = dossie.montar(caso_id)
    if montado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso não encontrado.")
    return montado


@roteador.post("/casos/{caso_id}/contrato")
def gerar_contrato_do_caso(caso_id: str) -> Response:
    """Gera usando o estado atual do caso, nunca um payload montado pelo navegador."""
    montado = dossie.montar(caso_id)
    if montado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso não encontrado.")

    respostas, motivos = dossie.dados_do_contrato(montado)
    if motivos:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Contrato não gerado: " + " ".join(motivos),
        )

    try:
        docx, faltando = contrato.gerar(respostas)
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    cliente = str(respostas["nome"])
    arquivo = f"Contrato - {cliente}.docx".replace("/", "-").replace("\\", "-")
    return Response(
        content=docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f'attachment; filename="contrato.docx"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            "X-Campos-Faltando": ", ".join(faltando),
        },
    )


@roteador.post("/casos/{caso_id}/sincronizar", status_code=status.HTTP_201_CREATED)
def sincronizar(caso_id: str, jurisdicao: str | None = Body(None, embed=True)) -> dict[str, Any]:
    """Cria o caso no agente (se ainda não existe) e manda o que faltava.

    Idempotente: chamar duas vezes reaproveita o mesmo caso do outro lado e só envia
    documento que ainda não tinha ido.
    """
    try:
        return espelho.sincronizar(caso_id, jurisdicao=jurisdicao)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/entrevista/{entrevista_id}")
def enviar_entrevista(caso_id: str, entrevista_id: str) -> dict[str, Any]:
    """Manda a entrevista guardada no Acervo para o agente ler.

    Síncrona de propósito: é uma chamada de modelo, e quem clicou está olhando a tela
    esperando os fatos aparecerem no dossiê.
    """
    try:
        return espelho.enviar_entrevista(caso_id, entrevista_id)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/analise", status_code=status.HTTP_202_ACCEPTED)
def analisar(caso_id: str) -> dict[str, Any]:
    """Classifica o caso e recalcula as pendências do playbook."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().analisar(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/pesquisa", status_code=status.HTTP_202_ACCEPTED)
def pesquisar(caso_id: str) -> dict[str, Any]:
    """Dispara a pesquisa de jurisprudência a partir das questões do caso."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().pesquisar(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/pesquisa/{pesquisa_ref}")
def pesquisa(caso_id: str, pesquisa_ref: str) -> dict[str, Any]:
    """Precedentes recuperados, com aplicabilidade, trechos citados e filtros usados."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().pesquisa(caso_ref, pesquisa_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/jurimetria")
def jurimetria(caso_id: str, orgao: str | None = None) -> dict[str, Any]:
    """Como o foro decide a matéria deste caso, e onde o caso cai dentro disso.

    Síncrona: do outro lado são contagens no acervo, não chamada de modelo. É a leitura
    que o dossiê não dá — ele responde "em que pé está o caso", e esta responde "o que
    esperar do mérito".
    """
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().jurimetria(caso_ref, orgao=orgao)
    except ErroDoAgente as erro:
        if erro.status == status.HTTP_404_NOT_FOUND:
            # `404` aqui é ambíguo e as duas causas levam a ações opostas: ou o caso sumiu
            # do agente, ou o agente em execução é anterior a este módulo e a rota nem
            # existe lá. Dizer as duas é mais útil que escolher uma e errar.
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "O agente não reconheceu esta consulta. Ou o caso não existe mais nele, ou "
                "a versão em execução do agente é anterior ao módulo de jurimetria — neste "
                "caso, reiniciar o serviço resolve.",
            ) from erro
        raise _erro(erro) from erro


@roteador.get("/jurimetria")
def jurimetria_do_acervo(
    assunto: list[str] = Query(default=[]),
    orgao: list[str] = Query(default=[]),
    magistrado: list[str] = Query(default=[]),
    de: str | None = None,
    ate: str | None = None,
) -> dict[str, Any]:
    """O mesmo painel sem caso nenhum: o retrato do acervo por recorte livre.

    Existe porque a pergunta "como esta vara decide isto?" é anterior ao caso — ela
    aparece na conversa de captação, antes de haver processo para comparar.
    """
    try:
        return Cliente().jurimetria_do_acervo(
            {
                "subject": assunto,
                "judging_body": orgao,
                "judge": magistrado,
                "decided_from": de,
                "decided_to": ate,
            }
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post(
    "/casos/{caso_id}/jurimetria/linhas-argumentativas", status_code=status.HTTP_202_ACCEPTED
)
def disparar_linhas_argumentativas(caso_id: str) -> dict[str, Any]:
    """Dispara a leitura das razões de decidir do recorte comparável deste caso."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().linhas_argumentativas(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/jurimetria/linhas-argumentativas")
def linhas_argumentativas(caso_id: str) -> dict[str, Any] | None:
    """A leitura mais recente, ou `None` quando ainda não foi pedida."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().linhas_argumentativas_resultado(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/jurimetria/contra-tese", status_code=status.HTTP_202_ACCEPTED)
def disparar_contra_tese(
    caso_id: str, hipotese_id: str = Body(..., embed=True)
) -> dict[str, Any]:
    """Dispara o argumento provável do outro lado contra a hipótese indicada.

    A tese a atacar é escolha do advogado — mesma régua da aprovação de estratégia.
    """
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().contra_tese(caso_ref, hipotese_id)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/jurimetria/contra-tese")
def contra_tese(caso_id: str) -> dict[str, Any] | None:
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().contra_tese_resultado(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.patch("/casos/{caso_id}/contradicoes/{contradicao_ref}")
def resolver_contradicao(
    caso_id: str,
    contradicao_ref: str,
    estado: str = Body(..., embed=True),
    resolucao: str = Body(..., embed=True),
    justificativa: str = Body(..., embed=True),
) -> dict[str, Any]:
    """Decide uma divergência entre o que o cliente contou e o que o documento registra.

    A justificativa é obrigatória do outro lado: daqui a seis meses ninguém lembra por que
    aquela versão do caso foi a escolhida.
    """
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().resolver_contradicao(
            caso_ref,
            contradicao_ref,
            estado=estado,
            resolucao=resolucao,
            justificativa=justificativa,
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/estrategia", status_code=status.HTTP_202_ACCEPTED)
def gerar_estrategia(caso_id: str) -> dict[str, Any]:
    """Propõe as teses do caso, com o que sustenta e o que enfraquece cada uma."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().gerar_estrategia(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.patch("/casos/{caso_id}/estrategia/{versao}")
def decidir_estrategia(
    caso_id: str,
    versao: int,
    aprovada: bool = Body(..., embed=True),
    nota: str | None = Body(None, embed=True),
) -> dict[str, Any]:
    """Aprovar a estratégia é o que faz a petição parar de tirar pedidos do playbook."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().decidir_estrategia(caso_ref, versao, aprovada=aprovada, nota=nota)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.patch("/casos/{caso_id}/estrategia/hipoteses/{hipotese_ref}")
def decidir_hipotese(
    caso_id: str,
    hipotese_ref: str,
    aceita: bool = Body(..., embed=True),
    enunciado: str | None = Body(None, embed=True),
) -> dict[str, Any]:
    """Aceitar, descartar ou reescrever uma tese. A tese é do advogado."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().decidir_hipotese(
            caso_ref, hipotese_ref, aceita=aceita, enunciado=enunciado
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/peticao", status_code=status.HTTP_202_ACCEPTED)
def gerar_peticao(caso_id: str) -> dict[str, Any]:
    """Dispara a minuta da petição inicial no agente.

    Responde 202 e a peça aparece no dossiê quando ficar pronta: são várias chamadas de
    modelo, uma por seção, e prender a tela do advogado nisso é o que o Fast Path proíbe.
    """
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().gerar_peticao(caso_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/peticao/{peca_ref}")
def peticao(caso_id: str, peca_ref: str) -> dict[str, Any]:
    """A minuta com as seções, o readiness e o relatório de revisão."""
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().peticao(caso_ref, peca_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/casos/{caso_id}/peticao/{peca_ref}/arquivo")
def baixar_peticao(caso_id: str, peca_ref: str) -> Response:
    """O `.docx` da minuta, buscado no agente e repassado ao navegador."""
    caso_ref = _caso_ref(caso_id)
    try:
        conteudo = Cliente().baixar_peticao(caso_ref, peca_ref)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro

    caso = armazenamento.obter_caso(caso_id) or {}
    arquivo = f"Peticao inicial - {caso.get('cliente', 'caso')}.docx".replace("/", "-")
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f'attachment; filename="peticao.docx"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            )
        },
    )


@roteador.patch("/casos/{caso_id}/peticao/{peca_ref}")
def decidir_peticao(
    caso_id: str,
    aprovada: bool = Body(..., embed=True),
    peca_ref: str = "",
    nota: str | None = Body(None, embed=True),
    secoes: list[dict[str, str]] | None = Body(None, embed=True),
) -> dict[str, Any]:
    """A revisão humana (`§2.10`). O agente recusa aprovar peça com achado bloqueante.

    `secoes` leva o texto como o advogado o entregou. O agente grava essa versão ao lado da
    gerada e mede, seção a seção, o que mudou — é assim que o sistema aprende o estilo do
    escritório em vez de repetir o do modelo.
    """
    caso_ref = _caso_ref(caso_id)
    try:
        return Cliente().decidir_peticao(
            caso_ref, peca_ref, aprovada=aprovada, nota=nota, secoes=secoes
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


# ------------------------------------------------------------------- estilo


@roteador.post("/estilo/pecas", status_code=status.HTTP_201_CREATED)
async def enviar_peca_de_estilo(
    arquivo: UploadFile = File(...),
    taxonomy_code: str = Form(...),
    document_type: str = Form("INITIAL_PETITION"),
) -> dict[str, Any]:
    """Sobe uma peça pronta do escritório para o corpus de estilo.

    O arquivo atravessa este servidor em vez de ir direto do navegador ao agente porque é
    aqui que ficam o endereço e o token — o mesmo caminho que o resto da ponte já usa.
    """
    conteudo = await arquivo.read()
    try:
        return Cliente().enviar_peca_de_estilo(
            nome=arquivo.filename or "peca.docx",
            conteudo=conteudo,
            taxonomy_code=taxonomy_code,
            document_type=document_type,
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/estilo/perfil")
def perfil_de_estilo(
    taxonomy_code: str | None = None,
    document_type: str = "INITIAL_PETITION",
    unidade: str = "DOCUMENT",
) -> dict[str, Any]:
    """O padrão de escrita do grupo. `404` do agente significa "ainda não há peças"."""
    try:
        return Cliente().perfil_de_estilo(
            taxonomy_code=taxonomy_code, document_type=document_type, unidade=unidade
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.get("/estilo/taxonomia")
def taxonomia_de_estilo() -> dict[str, Any]:
    """As quatro ações que o escritório realmente opera no sistema.

    O agente expõe uma taxonomia jurídica completa. Danos, nexo causal e
    incapacidade são questões de uma ação, não ações cadastráveis nesta tela.
    Deixar o frontend consumir a árvore inteira criava dezenas de perfis de
    escrita sem correspondência com os checklists e playbooks do escritório.
    """
    try:
        resposta = Cliente().taxonomia()
    except ErroDoAgente as erro:
        raise _erro(erro) from erro

    codigos_ativos = (
        "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT.CORREIOS",
        "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT",
        "LABOR.OCCUPATIONAL_HEALTH.OCCUPATIONAL_DISEASE",
        "SOCIAL_SECURITY.BENEFIT.ACCIDENT_ALLOWANCE",
    )
    por_codigo = {
        str(item.get("code", "")): item
        for item in resposta.get("items", resposta.get("nodes", []))
        if isinstance(item, dict)
    }
    return {"items": [por_codigo[codigo] for codigo in codigos_ativos if codigo in por_codigo]}


@roteador.get("/estilo/pecas")
def pecas_de_estilo(
    taxonomy_code: str | None = None, document_type: str | None = None
) -> dict[str, Any]:
    try:
        return Cliente().pecas_de_estilo(
            taxonomy_code=taxonomy_code, document_type=document_type
        )
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.delete("/estilo/pecas/{peca_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_peca_de_estilo(peca_id: str) -> None:
    """Remove uma amostra; o agente confere organização e recalcula na próxima leitura."""
    try:
        Cliente().remover_peca_de_estilo(peca_id)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


@roteador.post("/casos/{caso_id}/contrato/conferencia")
def conferir_contrato(caso_id: str, campos: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Confere a qualificação do contrato contra os fatos apurados dos documentos.

    Divergência de CPF entre o que o cliente falou na entrevista e o que a CTPS diz
    custa uma conferência agora e um aditivo depois da assinatura.
    """
    try:
        return espelho.conferir_contrato(caso_id, campos)
    except ErroDoAgente as erro:
        raise _erro(erro) from erro


def _caso_ref(caso_id: str) -> str:
    """O caso correspondente no agente, criando-o se for a primeira vez.

    Criar aqui é deliberado: o advogado que clica em "analisar" quer a análise, não
    uma mensagem dizendo que precisa antes clicar em outro botão.

    O vínculo guardado **não** serve como atalho: ele diz que o caso foi criado, não que
    ele ainda existe. Confiar nele fazia toda ação — analisar, pesquisar, gerar peça —
    apontar para um caso morto depois de o agente trocar de banco, e o advogado recebia
    "caso não encontrado" sem nada que pudesse fazer na tela.

    `garantir_caso` custa uma leitura e resolve o caso comum. A sincronização completa,
    que reenvia documentos e requalifica a parte, só roda quando o caso teve mesmo de ser
    recriado — do contrário cada clique em "analisar" pagaria por ela.
    """
    anterior = armazenamento.obter_vinculo_agente(caso_id)
    try:
        vinculo = espelho.garantir_caso(caso_id)
        if anterior is None or anterior["caso_ref"] != vinculo["caso_ref"]:
            return str(espelho.sincronizar(caso_id)["caso_ref"])
    except ErroDoAgente as erro:
        raise _erro(erro) from erro
    return str(vinculo["caso_ref"])
