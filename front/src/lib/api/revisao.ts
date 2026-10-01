/** Revisão de petições. */

import { buscar, comoJson } from "./base";

// ------------------------------------------------------ Revisão de petições

export interface PeticaoParaRevisar {
  caso_id: string;
  versao: number;
  status: string;
  atualizado_em: string;
  cliente: string;
  categoria: string;
  /** Quem já está revisando esta versão (revisão aberta), se houver. */
  revisor_andamento: string | null;
  andamento_desde: string | null;
}

export interface MetricasRevisao {
  revisadas: number;
  aprovadas: number;
  ajustes: number;
  em_andamento: number;
  tempo_medio_s: number;
  por_revisor: {
    revisor: string;
    revisadas: number;
    aprovadas: number;
    ajustes: number;
    tempo_total_s: number;
    tempo_medio_s: number;
  }[];
  aviso: string;
}

/** As petições que precisam de revisão, da mais antiga para a mais nova. */
export async function filaDeRevisao(): Promise<{ pendentes: PeticaoParaRevisar[] }> {
  return comoJson(await buscar("/api/revisao/fila"));
}

/** Marca o início da revisão desta petição (idempotente). */
export async function iniciarRevisao(casoId: string): Promise<unknown> {
  return comoJson(await buscar(`/api/revisao/${encodeURIComponent(casoId)}/iniciar`, { method: "POST" }));
}

/** Aprova a petição ("aprovada") ou devolve para ajustes ("ajustes"). */
export async function concluirRevisao(
  casoId: string,
  resultado: "aprovada" | "ajustes",
): Promise<{ resultado: string; status_peticao: string; duracao_s: number }> {
  return comoJson(await buscar(`/api/revisao/${encodeURIComponent(casoId)}/concluir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resultado }),
  }));
}

export async function metricasDeRevisao(minhas = false): Promise<MetricasRevisao> {
  return comoJson(await buscar(`/api/revisao/metricas${minhas ? "?minhas=true" : ""}`));
}
