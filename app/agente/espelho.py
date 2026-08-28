"""Espelha no agente jurídico o que o OCR já apurou.

O OCR é o sistema onde o caso nasce: o advogado cadastra o cliente, o checklist é
montado e os documentos chegam. O agente é onde esse material vira **Case State** —
fato com proveniência, classificação, pendência e pesquisa de jurisprudência.

A ligação é de mão única de propósito: o OCR **empurra** o que produziu e **lê** o
que o agente concluiu. Ele nunca escreve no banco do agente por outro caminho, e o
agente nunca escreve no SQLite daqui. Cada lado continua sendo dono do que produz —
é o que permite subir, testar e reverter um sem parar o outro.

O que atravessa a ponte:

- **cliente e caso**, uma vez, na primeira sincronização;
- **cada extração do OCR**, assim que a leitura termina, com chave
  `entrega_id:hash_da_extracao` como idempotência — reprocessar o OCR reenvia com
  payload novo; repetir o mesmo payload não duplica documento;
- **a qualificação do contrato**, que não vira fato: ela é conferida contra os fatos
  que o agente já apurou, e a divergência é mostrada ao advogado antes da assinatura.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from .. import armazenamento, extractors
from . import vocabulario
from .cliente import AgenteIndisponivel, Cliente, ErroDoAgente, caso_ref_valido

log = logging.getLogger("agente")

# Abrir/atualizar o dossiê pode chamar a sincronização várias vezes em poucos
# segundos. A fila do agente é idempotente para documentos, mas não para todos os
# jobs jurídicos; esta janela impede enfileirar a mesma etapa a cada refresh.
_RETOMADA_TTL_S = 120.0
_retomadas_recentes: dict[str, float] = {}
_retomadas_lock = Lock()

# A abertura do dossiê dispara leituras paralelas. Sem serializar a recuperação,
# duas requisições podem observar o mesmo vínculo órfão, criar casos diferentes e
# sobrescrever `caso_ref` uma depois da outra. Documentos e geração acabam então
# enviados ao identificador que perdeu a corrida.
_vinculos_locks: dict[str, Lock] = {}
_vinculos_locks_guard = Lock()

# Depois de criar ou revincular, o agente pode levar alguns segundos para o caso
# aparecer na leitura (réplica, pooler, commit). Recriar nessa janela gerava um caso
# novo a cada requisição — o sintoma do `diag_pipeline` com três `case_ref` em 30s.
_VINCULO_CONFIANCA_S = 90.0
_EXISTE_RETRY_S = 0.4

__all__ = [
    "analisar_caso_inteiro",
    "caso_ref",
    "conferir_contrato",
    "enviar_entrega",
    "garantir_caso",
    "sincronizar",
]


def jurisdicao_padrao() -> str:
    """Jurisdição atribuída ao caso quando ninguém informa.

    O escritório atende no Pará e no Amapá, e é a jurisdição que decide quais
    precedentes a pesquisa pode usar (`AGENTS.md §19`). Deixá-la vazia faria a
    pesquisa varrer o acervo inteiro por similaridade e devolver acórdão de outro
    regional — parecido e inaplicável.
    """
    return os.getenv("AGENTE_JURISDICAO_PADRAO", "TRT8").strip()


# ---------------------------------------------------------------- vínculo


def _instante_vinculo(vinculo: dict[str, Any]) -> float | None:
    """Converte `atualizado_em`/`criado_em` do vínculo para epoch UTC."""
    bruto = vinculo.get("atualizado_em") or vinculo.get("criado_em")
    if not bruto:
        return None
    texto = str(bruto).replace("Z", "+00:00")
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.timestamp()


def _vinculo_recente(vinculo: dict[str, Any]) -> bool:
    """Vínculo atualizado há pouco — ainda não recriar por um 404 isolado."""
    if not caso_ref_valido(str(vinculo.get("caso_ref") or "")):
        return False
    ultimo_erro = str(vinculo.get("ultimo_erro") or "").casefold()
    if "caso não encontrado" in ultimo_erro or "caso nao encontrado" in ultimo_erro:
        # Um 404 já observado pelo próprio agente não é atraso de réplica. Sem esta
        # distinção, registrar o erro renovava ``atualizado_em`` e o vínculo órfão ganhava
        # mais 90 segundos de confiança a cada tentativa, ficando preso para sempre.
        return False
    instante = _instante_vinculo(vinculo)
    if instante is None:
        return False
    return (time.time() - instante) < _VINCULO_CONFIANCA_S


def _caso_existe_no_agente(cliente: Cliente, caso_ref: str) -> bool:
    """Confere existência com uma segunda tentativa para visibilidade atrasada."""
    try:
        if cliente.caso_existe(caso_ref):
            return True
    except AgenteIndisponivel:
        raise
    time.sleep(_EXISTE_RETRY_S)
    try:
        return cliente.caso_existe(caso_ref)
    except AgenteIndisponivel:
        raise


def garantir_caso(caso_id: str, *, jurisdicao: str | None = None) -> dict[str, Any]:
    with _vinculos_locks_guard:
        lock = _vinculos_locks.setdefault(caso_id, Lock())
    with lock:
        return _garantir_caso(caso_id, jurisdicao=jurisdicao)


def _garantir_caso(caso_id: str, *, jurisdicao: str | None = None) -> dict[str, Any]:
    """Devolve o vínculo com o agente, criando cliente e caso quando preciso.

    Idempotente pelo vínculo guardado aqui: um segundo clique em "enviar ao agente"
    reaproveita o caso existente. Sem isso, o mesmo cliente teria dois casos no agente,
    cada um com metade dos documentos — e ninguém perceberia até a pesquisa jurídica
    sair pela metade.

    O vínculo sozinho não basta como prova: ele diz que o caso **foi** criado, não que
    ele ainda está lá. Por isso a existência é conferida do outro lado antes de ser
    reaproveitada.
    """
    cliente = Cliente()
    vinculo = armazenamento.obter_vinculo_agente(caso_id)
    if vinculo:
        existe = _caso_existe_no_agente(cliente, vinculo["caso_ref"])
        log.info(
            "diagnostico vinculo agente caso_id=%s case_ref=%s existe=%s enviados=%s",
            caso_id,
            vinculo["caso_ref"],
            existe,
            len(vinculo.get("enviados") or []),
        )
        if existe:
            return vinculo
        if _vinculo_recente(vinculo):
            log.warning(
                "vínculo recente do caso %s (%s): agente ainda não confirma existência; "
                "reutilizando sem recriar",
                caso_id,
                vinculo["caso_ref"],
            )
            return vinculo

    if vinculo:
        # Vínculo órfão: o caso existiu e não existe mais. Aconteceu de verdade na
        # migração do agente para o SQL Server — os casos ficaram no banco antigo e o
        # dossiê passou a abrir vazio, sem que nada aqui estivesse errado. Recriar do
        # lado de lá é o único caminho: `vincular_agente` troca o `caso_ref` e zera as
        # entregas enviadas, e o material volta a subir na próxima sincronização.
        log.warning(
            "vínculo órfão do caso %s: %s não existe mais no agente; recriando",
            caso_id,
            vinculo["caso_ref"],
        )

    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise ErroDoAgente("Caso não encontrado.")

    criado = cliente.criar_cliente(caso["cliente"])
    caso_criado = cliente.criar_caso(
        cliente_ref=criado["id"],
        titulo=_titulo(caso),
        jurisdicao=(jurisdicao or jurisdicao_padrao()) or None,
        descricao=caso.get("observacao") or None,
    )
    log.info("caso %s espelhado no agente como %s", caso_id, caso_criado["id"])
    return armazenamento.vincular_agente(caso_id, caso_criado["id"], criado["id"])


def _titulo(caso: dict[str, Any]) -> str:
    """Título legível do lado de lá: categoria e cliente.

    O agente exige ao menos três caracteres e mostra este texto na lista de casos —
    "acidente_trabalho_geral · Maria Santos" responde de quem é o caso sem abrir.
    """
    categoria = str(caso.get("categoria") or "caso").replace("_", " ")
    return f"{categoria} · {caso.get('cliente', '')}".strip(" ·")[:300]


# -------------------------------------------------------------- documentos


def _assinatura_extracao(extracao: dict[str, Any]) -> str:
    """Hash curto do JSON de extração — muda quando o OCR reprocessa o arquivo."""
    bruto = json.dumps(extracao, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(bruto.encode()).hexdigest()[:12]


def _chave_envio(entrega_id: str, extracao: dict[str, Any]) -> str:
    """Idempotência por versão da extração, não só pelo id da entrega."""
    return f"{entrega_id}:{_assinatura_extracao(extracao)}"


def _envio_registrado(vinculo: dict[str, Any], entrega_id: str, extracao: dict[str, Any]) -> bool:
    chave = _chave_envio(entrega_id, extracao)
    enviados = vinculo.get("enviados") or []
    return chave in enviados


def enviar_entrega(caso_id: str, entrega_id: str, *, silencioso: bool = True) -> bool:
    """Entrega ao agente uma extração já concluída. Silencioso por design.

    Chamado logo depois do OCR, em segundo plano: se o agente estiver fora do ar, o
    documento continua salvo aqui e o erro fica registrado no vínculo — o upload do
    cliente **não** pode falhar porque outro serviço caiu.
    """
    vinculo = armazenamento.obter_vinculo_agente(caso_id)
    if vinculo is None:
        return False

    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None or not entrega.get("extracao"):
        return False
    if entrega.get("status_proc") != "pronto":
        # Entrega em processamento ou com erro de leitura não tem o que promover a
        # fato; mandar assim faria o agente registrar documento sem campo nenhum.
        return False

    chave = _chave_envio(entrega_id, entrega["extracao"])
    if _envio_registrado(vinculo, entrega_id, entrega["extracao"]):
        return True

    origem = f"ocr://entregas/{entrega_id}/{entrega.get('arquivo', '')}"
    tipo = str((entrega["extracao"].get("tipo") or {}).get("codigo") or "").strip()
    evento_externo = chave

    try:
        cliente = Cliente()
        if tipo in extractors.ROTULOS_TIPO:
            cliente.enviar_extracao(
                vinculo["caso_ref"],
                evento_externo=evento_externo,
                origem=origem,
                extracao=entrega["extracao"],
            )
        else:
            # CNIS, CAT, PPP, ASO e outros documentos jurídicos não pertencem ao
            # contrato do OCR de identificação do agente. O Acervo sabe que o arquivo
            # chegou pelo item do checklist; portanto envia apenas essa declaração,
            # sem inventar campos extraídos nem ampliar artificialmente o OCR.
            caso = armazenamento.obter_caso(caso_id) or {}
            kind = vocabulario.kind_do_item(
                str(caso.get("categoria") or ""),
                str(entrega.get("item_codigo") or ""),
            )
            # Mesmo sem item conhecido no vocabulário, o conteúdo pertence ao caso e
            # precisa entrar na leitura/recuperação semântica da IA jurídica.
            generica = deepcopy(entrega["extracao"])
            generica.setdefault("tipo", {})["codigo"] = "desconhecido"
            generica["tipo"]["detectado"] = "desconhecido"
            cliente.enviar_extracao(
                vinculo["caso_ref"],
                evento_externo=evento_externo,
                origem=origem,
                extracao=generica,
            )
            if kind is not None:
                # O endpoint de extrações tem contrato fechado para documentos de
                # identificação. Enviamos uma cópia como tipo genérico para preservar
                # TODO o texto do anexo, gerar embeddings e permitir que o agente levante
                # fatos/alertas; em seguida a declaração atribui o tipo jurídico real ao
                # mesmo source_reference.
                cliente.declarar_documento(
                    vinculo["caso_ref"],
                    kind=kind,
                    arquivo=str(entrega.get("arquivo") or kind),
                    origem=origem,
                )
                log.info("entrega %s indexada e declarada ao agente como %s", entrega_id, kind)
            else:
                # Sem tipo jurídico seguro, permanece DOCUMENT.UNKNOWN — mas o texto,
                # embedding, fatos candidatos e proveniência já foram recebidos.
                log.info(
                    "entrega %s (%s) indexada sem tipo jurídico específico",
                    entrega_id,
                    tipo or "tipo ausente",
                )
    except ErroDoAgente as erro:
        log.warning("falha ao enviar entrega %s ao agente: %s", entrega_id, erro)
        armazenamento.registrar_erro_agente(caso_id, str(erro))
        if not silencioso:
            raise
        return False

    armazenamento.marcar_entrega_enviada(caso_id, chave)
    return True


def sincronizar(caso_id: str, *, jurisdicao: str | None = None) -> dict[str, Any]:
    """Garante o caso no agente e manda tudo que ainda não foi.

    É o que se chama ao abrir o dossiê: um caso antigo, cadastrado antes de a ligação
    existir, chega ao agente com todos os seus documentos de uma vez.
    """
    vinculo = garantir_caso(caso_id, jurisdicao=jurisdicao)
    log.info(
        "diagnostico sincronizacao iniciada caso_id=%s case_ref=%s",
        caso_id,
        vinculo["caso_ref"],
    )
    enviados, falhas = 0, 0

    for entrega in armazenamento.listar_entregas(caso_id):
        if entrega.get("status_proc") != "pronto" or not entrega.get("extracao"):
            continue
        if _envio_registrado(vinculo, entrega["id"], entrega["extracao"]):
            continue
        if enviar_entrega(caso_id, entrega["id"]):
            enviados += 1
        else:
            falhas += 1

    # Entrevista ainda não lida do outro lado também sobe aqui. É o que devolve os fatos
    # relatados ao caso recriado: o revínculo as reabre, e sem este laço elas ficariam
    # marcadas como pendentes para sempre, porque nada mais as reenvia sozinho.
    entrevistas, falhas_entrevista = 0, 0
    for entrevista in armazenamento.listar_entrevistas(caso_id):
        if entrevista.get("enviada"):
            continue
        try:
            resposta = enviar_entrevista(caso_id, entrevista["id"])
            if resposta.get("failure"):
                falhas_entrevista += 1
                armazenamento.registrar_erro_agente(
                    caso_id, f"Entrevista não lida: {resposta['failure']}"
                )
            else:
                entrevistas += 1
        except ErroDoAgente as erro:
            # Uma entrevista que não sobe não derruba a sincronização: os documentos já
            # foram, e a tela precisa abrir com o que existe.
            log.warning("entrevista %s não foi enviada: %s", entrevista["id"], erro)
            armazenamento.registrar_erro_agente(caso_id, f"Entrevista não lida: {erro}")
            falhas_entrevista += 1

    atual = armazenamento.obter_vinculo_agente(caso_id) or vinculo
    declarados = declarar_itens_entregues(caso_id, atual["caso_ref"])
    qualificar_reclamante(atual["caso_ref"])
    # O fluxo de petição por entrevista não usa mais classificar → pesquisar → estratégia
    # automáticos a cada sync — isso gerava 500 no agente e “Erro interno” na tela.
    pipeline = "fluxo_entrevista"
    if falhas == 0 and falhas_entrevista == 0:
        # Um erro antigo não pode permanecer para sempre quando tudo que estava
        # pendente já foi sincronizado (inclusive quando nenhum arquivo precisou ser
        # reenviado nesta abertura).
        armazenamento.registrar_erro_agente(caso_id, None)
        atual = armazenamento.obter_vinculo_agente(caso_id) or atual
    resultado = {
        "caso_ref": atual["caso_ref"],
        "cliente_ref": atual["cliente_ref"],
        "documentos_enviados": enviados,
        "documentos_com_falha": falhas,
        "entrevistas_enviadas": entrevistas,
        "entrevistas_com_falha": falhas_entrevista,
        "itens_declarados": declarados,
        "pipeline_juridico": pipeline,
        "ultimo_erro": atual.get("ultimo_erro"),
    }
    log.info(
        "diagnostico sincronizacao concluida caso_id=%s case_ref=%s docs_enviados=%s "
        "docs_falha=%s entrevistas_enviadas=%s entrevistas_falha=%s pipeline=%s",
        caso_id,
        atual["caso_ref"],
        enviados,
        falhas,
        entrevistas,
        falhas_entrevista,
        pipeline,
    )
    return resultado


def _retomar_pipeline_juridico(caso_ref: str, *, caso_id: str | None = None) -> str:
    """Enfileira a primeira etapa jurídica ausente de um caso já sincronizado.

    Cada worker encadeia o seguinte no agente (análise -> pesquisa -> estratégia).
    Casos antigos podem ter parado antes desse encadeamento existir; por isso o Acervo
    retoma explicitamente a primeira lacuna sempre que o dossiê é aberto.
    """
    agora = time.monotonic()
    with _retomadas_lock:
        if _retomadas_recentes.get(caso_ref, 0.0) > agora - _RETOMADA_TTL_S:
            return "aguardando"
        _retomadas_recentes[caso_ref] = agora

    cliente = Cliente()
    try:
        analise = cliente.analise(caso_ref)
        log.info(
            "diagnostico pipeline case_ref=%s etapa=classificacao quantidade=%s",
            caso_ref,
            len(analise.get("classifications") or []),
        )
        if not analise.get("classifications"):
            cliente.analisar(caso_ref)
            return "classificacao_enfileirada"

        pesquisas = cliente.pesquisas(caso_ref).get("items", [])
        recente = pesquisas[0] if pesquisas else None
        log.info(
            "diagnostico pipeline case_ref=%s etapa=jurisprudencia quantidade=%s status=%s",
            caso_ref,
            len(pesquisas),
            recente.get("status") if recente else "AUSENTE",
        )
        if recente and recente.get("status") == "RUNNING":
            return "jurisprudencia_em_andamento"
        if not recente or recente.get("status") != "COMPLETED":
            cliente.pesquisar(caso_ref)
            return "jurisprudencia_enfileirada"

        estrategia = cliente.estrategia(caso_ref)
        log.info(
            "diagnostico pipeline case_ref=%s etapa=estrategia existe=%s",
            caso_ref,
            estrategia is not None,
        )
        if estrategia is None:
            gerar_estrategia = getattr(cliente, "gerar_estrategia", None)
            if not callable(gerar_estrategia):
                return "estrategia_indisponivel"
            gerar_estrategia(caso_ref)
            return "estrategia_enfileirada"
        return "completo"
    except ErroDoAgente as erro:
        # Os documentos continuam disponíveis mesmo se o serviço jurídico oscilar.
        # Retiramos a trava para permitir nova tentativa no próximo refresh.
        with _retomadas_lock:
            _retomadas_recentes.pop(caso_ref, None)
        if erro.status == 404 and caso_id:
            log.warning(
                "pipeline do case_ref %s aponta para caso morto; revinculando %s",
                caso_ref,
                caso_id,
            )
            try:
                novo = garantir_caso(caso_id)
            except ErroDoAgente:
                log.warning(
                    "não foi possível retomar o pipeline do caso %s: %s", caso_ref, erro
                )
                return "indisponivel"
            if novo["caso_ref"] != caso_ref:
                return _retomar_pipeline_juridico(novo["caso_ref"], caso_id=caso_id)
        log.warning("não foi possível retomar o pipeline do caso %s: %s", caso_ref, erro)
        return "indisponivel"


def caso_ref(caso_id: str) -> str:
    """O caso correspondente no agente, criando-o se for a primeira vez.

    Criar aqui é deliberado: quem pergunta ao agente sobre um caso quer a resposta, não
    uma mensagem dizendo que precisa antes clicar em outro botão.

    O vínculo guardado **não** serve como atalho: ele diz que o caso foi criado, não que
    ele ainda existe. Confiar nele fazia toda ação apontar para um caso morto depois de o
    agente trocar de banco, e o advogado recebia "caso não encontrado" sem nada que
    pudesse fazer na tela. `garantir_caso` custa uma leitura e resolve o caso comum; a
    sincronização completa só roda quando o caso teve mesmo de ser recriado.

    Levanta `ErroDoAgente`, e não `HTTPException`: quem chama decide o que fazer com a
    indisponibilidade. Na conversa geral, por exemplo, ela vira mensagem NA transcrição —
    transformá-la em erro de tela apagaria a conversa inteira por causa de uma resposta.
    """
    anterior = armazenamento.obter_vinculo_agente(caso_id)
    vinculo = garantir_caso(caso_id)
    if anterior is None or anterior["caso_ref"] != vinculo["caso_ref"]:
        return str(sincronizar(caso_id)["caso_ref"])
    return str(vinculo["caso_ref"])


def declarar_itens_entregues(caso_id: str, caso_ref: str) -> int:
    """Informa ao agente quais itens do checklist já chegaram ao escritório.

    O OCR classifica nove tipos de imagem; o playbook exige dezesseis documentos. CAT, CNIS,
    PPP, ASO e laudo pericial entram por aqui — pela **declaração** de que foram entregues,
    que é o que o Acervo sabe com certeza. Sem isso o caso mantinha as pendências
    indispensáveis abertas para sempre e a petição jamais era liberada.

    Declarar não é ler: nenhum fato nasce daqui. O que muda é o checklist.

    `origem` é **de propósito** igual ao de `enviar_extracao`: o agente deduplica documento
    pelo `source_reference`, e uma entrega que já foi extraída (RG, CPF, CTPS...) não pode
    virar um segundo registro só porque também tem `document_kind` no vocabulário — usar uma
    chave diferente aqui criava dois "documentos" para o mesmo arquivo físico, um por
    extração e outro por declaração, e o advogado via o dobro do que o escritório recebeu.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return 0

    categoria = str(caso.get("categoria") or "")
    cliente = Cliente()
    declarados = 0

    for entrega in armazenamento.listar_entregas(caso_id):
        if entrega.get("status_proc") != "pronto":
            continue
        kind = vocabulario.kind_do_item(categoria, str(entrega.get("item_codigo") or ""))
        if kind is None:
            continue
        try:
            cliente.declarar_documento(
                caso_ref,
                kind=kind,
                arquivo=str(entrega.get("arquivo") or kind),
                # Mesma chave que `enviar_entrega` usa para a extração — é o que faz o
                # agente reconhecer "já tenho este arquivo" em vez de duplicar.
                origem=f"ocr://entregas/{entrega['id']}/{entrega.get('arquivo', '')}",
            )
        except ErroDoAgente as erro:
            log.warning("não foi possível declarar %s: %s", kind, erro)
            continue
        declarados += 1
    return declarados


def enviar_entrevista(caso_id: str, entrevista_id: str) -> dict[str, Any]:
    """Manda ao agente a entrevista guardada aqui, uma vez só.

    Idempotente pelo `enviada_em` do registro local: reenviar criaria uma segunda leva de
    fatos alegados idênticos, e o detector de contradições passaria a acusar o cliente de se
    contradizer com ele mesmo.
    """
    registro = armazenamento.obter_entrevista(entrevista_id)
    if registro is None or registro["caso_id"] != caso_id:
        raise ErroDoAgente("Entrevista não encontrada neste caso.")
    if registro["enviada"]:
        return {"ja_enviada": True, "fatos_gerados": registro["fatos_gerados"]}

    vinculo = garantir_caso(caso_id)
    resposta = Cliente().enviar_entrevista(
        vinculo["caso_ref"],
        # O agente pode recriar um caso depois de migração/restauração. O id local
        # sozinho continuaria globalmente preso ao case_ref antigo e o novo caso receberia
        # INTERVIEW_CASE_MISMATCH para sempre. Vincular a chave idempotente ao caso remoto
        # permite a recuperação sem duplicar a entrevista dentro do mesmo caso.
        entrevista_id=f"{vinculo['caso_ref']}:{entrevista_id}",
        transcricao=registro["texto"],
        realizada_em=registro["realizada_em"],
        entrevistador=registro["entrevistador"],
    )

    falha = str(resposta.get("failure") or "")
    if falha:
        # Leitura não aconteceu (sem provedor, transcrição vazia). O arquivo continua aqui e
        # a entrevista **não** é marcada como lida: dá para tentar de novo.
        armazenamento.registrar_erro_agente(caso_id, f"entrevista não lida: {falha}")
        return dict(resposta)

    armazenamento.marcar_entrevista_lida(
        entrevista_id,
        resumo=str(resposta.get("summary") or ""),
        perguntas=[str(item) for item in (resposta.get("open_questions") or [])],
        fatos_gerados=int(resposta.get("facts_recorded") or 0),
    )
    # O CPF costuma aparecer aqui pela primeira vez — o cliente o diz no atendimento, e o
    # agente o lê por código (a política de redação impede que ele chegue ao modelo). Sem
    # esta chamada a parte só seria qualificada na próxima sincronização, e até lá a peça
    # ficaria barrada por falta de um dado que o caso já tem.
    qualificar_reclamante(vinculo["caso_ref"])
    return dict(resposta)


def qualificar_reclamante(caso_ref: str) -> str | None:
    """Copia para a parte reclamante o CPF que os documentos revelaram.

    O caso nasce aqui com o nome que o cliente disse no atendimento; o CPF só existe
    depois que a CTPS ou o RG passam pelo OCR. Sem esta costura a parte fica sem
    documento para sempre e o readiness do agente barra a petição de **todo** caso
    vindo do escritório — bloqueio correto (`§21`: qualificação incompleta trava a
    peça), causa boba.

    Não sobrescreve documento já preenchido: quem digitou vence o que foi lido.
    Devolve o CPF aplicado, ou `None` quando não havia o que fazer.
    """
    cliente = Cliente()
    try:
        caso = cliente.caso(caso_ref)
        partes = [p for p in caso.get("parties", []) if p.get("role") == "CLAIMANT"]
        if not partes or partes[0].get("document"):
            return None

        cpf = _cpf_apurado(cliente.fatos(caso_ref).get("items", []))
        if cpf is None:
            return None

        cliente.qualificar_parte(caso_ref, partes[0]["id"], documento=cpf)
    except ErroDoAgente as erro:
        # Sincronizar é chamado ao abrir o dossiê: falhar aqui esconderia o caso inteiro
        # por causa de um campo. O readiness dirá o que falta, com o nome certo.
        log.warning("não foi possível qualificar a parte do caso %s: %s", caso_ref, erro)
        return None
    else:
        log.info("parte reclamante do caso %s qualificada com o CPF apurado", caso_ref)
        return cpf


#: Precedência do CPF que qualifica a parte. Conferido por humano vence lido de documento,
#: que vence o que o cliente informou no atendimento. `ALLEGED` entra porque é assim que o
#: escritório trabalha — a ficha nasce do que o cliente disse —, e porque o número passou
#: por dígito verificador antes de virar fato; se estiver errado, o documento corrige depois.
_PRECEDENCIA_CPF = {"CONFIRMED": 3, "EXTRACTED": 2, "ALLEGED": 1}


def _cpf_apurado(fatos: list[dict[str, Any]]) -> str | None:
    """O CPF de fato do caso. Rejeitado e superado não contam."""
    melhor: tuple[int, str] | None = None
    for fato in fatos:
        if fato.get("type") != "PERSON.CPF":
            continue
        peso = _PRECEDENCIA_CPF.get(str(fato.get("status")))
        if peso is None:
            continue
        digitos = str((fato.get("value") or {}).get("digits") or "").strip()
        if not digitos:
            continue
        if melhor is None or peso > melhor[0]:
            melhor = (peso, digitos[:20])
    return melhor[1] if melhor else None


# ---------------------------------------------------------------- contrato


#: Campo do contrato → tipo de fato do agente e a chave onde o valor mora.
#: Só o que dá para comparar sem interpretação: nome, CPF, RG e nascimento. Endereço
#: fica de fora porque "Rua X, 10, ap 2" e "Rua X nº 10 apto 2" são o mesmo endereço
#: e a comparação acusaria divergência onde não há.
CAMPOS_CONFERIDOS: dict[str, tuple[str, str]] = {
    "nome da pessoa": ("PERSON.NAME", "full_name"),
    "cpf": ("PERSON.CPF", "digits"),
    "rg numero": ("PERSON.RG", "number"),
    "data de nascimento": ("PERSON.BIRTH_DATE", "date"),
}


def conferir_contrato(caso_id: str, campos: dict[str, Any]) -> dict[str, Any]:
    """Compara a qualificação do contrato com os fatos que o agente apurou.

    O contrato é digitado a partir da entrevista; os fatos vêm dos documentos lidos.
    Quando os dois discordam sobre o CPF, um deles está errado — e descobrir isso
    **antes** da assinatura custa uma conferência, depois custa um aditivo.

    A qualificação não vira fato de propósito: os documentos já produzem esses
    mesmos fatos com proveniência (página, campo do OCR, confiança). Registrar de
    novo pelo contrato criaria uma segunda versão da mesma verdade, sem origem
    conferível, que é o que o `§2.2` proíbe.
    """
    vinculo = armazenamento.obter_vinculo_agente(caso_id)
    if vinculo is None:
        return {"disponivel": False, "motivo": "caso ainda não enviado ao agente"}

    try:
        fatos = Cliente().fatos(vinculo["caso_ref"]).get("items", [])
    except AgenteIndisponivel as erro:
        return {"disponivel": False, "motivo": str(erro)}

    por_tipo: dict[str, Any] = {}
    for fato in fatos:
        # O primeiro de cada tipo basta: a lista já vem do mais recente e os
        # superados não aparecem.
        por_tipo.setdefault(str(fato.get("type")), fato)

    divergencias: list[dict[str, Any]] = []
    conferidos: list[str] = []

    for campo, (tipo, chave) in CAMPOS_CONFERIDOS.items():
        no_contrato = str(campos.get(campo) or "").strip()
        fato = por_tipo.get(tipo)
        if not no_contrato or fato is None:
            continue

        no_agente = str((fato.get("value") or {}).get(chave) or "").strip()
        if not no_agente:
            continue

        if _comparavel(no_contrato) == _comparavel(no_agente):
            conferidos.append(campo)
            continue

        divergencias.append(
            {
                "campo": campo,
                "no_contrato": no_contrato,
                "nos_documentos": no_agente,
                "tipo_de_fato": tipo,
                # A proveniência é o que permite ao advogado abrir o documento e
                # decidir quem está certo, em vez de escolher no palpite.
                "origem": fato.get("sources") or fato.get("source_types"),
            }
        )

    return {
        "disponivel": True,
        "conferidos": conferidos,
        "divergencias": divergencias,
        "fatos_comparaveis": len(conferidos) + len(divergencias),
    }


def _comparavel(valor: str) -> str:
    """Forma para comparar o que o humano digitou com o que o OCR leu.

    Sem acento, sem caixa e sem pontuação: `123.456.789-00` e `12345678900` são o
    mesmo CPF, e `MARIA SANTOS` é a mesma pessoa que `Maria Santos`. Data também
    normaliza, porque o contrato traz `15/03/1990` e o fato guarda `1990-03-15`.
    """
    texto = unicodedata.normalize("NFKD", valor.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    limpo = valor.strip()
    somente_digitos = re.sub(r"\D", "", texto)

    if len(somente_digitos) == 8 and re.fullmatch(r"[\d/.\-\s]+", limpo):
        # Data. O contrato traz `15/03/1990`, o fato guarda `1990-03-15` — a mesma
        # data. Quem diz qual é qual é o **separador no texto original**: quatro
        # dígitos antes dele significam ano na frente. Olhar só para os dígitos não
        # resolveria, porque `15031990` também "começa com quatro dígitos".
        iso = bool(re.match(r"^\d{4}\D", limpo))
        return somente_digitos if iso else somente_digitos[4:] + somente_digitos[2:4] + somente_digitos[:2]

    if somente_digitos and not re.search(r"[a-z]", texto):
        return somente_digitos
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


# ------------------------------------------------- leitura combinada do caso


#: Quanto se espera a classificação ficar pronta antes de pedir a jurisprudência.
#:
#: A análise responde 202 e roda do outro lado; a pesquisa sai "a partir das questões
#: do caso", e essas questões são produto dela. Disparar as duas juntas faria a
#: jurisprudência ser pesquisada antes de existir pergunta — e voltar vazia, que é
#: pior que não ter rodado, porque parece resposta.
ESPERA_ANALISE_S = 5.0
TENTATIVAS_ANALISE = 12


def analisar_caso_inteiro(caso_id: str) -> dict[str, Any]:
    """Classifica o caso com TUDO que ele tem, e então pesquisa a jurisprudência.

    O QUE ISTO JUNTA

    Nada aqui produz fato novo. A esta altura o agente já recebeu, por caminhos
    separados e automáticos, as duas fontes que importam: cada extração de documento
    (`enviar_entrega`) e a transcrição do atendimento (`enviar_entrevista`). Elas
    convivem na mesma base de fatos, distinguidas pela proveniência — `ocr_document`
    de um lado, `interview` do outro.

    O que faltava era o passo que LÊ as duas juntas. A classificação e as pendências
    saem dos fatos do caso, sem separar de onde vieram; a pesquisa sai das questões
    que a classificação levantou. Até agora esse passo só acontecia se alguém
    clicasse em "Classificar o caso" e depois em "Pesquisar jurisprudência", na tela
    do dossiê — e no fim de um atendimento ninguém clica: o cliente acabou de sair,
    o advogado foi para o próximo.

    POR QUE ESPERAR ENTRE UMA COISA E OUTRA

    Ver `ESPERA_ANALISE_S`. Se a classificação não ficar pronta a tempo, a pesquisa
    NÃO é disparada: o botão continua na tela, e uma pesquisa sem questão nenhuma
    voltaria vazia parecendo resposta.
    """
    vinculo = garantir_caso(caso_id)
    caso_ref = vinculo["caso_ref"]
    cliente = Cliente()

    resultado: dict[str, Any] = {"caso_ref": caso_ref, "analise": False, "pesquisa": False}
    cliente.analisar(caso_ref)
    resultado["analise"] = True

    for _ in range(TENTATIVAS_ANALISE):
        time.sleep(ESPERA_ANALISE_S)
        try:
            analise = cliente.analise(caso_ref)
        except ErroDoAgente:
            # Leitura falhou no meio; a análise pode estar rodando ainda. Tentar de
            # novo é barato, e desistir aqui perderia a pesquisa por um soluço de rede.
            continue
        if analise.get("classifications"):
            cliente.pesquisar(caso_ref)
            resultado["pesquisa"] = True
            resultado["classificacoes"] = len(analise["classifications"])
            return resultado

    log.info(
        "caso %s: classificação não ficou pronta em %.0fs — jurisprudência não foi "
        "pedida, o botão do dossiê continua valendo",
        caso_id,
        ESPERA_ANALISE_S * TENTATIVAS_ANALISE,
    )
    return resultado


def garantir_preparo_juridico(caso_id: str) -> dict[str, Any]:
    """Sincroniza documentos e enfileira classificação/pesquisa quando faltam.

    Usado antes de estratégia e petição: responde rápido e deixa a espera no worker.
    """
    vinculo = garantir_caso(caso_id)
    caso_ref = vinculo["caso_ref"]
    cliente = Cliente()

    resultado: dict[str, Any] = {
        "caso_ref": caso_ref,
        "classificacao": False,
        "pesquisa": False,
    }

    # Documentos novos ou reprocessados entram antes da classificação.
    sincronizacao = sincronizar(caso_id)
    retomada = str(sincronizacao.get("pipeline_juridico") or "")
    qualificar_reclamante(caso_ref)

    try:
        analise = cliente.analise(caso_ref)
    except ErroDoAgente:
        analise = {}

    if analise.get("classifications"):
        resultado["classificacao"] = True
        resultado["classificacoes"] = len(analise["classifications"])
    else:
        if retomada not in {"classificacao_enfileirada", "aguardando"}:
            cliente.analisar(caso_ref)
        resultado["analise_enfileirada"] = True

    try:
        pesquisas = cliente.pesquisas(caso_ref).get("items", [])
    except ErroDoAgente:
        pesquisas = []

    if pesquisas and pesquisas[0].get("status") == "COMPLETED":
        resultado["pesquisa"] = True
        return resultado

    recente = pesquisas[0] if pesquisas else None
    if recente and recente.get("status") == "RUNNING":
        resultado["pesquisa_enfileirada"] = True
        return resultado

    if resultado.get("classificacao") and retomada not in {
        "jurisprudencia_enfileirada",
        "jurisprudencia_em_andamento",
        "aguardando",
    }:
        cliente.pesquisar(caso_ref)
    resultado["pesquisa_enfileirada"] = True
    return resultado


def garantir_pesquisa_para_peca(caso_id: str) -> dict[str, Any]:
    """Alias de `garantir_preparo_juridico` — mantido para rotas e testes existentes."""
    return garantir_preparo_juridico(caso_id)
