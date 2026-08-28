"""Cliente HTTP do agente jurídico.

Fala com o backend do `ia-juridica`, que é quem guarda o Case State: fatos com
proveniência, classificação, pendências e pesquisa de jurisprudência. **Este módulo
não decide nada** — traduz chamada em HTTP e erro em erro tipado.

Duas regras que ele existe para garantir:

- **indisponibilidade é erro explícito.** Agente fora do ar não pode virar "o caso não
  tem fato nenhum" na tela do advogado: as duas coisas se parecem e levam a decisões
  opostas;
- **o OCR nunca fica preso.** Prazos curtos no que o advogado espera olhando, prazo
  folgado só no envio de documento, que roda em segundo plano.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

from . import motivos
from .config import Config, config

log = logging.getLogger("agente")

_CASE_REF_RE = re.compile(r"^case_[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)

__all__ = [
    "AgenteIndisponivel",
    "AgenteNaoConfigurado",
    "ErroDoAgente",
    "Cliente",
    "caso_ref_valido",
]


def caso_ref_valido(caso_ref: str) -> bool:
    """Identificador público de caso aceito pelo agente."""
    return bool(_CASE_REF_RE.fullmatch(caso_ref.strip()))


#: Pool de conexões compartilhado por todas as chamadas ao agente.
#:
#: `httpx.request()` solto abre e derruba uma conexão TCP a cada leitura, e o dossiê faz
#: sete delas para montar uma tela. O pool guarda a conexão aberta entre as chamadas —
#: o mesmo motivo pelo qual um navegador não reabre a conexão a cada imagem da página.
#:
#: Só o transporte é compartilhado: endereço, token e prazo continuam vindo de `Config`
#: a cada chamada, senão trocar `.env` exigiria reiniciar o processo.
_pool: httpx.Client | None = None
_pool_mu = threading.Lock()


def _cliente_http() -> httpx.Client:
    global _pool
    if _pool is None:
        with _pool_mu:
            if _pool is None:
                _pool = httpx.Client(
                    limits=httpx.Limits(
                        max_keepalive_connections=10, max_connections=20
                    )
                )
    return _pool


#: Memória curta de "o agente não respondeu".
#:
#: Uma tela do dossiê faz seis leituras. Com o agente fora do ar e sem esta memória, as
#: seis esperam o prazo inteiro cada uma para chegar à mesma conclusão — o advogado fica
#: minutos olhando um carregamento para ler "agente indisponível". Aqui a primeira falha
#: responde pelas seguintes durante `pausa_apos_falha`, e qualquer resposta boa apaga a
#: marca na hora.
#:
#: Só as **leituras** consultam esta memória. Envio de documento e disparo de análise
#: passam direto: são operações do fluxo de trabalho, não da tela, e desistir delas
#: porque uma consulta falhou há dez segundos perderia trabalho de verdade.
_falha_ate: float = 0.0
_falha_motivo: str = ""
_falha_mu = threading.Lock()


def _em_pausa() -> str | None:
    """O motivo registrado, enquanto a pausa durar. `None` quando é para tentar."""
    with _falha_mu:
        if _falha_ate and time.monotonic() < _falha_ate:
            return _falha_motivo
    return None


def _marcar_falha(motivo: str, pausa: float) -> None:
    global _falha_ate, _falha_motivo
    with _falha_mu:
        _falha_ate = time.monotonic() + pausa
        _falha_motivo = motivo


def _marcar_resposta() -> None:
    """O agente respondeu — a pausa morre aqui, sem esperar o relógio."""
    global _falha_ate, _falha_motivo
    if not _falha_ate:
        return
    with _falha_mu:
        _falha_ate = 0.0
        _falha_motivo = ""


class ErroDoAgente(RuntimeError):
    """Falha que o advogado precisa ver, com o texto que o agente devolveu.

    `status` é o código HTTP quando houve resposta, e `None` quando o erro nasceu antes
    dela (rede, configuração). Ele existe para distinguir *o caso não existe* de *o agente
    recusou o pedido* sem depender do texto da mensagem — comparação de frase quebra na
    primeira vez que alguém melhora a redação do erro.
    """

    def __init__(self, mensagem: str, *, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


class AgenteNaoConfigurado(ErroDoAgente):
    """Sem `AGENTE_API_URL`. A tela explica; o atendimento não para."""


class AgenteIndisponivel(ErroDoAgente):
    """Fora do ar, sem rede ou estourou o prazo. Nunca confundir com "não há dados"."""


class Cliente:
    def __init__(self, cfg: Config | None = None) -> None:
        self._cfg = cfg or config()
        if not self._cfg.ligado:
            raise AgenteNaoConfigurado(
                "Agente jurídico não configurado (AGENTE_API_URL vazio)."
            )

    # ------------------------------------------------------------------ básico

    def _cabecalhos(self) -> dict[str, str]:
        if not self._cfg.token:
            return {}
        return {"Authorization": f"Bearer {self._cfg.token}"}

    def _ler(self, caminho: str) -> Any:
        """Consulta que monta tela: prazo curto e sujeita à pausa após falha.

        `timeout` fica `None` aqui de propósito — quem resolve o valor default é
        `_chamar`, não este método. Um dublê de teste que sobrescreve `_chamar` sem
        montar `self._cfg` (há um assim em `test_agente.py`) quebraria se `_ler`
        lesse `self._cfg` antes de chamar o método que ele substitui.
        """
        return self._chamar("GET", caminho, de_tela=True)

    def _chamar(
        self,
        metodo: str,
        caminho: str,
        *,
        json: Any = None,
        timeout: float | None = None,
        de_tela: bool = False,
    ) -> Any:
        url = f"{self._cfg.url}{caminho}"

        if de_tela:
            motivo = _em_pausa()
            if motivo is not None:
                raise AgenteIndisponivel(motivo)

        try:
            resposta = _cliente_http().request(
                metodo,
                url,
                json=json,
                headers=self._cabecalhos(),
                timeout=timeout or (self._cfg.timeout_leitura if de_tela else self._cfg.timeout),
            )
        except httpx.HTTPError as erro:
            # Rede, DNS, prazo. O agente pode estar subindo, o banco dele pode estar
            # fora — de todo jeito, não olhamos o caso.
            log.warning("agente indisponível em %s: %s", url, erro)
            recado = (
                "O agente jurídico não respondeu. O caso continua no OCR; "
                "a análise fica pendente até ele voltar."
            )
            _marcar_falha(recado, self._cfg.pausa_apos_falha)
            raise AgenteIndisponivel(recado) from erro

        # Respondeu — inclusive com 4xx, que é o agente vivo recusando o pedido.
        _marcar_resposta()

        if resposta.status_code >= 400:
            raise ErroDoAgente(_detalhe(resposta), status=resposta.status_code)
        if resposta.status_code == 204 or not resposta.content:
            return None
        return resposta.json()

    # ---------------------------------------------------------------- clientes

    def criar_cliente(self, nome: str, *, documento: str | None = None) -> dict[str, Any]:
        return self._chamar(
            "POST",
            "/api/v1/clients",
            json={"full_name": nome, "document": documento},
        )

    # ------------------------------------------------------------------- casos

    def criar_caso(
        self,
        *,
        cliente_ref: str,
        titulo: str,
        jurisdicao: str | None = None,
        descricao: str | None = None,
    ) -> dict[str, Any]:
        return self._chamar(
            "POST",
            "/api/v1/cases",
            json={
                "client_id": cliente_ref,
                "title": titulo,
                "jurisdiction": jurisdicao,
                "description": descricao,
            },
        )

    def caso(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}")

    def caso_existe(self, caso_ref: str) -> bool:
        """O caso ainda está lá?

        Só o 404 vira `False`. Agente fora do ar continua subindo `AgenteIndisponivel`, e
        é isso que se quer: quem chama usa esta resposta para decidir recriar o caso, e
        tratar indisponibilidade como ausência criaria um caso novo — com metade dos
        documentos — a cada oscilação de rede.
        """
        if not caso_ref_valido(caso_ref):
            return False
        try:
            self.caso(caso_ref)
        except AgenteIndisponivel:
            raise
        except ErroDoAgente as erro:
            if erro.status == 404 or "Identificador inválido" in str(erro):
                return False
            raise
        return True

    def qualificar_parte(
        self, caso_ref: str, parte_ref: str, *, documento: str
    ) -> dict[str, Any]:
        """Completa o CPF da parte depois que os documentos revelaram qual é."""
        return self._chamar(
            "PATCH",
            f"/api/v1/cases/{caso_ref}/parties/{parte_ref}",
            json={"document": documento},
        )

    def estado_do_caso(self, caso_ref: str, *, secoes: str | None = None) -> dict[str, Any]:
        sufixo = f"?include={secoes}" if secoes else ""
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/state{sufixo}")

    def fatos(self, caso_ref: str) -> dict[str, Any]:
        return self._listar_paginas(f"/api/v1/cases/{caso_ref}/facts", limite=100)

    def contradicoes(self, caso_ref: str) -> dict[str, Any]:
        return self._listar_paginas(
            f"/api/v1/cases/{caso_ref}/contradictions", limite=100
        )

    def _listar_paginas(self, caminho: str, *, limite: int) -> dict[str, Any]:
        """Lê uma coleção inteira sem tratar a primeira página como o caso completo.

        Fatos antigos continuam relevantes para detectar documentos conflitantes. Se
        a API parar de avançar antes do total declarado, falhamos explicitamente em
        vez de devolver um estado parcial que poderia autorizar um contrato incorreto.
        """
        itens: list[Any] = []
        resposta_final: dict[str, Any] | None = None
        offset = 0
        paginas_vistas: set[tuple[str, ...]] = set()

        while True:
            pagina = self._ler(f"{caminho}?limit={limite}&offset={offset}")
            if not isinstance(pagina, dict) or not isinstance(pagina.get("items"), list):
                raise ErroDoAgente("O agente devolveu uma lista paginada inválida.")

            if resposta_final is None:
                resposta_final = dict(pagina)

            lote = pagina["items"]
            assinatura = tuple(
                str(item.get("id"))
                if isinstance(item, dict) and item.get("id") is not None
                else repr(item)
                for item in lote
            )
            if lote and assinatura in paginas_vistas:
                raise ErroDoAgente(
                    "O agente não conseguiu concluir a paginação do caso."
                )
            paginas_vistas.add(assinatura)
            itens.extend(lote)

            try:
                total = int(pagina.get("total", len(itens)))
            except (TypeError, ValueError) as exc:
                raise ErroDoAgente(
                    "O agente devolveu um total de paginação inválido."
                ) from exc
            if total < 0:
                raise ErroDoAgente("O agente devolveu um total de paginação inválido.")
            if len(itens) >= total:
                break
            if not lote:
                raise ErroDoAgente(
                    "O agente não conseguiu concluir a paginação do caso."
                )
            offset += len(lote)

        assert resposta_final is not None
        resposta_final.update(
            {"items": itens, "total": len(itens), "limit": limite, "offset": 0}
        )
        return resposta_final

    # --------------------------------------------------------------- documentos

    def enviar_extracao(
        self,
        caso_ref: str,
        *,
        evento_externo: str,
        origem: str,
        extracao: dict[str, Any],
    ) -> dict[str, Any]:
        """Entrega ao agente o JSON que o OCR já produziu, sem reformatá-lo.

        `evento_externo` é a chave de idempotência do outro lado: reenviar a mesma
        entrega não cria documento duplicado. Por isso é o id da entrega, e não um
        identificador sorteado na hora.
        """
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/documents/extractions",
            json={
                "external_event_id": evento_externo,
                "source_reference": origem,
                "payload": extracao,
                "schema_version": "1.0",
            },
            timeout=self._cfg.timeout_envio,
        )

    def enviar_entrevista(
        self,
        caso_ref: str,
        *,
        entrevista_id: str,
        transcricao: str,
        realizada_em: str = "",
        entrevistador: str = "",
    ) -> dict[str, Any]:
        """Manda a transcrição para virar fato **alegado**, com origem na entrevista.

        Prazo do envio, e não o da tela: a leitura é uma chamada de modelo sobre um texto
        que pode ter dez páginas.
        """
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/interviews",
            json={
                "interview_id": entrevista_id,
                "transcript": transcricao,
                "occurred_at": realizada_em,
                "interviewer": entrevistador,
            },
            timeout=self._cfg.timeout_envio,
        )

    def declarar_documento(
        self, caso_ref: str, *, kind: str, arquivo: str, origem: str
    ) -> dict[str, Any]:
        """Diz ao agente que um documento do checklist chegou, sem passar por OCR.

        É o que baixa a pendência do playbook para CAT, CNIS, PPP e laudos — documentos que
        nenhum classificador de imagem reconhece.
        """
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/documents/received",
            json={"kind": kind, "filename": arquivo, "source_reference": origem},
        )

    def documentos(self, caso_ref: str) -> dict[str, Any]:
        # A proveniência de um fato pode apontar para o 21º anexo. Ler só a primeira
        # página faria a tela saber o fato, mas não conseguir abrir justamente a prova.
        return self._listar_paginas(f"/api/v1/cases/{caso_ref}/documents", limite=100)

    # ------------------------------------------------------------- análise

    def analisar(self, caso_ref: str) -> dict[str, Any]:
        """Dispara classificação e apuração de pendências. Responde na hora, roda depois."""
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/analysis")

    def analise(self, caso_ref: str) -> dict[str, Any]:
        return self._ler(f"/api/v1/cases/{caso_ref}/analysis")

    # ----------------------------------------------------------- chat do caso

    def perguntar_ao_caso(
        self, caso_ref: str, *, mensagem: str, conversa_ref: str | None = None
    ) -> dict[str, Any]:
        """Pergunta ao agente com o estado deste caso, e só dele.

        Síncrona de propósito, ao contrário da análise e da pesquisa: quem perguntou está
        olhando a conversa esperando a resposta, e um `202` com identificador de execução
        não é resposta nenhuma num chat.

        O `conversa_ref` é o fio do raciocínio do outro lado. Sem ele, cada pergunta
        recomeça do zero e "e quanto ao PPP?" vira uma pergunta sem sujeito.
        """
        corpo: dict[str, Any] = {"message": mensagem}
        if conversa_ref:
            corpo["conversation_id"] = conversa_ref
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/chat", json=corpo)

    def conversa_do_caso(self, caso_ref: str, conversa_ref: str) -> dict[str, Any]:
        """A transcrição que o agente guarda daquele fio, para reabrir a conversa."""
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/chat/{conversa_ref}")

    def confirmar_proposta(self, caso_ref: str, proposta_ref: str) -> dict[str, Any]:
        """Aplica a alteração proposta — só depois da confirmação explícita do advogado.

        É o único caminho pelo qual uma conversa altera o caso (`AGENTS.md §2.4`): o
        agente propõe com o antes e o depois, e nada acontece até alguém clicar.
        """
        return self._chamar(
            "POST", f"/api/v1/cases/{caso_ref}/chat/proposals/{proposta_ref}/confirm"
        )

    # ------------------------------------------------------------- pesquisa

    def pesquisar(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/research")

    def pesquisas(self, caso_ref: str) -> dict[str, Any]:
        return self._ler(f"/api/v1/cases/{caso_ref}/research")

    def pesquisa(self, caso_ref: str, pesquisa_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/research/{pesquisa_ref}")

    # ----------------------------------------------------------- jurimetria

    def jurimetria(self, caso_ref: str, *, orgao: str | None = None) -> dict[str, Any]:
        """Como o foro decide a matéria deste caso, e onde o caso cai dentro disso.

        Leitura direta: do outro lado são agregações no acervo, sem chamada de modelo.
        Prender a tela num 202 aqui seria burocracia sem ganho.

        O `orgao` é opcional porque o Acervo não guarda a vara em campo próprio. Quando o
        advogado informa, a comparação deixa de ser com a jurisdição inteira e passa a ser
        com quem vai julgar.
        """
        caminho = f"/api/v1/cases/{caso_ref}/jurimetrics"
        if orgao:
            caminho += f"?judging_body={quote(orgao)}"
        return self._chamar("GET", caminho)

    def jurimetria_do_acervo(self, filtros: dict[str, Any] | None = None) -> dict[str, Any]:
        """O mesmo painel sem caso: o retrato do acervo por recorte livre."""
        parametros: list[str] = []
        for chave, valor in (filtros or {}).items():
            if valor in (None, "", [], ()):
                continue
            for item in valor if isinstance(valor, list | tuple) else [valor]:
                parametros.append(f"{chave}={quote(str(item))}")
        sufixo = "?" + "&".join(parametros) if parametros else ""
        return self._chamar("GET", f"/api/v1/jurimetrics/panel{sufixo}")

    def linhas_argumentativas(self, caso_ref: str) -> dict[str, Any]:
        """Dispara a leitura das razões de decidir do recorte comparável deste caso.

        A jurimetria conta; esta leitura diz com que fundamento — cada linha vem ancorada
        nos processos que a sustentam. Roda por pedido explícito, como estratégia e
        pesquisa: chama modelo do outro lado.
        """
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/jurimetrics/argument-lines")

    def linhas_argumentativas_resultado(self, caso_ref: str) -> dict[str, Any] | None:
        """A leitura mais recente, ou `None` quando ainda não foi pedida.

        Ausência aqui é estado normal do caso, não erro — mesma régua de `estrategia()`.
        """
        try:
            return self._ler(f"/api/v1/cases/{caso_ref}/jurimetrics/argument-lines")
        except ErroDoAgente as erro:
            if erro.status == 404:
                return None
            raise

    def contra_tese(self, caso_ref: str, hipotese_ref: str) -> dict[str, Any]:
        """Dispara o argumento provável do outro lado contra a hipótese indicada.

        Exige uma hipótese aceita na Estratégia — a tese a atacar é escolha do advogado.
        """
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/jurimetrics/adversarial",
            json={"hypothesis_id": hipotese_ref},
        )

    def contra_tese_resultado(self, caso_ref: str) -> dict[str, Any] | None:
        try:
            return self._ler(f"/api/v1/cases/{caso_ref}/jurimetrics/adversarial")
        except ErroDoAgente as erro:
            if erro.status == 404:
                return None
            raise

    def resolver_contradicao(
        self,
        caso_ref: str,
        contradicao_ref: str,
        *,
        estado: str,
        resolucao: str,
        justificativa: str,
    ) -> dict[str, Any]:
        """A decisão do advogado sobre uma divergência (`§10`).

        Resolver não apaga nada: grava um evento no histórico com quem decidiu e por quê, e
        os dois fatos continuam no caso. "Ambos permanecem como tese" é resposta legítima —
        no vínculo não registrado, a divergência é a própria causa.
        """
        return self._chamar(
            "PATCH",
            f"/api/v1/cases/{caso_ref}/contradictions/{contradicao_ref}",
            json={
                "status": estado,
                "resolution": resolucao,
                "justification": justificativa,
            },
        )

    # ---------------------------------------------------------------- estratégia

    def gerar_estrategia(self, caso_ref: str) -> dict[str, Any]:
        """Dispara a estratégia: hipóteses, pedidos, riscos e pendências.

        Roda por pedido explícito do advogado, nunca a cada fato novo — é cara, e a decisão
        de pedi-la é dele.
        """
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/strategy")

    def estrategia(self, caso_ref: str) -> dict[str, Any] | None:
        """A versão atual, ou `None` quando ainda não há nenhuma.

        O agente novo devolve 204 sem estratégia. 404 aqui significa caso inexistente
        e precisa subir para o dossiê recriar o vínculo — não confundir com ausência
        de estratégia (agente antigo ainda respondia 404 nesse caso).
        """
        try:
            return self._ler(f"/api/v1/cases/{caso_ref}/strategy")
        except ErroDoAgente as erro:
            if erro.status == 404 and "Caso não encontrado" in str(erro):
                raise
            if erro.status == 404:
                return None
            raise

    def decidir_estrategia(
        self, caso_ref: str, versao: int, *, aprovada: bool, nota: str | None = None
    ) -> dict[str, Any]:
        """A aprovação humana: só material aprovado alimenta a peça (`§13`)."""
        return self._chamar(
            "PATCH",
            f"/api/v1/cases/{caso_ref}/strategy/{versao}",
            json={"status": "APPROVED" if aprovada else "REJECTED", "note": nota},
        )

    def decidir_hipotese(
        self, caso_ref: str, hipotese_ref: str, *, aceita: bool, enunciado: str | None = None
    ) -> dict[str, Any]:
        return self._chamar(
            "PATCH",
            f"/api/v1/cases/{caso_ref}/strategy/hypotheses/{hipotese_ref}",
            json={
                "status": "ACCEPTED" if aceita else "DISCARDED",
                "statement": enunciado,
            },
        )

    # -------------------------------------------------------------- peças geradas

    def gerar_peticao(self, caso_ref: str) -> dict[str, Any]:
        """Dispara a geração da petição inicial. Responde na hora, redige depois.

        Uma chamada de modelo por seção do outro lado — é o motivo de o prazo aqui ser o
        de envio, e não o das leituras que o advogado espera olhando a tela.
        """
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/generations",
            json={"document_type": "INITIAL_PETITION"},
            timeout=self._cfg.timeout_envio,
        )

    def gerar_peticao_entrevista(
        self,
        caso_ref: str,
        *,
        interview_id: str,
        transcript: str,
        analysis_summary: str,
        taxonomy_code: str,
        strategy_title: str,
        strategy_thesis: str,
        strategy_claims: list[str] | None = None,
        strategy_risks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Petição pelo fluxo de entrevista — usa embeddings de style e de documentos."""
        return self._chamar(
            "POST",
            f"/api/v1/cases/{caso_ref}/generations/interview-pipeline",
            json={
                "interview_id": interview_id,
                "transcript": transcript,
                "analysis_summary": analysis_summary,
                "taxonomy_code": taxonomy_code,
                "strategy_title": strategy_title,
                "strategy_thesis": strategy_thesis,
                "strategy_claims": strategy_claims or [],
                "strategy_risks": strategy_risks or [],
            },
            timeout=self._cfg.timeout_envio,
        )

    def peticoes(self, caso_ref: str) -> dict[str, Any]:
        return self._ler(f"/api/v1/cases/{caso_ref}/generations")

    def peticao(self, caso_ref: str, peca_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/generations/{peca_ref}")

    def progresso_peticao(self, caso_ref: str, desde: str) -> dict[str, Any]:
        """Onde a redação está agora — contada pelo agente, não estimada aqui."""
        return self._ler(
            f"/api/v1/cases/{caso_ref}/generations/progress?since={quote(desde)}"
        )

    def baixar_peticao(self, caso_ref: str, peca_ref: str, *, formato: str = "docx") -> bytes:
        """O arquivo da peça, renderizado pelo agente a partir das seções guardadas.

        Passa por aqui e não pelo navegador porque o token e o endereço do agente ficam
        no servidor — e porque o arquivo precisa chegar ao advogado com o mesmo aviso de
        minuta que o agente carimba nele.
        """
        url = (
            f"{self._cfg.url}/api/v1/cases/{caso_ref}/generations/{peca_ref}/file"
            f"?format={formato}"
        )
        try:
            resposta = _cliente_http().get(
                url, headers=self._cabecalhos(), timeout=self._cfg.timeout_envio
            )
        except httpx.HTTPError as erro:
            log.warning("agente indisponível ao baixar peça em %s: %s", url, erro)
            raise AgenteIndisponivel(
                "O agente jurídico não respondeu ao pedido do arquivo."
            ) from erro

        if resposta.status_code >= 400:
            raise ErroDoAgente(_detalhe(resposta), status=resposta.status_code)
        return resposta.content

    def decidir_peticao(
        self,
        caso_ref: str,
        peca_ref: str,
        *,
        aprovada: bool,
        nota: str | None = None,
        secoes: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """A revisão humana do `§2.10`. Não existe caminho automático para aprovada.

        `secoes` carrega o texto **como o advogado o entregou**, quando ele editou na tela.
        O agente guarda essa versão ao lado da gerada, nunca por cima: a diferença entre as
        duas é o único sinal que o sistema tem sobre o estilo do escritório, e ela deixa de
        existir no instante em que uma das duas é sobrescrita.

        Ausente significa "revisei sem mexer no texto" — diferente de enviar as seções
        idênticas, que prova que o advogado passou por cada uma delas.
        """
        corpo: dict[str, Any] = {
            "status": "APPROVED" if aprovada else "REJECTED",
            "note": nota,
        }
        if secoes is not None:
            corpo["sections"] = secoes
        return self._chamar(
            "PATCH", f"/api/v1/cases/{caso_ref}/generations/{peca_ref}", json=corpo
        )

    def taxonomia(self) -> dict[str, Any]:
        """Os códigos de ação que o agente conhece, para a tela oferecer os certos.

        Vem do YAML validado no boot do agente, não de uma lista repetida aqui: um código
        digitado à mão cria silenciosamente um grupo de estilo com uma peça só, e o escritório
        passa a ver dois padrões para a mesma ação sem entender de onde saiu o segundo.
        """
        return self._ler("/api/v1/legal/taxonomy")

    # ------------------------------------------------------------------ estilo

    def enviar_peca_de_estilo(
        self,
        *,
        nome: str,
        conteudo: bytes,
        taxonomy_code: str,
        document_type: str = "INITIAL_PETITION",
    ) -> dict[str, Any]:
        """Sobe uma peça histórica do escritório para o corpus de estilo.

        Escopo de organização, não de caso: a peça não pertence a um processo, é material do
        escritório, e o mesmo padrão serve a todos os casos daquele tipo de ação.
        """
        url = f"{self._cfg.url}/api/v1/style/documents"
        try:
            resposta = _cliente_http().post(
                url,
                headers=self._cabecalhos(),
                files={"file": (nome, conteudo, "application/octet-stream")},
                data={"taxonomy_code": taxonomy_code, "document_type": document_type},
                timeout=self._cfg.timeout_envio,
            )
        except httpx.HTTPError as erro:
            log.warning("agente indisponivel ao enviar peca de estilo em %s: %s", url, erro)
            raise AgenteIndisponivel(
                "O agente jurídico não respondeu ao envio da peça."
            ) from erro

        if resposta.status_code >= 400:
            raise ErroDoAgente(_detalhe(resposta), status=resposta.status_code)
        return dict(resposta.json())

    def perfil_de_estilo(
        self,
        *,
        taxonomy_code: str | None = None,
        document_type: str = "INITIAL_PETITION",
        unidade: str = "DOCUMENT",
    ) -> dict[str, Any]:
        """O padrão de escrita do grupo, com a amostra e o nível que responderam.

        O nível importa na tela: "87" a partir de quatro peças e "87" a partir de trezentas
        são afirmações diferentes, e o advogado precisa poder distingui-las.
        """
        caminho = (
            f"/api/v1/style/profile?document_type={quote(document_type)}&unit={quote(unidade)}"
        )
        if taxonomy_code:
            caminho += f"&taxonomy_code={quote(taxonomy_code)}"
        return self._ler(caminho)

    def pecas_de_estilo(
        self, *, taxonomy_code: str | None = None, document_type: str | None = None
    ) -> dict[str, Any]:
        caminho = "/api/v1/style/documents"
        filtros = []
        if taxonomy_code:
            filtros.append(f"taxonomy_code={quote(taxonomy_code)}")
        if document_type:
            filtros.append(f"document_type={quote(document_type)}")
        if filtros:
            caminho += "?" + "&".join(filtros)
        return self._ler(caminho)

    def remover_peca_de_estilo(self, peca_id: str) -> None:
        """Remove uma amostra do corpus da organização autenticada."""
        self._chamar("DELETE", f"/api/v1/style/documents/{quote(peca_id)}")

    def configuracao_de_geracao(self, taxonomy_code: str, document_type: str) -> dict[str, Any]:
        return self._ler(
            "/api/v1/style/generation-config"
            f"?taxonomy_code={quote(taxonomy_code)}&document_type={quote(document_type)}"
        )

    def salvar_configuracao_de_geracao(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._chamar("PUT", "/api/v1/style/generation-config", json=payload)

    # ------------------------------------------------------------------ saúde

    def saude(self) -> dict[str, Any]:
        return self._chamar("GET", "/api/health", timeout=5)

    def inspecao(self) -> dict[str, Any]:
        """Latência dos dois bancos do agente e o desempenho de cada agente de IA.

        `/api/health/inspection`, do lado de lá, é mais lento que `/api/health` (mede o corpus de
        jurisprudência e agrega `agent_runs`) e exige papel interno — por isso um método
        à parte, com prazo próprio, em vez de reaproveitar `saude()`.
        """
        return self._chamar("GET", "/api/health/inspection", timeout=15)


def _detalhe(resposta: httpx.Response) -> str:
    """A mensagem do agente, não um "erro 422" genérico.

    O agente responde `{"error": {"code": ..., "message": ...}}`; é esse texto que
    diz ao advogado o que fazer — "o caso ainda não tem questões jurídicas", por
    exemplo, é instrução, não falha de sistema.
    """
    try:
        corpo = resposta.json()
    except ValueError:
        return f"Agente respondeu {resposta.status_code}."

    if isinstance(corpo, dict):
        erro = corpo.get("error")
        if isinstance(erro, dict) and erro.get("message"):
            return str(erro["message"]) + _pendencias(erro)
        if corpo.get("detail"):
            return str(corpo["detail"])
    return f"Agente respondeu {resposta.status_code}."


def _pendencias(erro: dict[str, Any]) -> str:
    """Anexa o que falta quando o caso é recusado por não estar pronto.

    Sem isto a tela mostraria "o caso ainda não está pronto para virar peça" e ponto —
    verdade inútil. O agente manda os códigos do readiness junto; aqui eles viram as frases
    que dizem qual documento buscar.
    """
    if erro.get("code") != "CASE_NOT_READY":
        return ""

    detalhes = erro.get("details")
    codigos = (detalhes or {}).get("blocking_issues") if isinstance(detalhes, dict) else None
    if not codigos:
        return ""
    return " Falta: " + " ".join(motivos.explicar_todos(list(codigos)))
