/** Leitura avulsa de documento (OCR) e utilitários de download de texto. */

import type { Documento, TipoDocumento } from "../types";
import { ApiError, buscar, comoJson } from "./base";

export async function listarTipos(): Promise<TipoDocumento[]> {
  const dados = await comoJson<{ tipos: TipoDocumento[] }>(await buscar("/api/tipos"));
  return dados.tipos;
}

export async function verificarSaude(): Promise<boolean> {
  const dados = await comoJson<{ modelo_aquecido: boolean; ocr_via_worker: boolean }>(
    await buscar("/api/saude"),
  );
  return dados.ocr_via_worker || dados.modelo_aquecido;
}

export async function extrair(
  arquivo: File,
  idioma: string,
  tipo: string,
): Promise<Documento> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("tipo", tipo);
  const criado = await comoJson<{ job_id: string }>(
    await buscar("/api/extrair/jobs", { method: "POST", body: form }),
  );
  // O backend trata precedentes como enriquecimento de melhor esforço. Se o
  // worker desaparecer, não deixamos o botão preso por quinze minutos.
  const limite = Date.now() + 90_000;
  while (Date.now() < limite) {
    const job = await comoJson<{
      status: "QUEUED" | "STARTED" | "PROCESSING" | "COMPLETED" | "FAILED";
      erro?: string | null;
      resultado?: Documento | null;
    }>(await buscar(`/api/jobs/${criado.job_id}`));
    if (job.status === "COMPLETED" && job.resultado) return job.resultado;
    if (job.status === "FAILED") throw new ApiError(job.erro || "O processamento do documento falhou.");
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("O OCR continua na fila. Consulte o job novamente em instantes.");
}

export async function baixarTexto(caminho: string): Promise<string> {
  const r = await buscar(caminho);
  if (!r.ok) throw new ApiError(`Erro ${r.status}`);
  return r.text();
}
