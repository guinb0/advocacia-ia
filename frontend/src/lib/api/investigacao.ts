/** Investigação em fontes abertas. */

import { buscar, comoJson } from "./base";

export interface EvidenciaInvestigativa {
  identificador: string;
  categoria: string;
  titulo: string;
  url: string;
  fonte: string;
  confianca: string;
  metadados: Record<string, unknown>;
}

export interface ResultadoInvestigativo {
  texto: string;
  similaridade: number;
  metadados: Record<string, unknown>;
  titulo: string;
  url: string;
}

export async function coletarInvestigacao(alvo: {
  cnpj?: string;
  numero_processo?: string;
  tribunal: string;
}): Promise<{ fontes: number; chunks: number; evidencias: EvidenciaInvestigativa[]; avisos: string[] }> {
  return comoJson(await buscar("/api/investigacao/coletar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(alvo),
  }));
}

export async function buscarInvestigacao(filtro: {
  consulta: string;
  cnpj?: string;
  numero_processo?: string;
}): Promise<{ resultados: ResultadoInvestigativo[]; aviso: string }> {
  const params = new URLSearchParams({ consulta: filtro.consulta });
  if (filtro.cnpj) params.set("cnpj", filtro.cnpj);
  if (filtro.numero_processo) params.set("numero_processo", filtro.numero_processo);
  return comoJson(await buscar(`/api/investigacao/buscar?${params.toString()}`));
}

export interface AnaliseInvestigativa {
  resumo: string;
  insights: Array<{ achado: string; tipo: string; impacto: string; confianca: string; evidencias: string[]; como_verificar: string }>;
  contradicoes: Array<{ ponto: string; evidencias: string[]; pergunta: string }>;
  provas_a_buscar: string[];
  perguntas_entrevista: string[];
  alertas: string[];
  fontes: Array<{ indice: string; titulo: string; url: string; similaridade: number }>;
  aviso: string;
}

export async function analisarInvestigacao(alvo: {
  relato: string; cnpj?: string; numero_processo?: string; tribunal: string;
}): Promise<AnaliseInvestigativa> {
  return comoJson(await buscar("/api/investigacao/analisar", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(alvo),
  }));
}
