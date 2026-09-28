/** Follow-up de clientes e ligações. */

import { buscar, comoJson } from "./base";

// ------------------------------------------------- Relatório de follow-up

export interface ClienteFollowUp {
  caso_id: string;
  cliente: string;
  telefone: string;
  documentos_faltantes: string[];
  faltantes_total: number;
  dias_parado: number;
  follow_up_ativo: boolean;
  precisa_ligar: boolean;
  motivo_ligacao: string;
  ultima_ligacao: Call | null;
  /** Dias corridos desde a última ligação — `null` quando nunca ligaram. */
  dias_desde_ligacao: number | null;
}

export interface RelatorioFollowUp {
  clientes: ClienteFollowUp[];
  total: number;
  precisam_ligar: number;
  regra: string;
  aviso: string;
}

export interface Call {
  id: string;
  caso_id: string;
  atendente_id: string;
  atendente_nome: string;
  realizada_em: string;
  criado_em: string;
}

/** Clientes com documento obrigatório pendente, com alerta de necessidade de ligação. */
export async function relatorioFollowUp(): Promise<RelatorioFollowUp> {
  return comoJson(await buscar("/api/follow-up"));
}

export async function callHistory(caseId: string): Promise<{ calls: Call[] }> {
  return comoJson(await buscar(`/api/casos/${encodeURIComponent(caseId)}/ligacoes`));
}

export async function registerCall(caseId: string): Promise<Call> {
  return comoJson(await buscar(`/api/casos/${encodeURIComponent(caseId)}/ligacoes`, { method: "POST" }));
}
