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
from typing import Any

import httpx

from . import motivos
from .config import Config, config

log = logging.getLogger("agente")

__all__ = ["AgenteIndisponivel", "AgenteNaoConfigurado", "ErroDoAgente", "Cliente"]


class ErroDoAgente(RuntimeError):
    """Falha que o advogado precisa ver, com o texto que o agente devolveu."""


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

    def _chamar(
        self,
        metodo: str,
        caminho: str,
        *,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self._cfg.url}{caminho}"
        try:
            resposta = httpx.request(
                metodo,
                url,
                json=json,
                headers=self._cabecalhos(),
                timeout=timeout or self._cfg.timeout,
            )
        except httpx.HTTPError as erro:
            # Rede, DNS, prazo. O agente pode estar subindo, o banco dele pode estar
            # fora — de todo jeito, não olhamos o caso.
            log.warning("agente indisponível em %s: %s", url, erro)
            raise AgenteIndisponivel(
                "O agente jurídico não respondeu. O caso continua no OCR; "
                "a análise fica pendente até ele voltar."
            ) from erro

        if resposta.status_code >= 400:
            raise ErroDoAgente(_detalhe(resposta))
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
            pagina = self._chamar(
                "GET", f"{caminho}?limit={limite}&offset={offset}"
            )
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
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/documents")

    # ------------------------------------------------------------- análise

    def analisar(self, caso_ref: str) -> dict[str, Any]:
        """Dispara classificação e apuração de pendências. Responde na hora, roda depois."""
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/analysis")

    def analise(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/analysis")

    # ------------------------------------------------------------- pesquisa

    def pesquisar(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("POST", f"/api/v1/cases/{caso_ref}/research")

    def pesquisas(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/research")

    def pesquisa(self, caso_ref: str, pesquisa_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/research/{pesquisa_ref}")

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

        Ausência aqui é estado normal do caso, não erro: a estratégia só existe depois que
        alguém a pede. Tratar 404 como falha faria a tela mostrar erro para um caso novo.
        """
        try:
            return self._chamar("GET", f"/api/v1/cases/{caso_ref}/strategy")
        except ErroDoAgente as erro:
            if "não encontrada" in str(erro) or "Nenhuma estratégia" in str(erro):
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

    def peticoes(self, caso_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/generations")

    def peticao(self, caso_ref: str, peca_ref: str) -> dict[str, Any]:
        return self._chamar("GET", f"/api/v1/cases/{caso_ref}/generations/{peca_ref}")

    def baixar_peticao(self, caso_ref: str, peca_ref: str) -> bytes:
        """O `.docx` da peça, renderizado pelo agente a partir das seções guardadas.

        Passa por aqui e não pelo navegador porque o token e o endereço do agente ficam
        no servidor — e porque o arquivo precisa chegar ao advogado com o mesmo aviso de
        minuta que o agente carimba nele.
        """
        url = f"{self._cfg.url}/api/v1/cases/{caso_ref}/generations/{peca_ref}/file"
        try:
            resposta = httpx.get(
                url, headers=self._cabecalhos(), timeout=self._cfg.timeout_envio
            )
        except httpx.HTTPError as erro:
            log.warning("agente indisponível ao baixar peça em %s: %s", url, erro)
            raise AgenteIndisponivel(
                "O agente jurídico não respondeu ao pedido do arquivo."
            ) from erro

        if resposta.status_code >= 400:
            raise ErroDoAgente(_detalhe(resposta))
        return resposta.content

    def decidir_peticao(
        self, caso_ref: str, peca_ref: str, *, aprovada: bool, nota: str | None = None
    ) -> dict[str, Any]:
        """A revisão humana do `§2.10`. Não existe caminho automático para aprovada."""
        return self._chamar(
            "PATCH",
            f"/api/v1/cases/{caso_ref}/generations/{peca_ref}",
            json={"status": "APPROVED" if aprovada else "REJECTED", "note": nota},
        )

    # ------------------------------------------------------------------ saúde

    def saude(self) -> dict[str, Any]:
        return self._chamar("GET", "/health", timeout=5)


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
