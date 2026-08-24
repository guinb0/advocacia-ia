from __future__ import annotations

from ..celery_app import celery_app
from .. import jobs, pipeline, rag, relatorio
from datetime import datetime, timezone
from pathlib import Path


@celery_app.task(bind=True, name="app.tasks.documentos.executar", autoretry_for=(OSError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def executar(self, funcao: str, argumentos: dict):
    """Ponto controlado para documentos; funções permitidas são explícitas."""
    if funcao == "limpar_temporarios":
        from ..pipeline import limpar_temporarios
        return limpar_temporarios()
    raise ValueError(f"Operação de documentos não permitida: {funcao}")


@celery_app.task(
    bind=True,
    name="app.tasks.documentos.gerar_relatorio",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def gerar_relatorio(self, job_id: str, pedido: dict):
    jobs.atualizar(job_id, status="STARTED", progresso=5, iniciado_em=datetime.now(timezone.utc))
    try:
        analise = None
        if pedido.get("analisar", True) and str(pedido.get("relato", "")).strip():
            jobs.atualizar(job_id, status="PROCESSING", progresso=25)
            try:
                # O PDF é a entrega principal. Precedentes são enriquecimento e
                # têm orçamento curto: rede ou modelo lentos não podem deixar a
                # equipe olhando "Gerando" por vários minutos.
                analise = rag.sugerir_acoes(
                    pedido["relato"],
                    embedding_timeout=15,
                    connect_timeout=4,
                    connect_retries=1,
                    model_timeout=35,
                )
            except Exception:
                analise = {"indisponivel": "A análise por precedentes poderá ser gerada depois."}
        jobs.atualizar(job_id, status="PROCESSING", progresso=70)
        pdf, dados = relatorio.gerar_pdf(
            pedido["respostas"], pedido.get("roteiro", "empregado_publico"),
            pedido.get("entrevistador", ""), analise,
        )
        nome = f"{job_id}.pdf"
        destino = pipeline.TMP_DIR / nome
        destino.write_bytes(pdf)
        resultado = {
            "arquivo": f"/api/temp/{nome}",
            "cliente": dados["cliente"],
            "pendencias": len(dados["faltando_obrigatorias"]),
            "impedimentos": len(dados["impedimentos"]),
            "analise": "indisponivel" if analise and analise.get("indisponivel") else "sim" if analise else "nao",
        }
        jobs.atualizar(job_id, status="COMPLETED", progresso=100, resultado=resultado, finalizado_em=datetime.now(timezone.utc))
        return resultado
    except Exception as exc:
        jobs.atualizar(job_id, status="FAILED", erro=str(exc), finalizado_em=datetime.now(timezone.utc))
        raise
