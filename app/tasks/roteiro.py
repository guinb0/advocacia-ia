"""Importa um roteiro de entrevista a partir do documento anexado.

Fora do processo da API porque a leitura pode ser OCR de um PDF digitalizado e a
montagem são várias chamadas ao modelo, uma por bloco — de dez segundos a dois
minutos. Numa requisição HTTP isso seria um botão travado e um proxy cortando a
conexão no meio.

Pode ser executada como tarefa Celery ou diretamente pela API em uma thread de
segundo plano. A segunda forma impede que uma importação administrativa fique
eternamente em `QUEUED` quando nenhum worker externo estiver conectado.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .. import jobs, roteiro_ia, roteiros
from ..celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.roteiro.importar_roteiro")
def importar_roteiro(self, job_id: str, caminho: str, nome: str):
    jobs.atualizar(
        job_id,
        status="STARTED",
        progresso=5,
        iniciado_em=datetime.now(timezone.utc),
        resultado={"etapa": "Lendo o arquivo"},
    )
    try:
        # A API e este worker normalmente estão em containers diferentes.
        # `/app/tmp/jobs/...` pertence ao disco da API e não existe aqui; o
        # binário durável do job é a fonte principal. O caminho só atende
        # instalações antigas em que ambos ainda compartilham o mesmo disco.
        conteudo = jobs.conteudo_arquivo(job_id)
        if conteudo is None:
            conteudo = Path(caminho).read_bytes()
        texto, leitura = roteiro_ia.texto_do_documento(nome, conteudo)

        jobs.atualizar(
            job_id,
            status="PROCESSING",
            progresso=15,
            resultado={"etapa": f"Texto extraído por {leitura}"},
        )

        def avancar(pct: int, etapa: str) -> None:
            jobs.atualizar(job_id, progresso=pct, resultado={"etapa": etapa})

        proposta = roteiro_ia.gerar(texto, origem=nome, progresso=avancar)

        # Valida antes de entregar: o que a tela recebe já passou pelo mesmo
        # crivo do que ela salva, então o editor abre sabendo que consegue
        # desenhar todas as perguntas.
        roteiro = roteiros.de_dict(proposta)

        resultado = {
            "roteiro": roteiro.to_dict(),
            "origem": nome,
            "leitura": leitura,
            # O texto lido volta junto para a conferência lado a lado: sem ele,
            # descobrir que o modelo pulou um bloco exigiria reabrir o .docx.
            "texto": texto[:20_000],
            "salvo": False,
        }
        jobs.atualizar(
            job_id,
            status="COMPLETED",
            progresso=100,
            resultado=resultado,
            finalizado_em=datetime.now(timezone.utc),
        )
        return resultado
    except (roteiro_ia.ErroGeracao, roteiros.RoteiroInvalido) as erro:
        # Erro esperado e explicado em português: vai inteiro para a tela, sem
        # retry — tentar de novo daria a mesma resposta e gastaria o mesmo minuto.
        jobs.atualizar(
            job_id,
            status="FAILED",
            erro=str(erro),
            finalizado_em=datetime.now(timezone.utc),
        )
        return None
    except Exception as erro:
        log.exception("Falha ao importar roteiro de %s", nome)
        jobs.atualizar(
            job_id,
            status="FAILED",
            erro=f"Erro inesperado ao montar o roteiro: {erro}",
            finalizado_em=datetime.now(timezone.utc),
        )
        raise
    finally:
        Path(caminho).unlink(missing_ok=True)
