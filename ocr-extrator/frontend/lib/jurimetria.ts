/**
 * Cliente do painel de jurimetria.
 *
 * O backend do agente entrega tudo já medido: distribuição de desfechos do recorte, a
 * referência contra a qual ele faz sentido, a série anual, os rankings e — o que mais
 * importa aqui — as **ressalvas**. Nada é recalculado nesta camada.
 *
 * A regra que atravessa o módulo inteiro: nenhum percentual existe sozinho. Cada um vem
 * com `total` (quantos processos), `margin` (a margem de erro) e o `scope` que o produziu.
 * Reduzir isso a um número na tela seria transformar "61% em 79 processos daquela vara"
 * em "61% de chance de ganhar", que é uma frase que ninguém pode sustentar.
 */

import { ApiError, cabecalhos, urlApi } from "./api";

/** Uma proporção com a amostra que a produziu. Os dois nunca se separam. */
export interface Proporcao {
  label: string;
  count: number;
  total: number;
  /** Fração de 0 a 1. */
  share: number;
  /** Margem de erro em fração — 0.05 é cinco pontos percentuais. */
  margin: number;
  small_sample: boolean;
  comparacao?: Comparacao;
}

export interface Comparacao {
  difference_points: number;
  /** A amostra sustenta a diferença? Quando `false`, a tela mostra o número e a ressalva. */
  meaningful: boolean;
  /** A conta por extenso, para o tooltip. */
  basis: string;
  scope: { count: number; total: number; share: number; margin: number };
  reference: { count: number; total: number; share: number; margin: number };
}

export interface Recorte {
  label: string;
  subjects?: string[];
  judging_bodies?: string[];
  judges?: string[];
  case_classes?: string[];
  origins?: string[];
  decided_from?: string;
  decided_to?: string;
  notes?: string[];
}

export interface Cobertura {
  processes: number;
  first_decision: string | null;
  last_decision: string | null;
}

export interface PontoDoAno {
  year: number;
  processes: number;
  /** Ano incompleto: ainda corre, ou o acervo termina no meio dele. */
  partial: boolean;
  small_sample: boolean;
  shares: Proporcao[];
}

export interface Tendencia {
  label: string;
  first_year: number;
  last_year: number;
  direction: "alta" | "queda" | "estável";
  comparison: Comparacao;
  nature: string;
}

export interface FatiaDoRanking {
  value: string;
  processes: number;
  small_sample: boolean;
  shares: Proporcao[];
}

export interface Ranking {
  dimension: string;
  label: string;
  ordering: string;
  /** `false` para assunto e magistrado: um processo entra em várias fatias. */
  counts_processes_once: boolean;
  nature: string;
  slices: FatiaDoRanking[];
}

export interface Ausencia {
  question: string;
  reason: string;
}

export interface Jurimetria {
  nature: string;
  scope: Recorte;
  coverage: Cobertura;
  reliable: boolean;
  minimum_sample: number;
  outcomes: Proporcao[];
  timeline: PontoDoAno[];
  trend: Tendencia | null;
  rankings: Ranking[];
  absences: Ausencia[];
  notes: string[];
  reference?: { scope: Recorte; coverage: Cobertura };
  appellate?: {
    count: number;
    total: number;
    share: number;
    margin: number;
    small_sample: boolean;
    meaning: string;
  };
}

async function buscar<T>(caminho: string): Promise<T> {
  const resposta = await fetch(urlApi(caminho), { headers: cabecalhos() });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`,
    );
  }
  return corpo as T;
}

async function enviar<T>(caminho: string, corpoEnvio?: Record<string, unknown>): Promise<T> {
  const resposta = await fetch(urlApi(caminho), {
    method: "POST",
    headers: cabecalhos(corpoEnvio ? { "Content-Type": "application/json" } : undefined),
    body: corpoEnvio ? JSON.stringify(corpoEnvio) : undefined,
  });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`,
    );
  }
  return corpo as T;
}

/** O painel do recorte comparável deste caso. */
export async function buscarJurimetria(casoId: string, orgao?: string): Promise<Jurimetria> {
  const sufixo = orgao ? `?orgao=${encodeURIComponent(orgao)}` : "";
  return buscar<Jurimetria>(
    `/api/agente/casos/${encodeURIComponent(casoId)}/jurimetria${sufixo}`,
  );
}

/** O painel do acervo, sem caso — a pergunta que vem antes de haver processo. */
export async function buscarJurimetriaDoAcervo(filtros: {
  assunto?: string[];
  orgao?: string[];
  magistrado?: string[];
}): Promise<Jurimetria> {
  const query = new URLSearchParams();
  for (const [chave, valores] of Object.entries(filtros)) {
    for (const valor of valores ?? []) query.append(chave, valor);
  }
  const sufixo = query.size > 0 ? `?${query}` : "";
  return buscar<Jurimetria>(`/api/agente/jurimetria${sufixo}`);
}

// ------------------------------------------------------------------ formato

/** Percentual com uma casa. Recebe a fração, como o backend a entrega. */
export function percentual(fracao: number): string {
  return `${(fracao * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

/** Diferença em pontos percentuais, com o sinal explícito. */
export function pontos(valor: number): string {
  const formatado = Math.abs(valor).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  if (valor === 0) return "0 p.p.";
  return `${valor > 0 ? "+" : "−"}${formatado} p.p.`;
}

/**
 * Como a tela deve ler uma comparação — símbolo, palavra e tom, nesta ordem.
 *
 * Uma diferença que a amostra não sustenta continua visível, mas dita como "dentro da
 * margem". Escondê-la faria quem viu 8 pontos ontem achar que o sistema mudou de ideia;
 * exibi-la como achado faria ruído virar tendência.
 */
export function leituraDaComparacao(
  comparacao: Comparacao | undefined,
): { simbolo: string; palavra: string; tom: "ok" | "atencao" | "neutro" } | null {
  if (!comparacao) return null;
  if (!comparacao.meaningful) {
    return { simbolo: "≈", palavra: "dentro da margem", tom: "neutro" };
  }
  return comparacao.difference_points > 0
    ? { simbolo: "▲", palavra: "acima da referência", tom: "ok" }
    : { simbolo: "▼", palavra: "abaixo da referência", tom: "atencao" };
}

/** Rótulo legível dos desfechos do acervo, que vêm em caixa alta. */
export const ROTULO_DO_DESFECHO: Record<string, string> = {
  PROCEDENTE: "Procedente",
  PARCIAL: "Parcialmente procedente",
  IMPROCEDENTE: "Improcedente",
  ACORDO: "Acordo",
  EXTINTO: "Extinto sem mérito",
  INDEFINIDO: "Sem desfecho registrado",
};

export function rotuloDoDesfecho(codigo: string): string {
  return ROTULO_DO_DESFECHO[codigo] ?? codigo;
}

// ------------------------------------------------- leituras de agente

/** O processo por extenso ao lado de cada citação — nunca o `corpus_id` cru. */
export interface PrecedenteCitado {
  corpus_id: string;
  process_number: string;
  court: string;
  judging_body: string | null;
  decided_at: string | null;
  outcome: string | null;
}

/** Uma razão de decidir recorrente no recorte, ancorada nos processos que a sustentam. */
export interface LinhaArgumentativa {
  thesis: string;
  side: "GRANTING" | "DENYING";
  precedents: PrecedenteCitado[];
  cited_excerpts: string[];
  counter_consideration: string;
  /** Fração de 0 a 1 — não é probabilidade de êxito, é quanto o conjunto lido sustenta a linha. */
  confidence: number;
}

export interface LeituraLinhasArgumentativas {
  status: "RUNNING" | "COMPLETED" | "FAILED";
  lines: LinhaArgumentativa[];
  sample: { granting: number; denying: number };
  failure_reason: string | null;
  nature: string;
}

/** O argumento provável do outro lado, com o precedente que o sustenta. */
export interface ContraArgumento {
  argument: string;
  precedents: PrecedenteCitado[];
  cited_excerpts: string[];
  /** Por que o caso concreto pode se afastar daquele precedente. Vazio é resposta legítima. */
  distinguishing: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
}

export interface LeituraContraTese {
  status: "RUNNING" | "COMPLETED" | "FAILED";
  thesis: string;
  counters: ContraArgumento[];
  sample: number;
  failure_reason: string | null;
  nature: string;
}

/** Dispara a leitura. Fica em fila do outro lado — chama modelo sobre os precedentes já
 * recuperados do recorte deste caso. */
export async function dispararLinhasArgumentativas(
  casoId: string,
): Promise<{ run_id: string; status: string }> {
  return enviar(
    `/api/agente/casos/${encodeURIComponent(casoId)}/jurimetria/linhas-argumentativas`,
  );
}

/** A leitura mais recente, ou `null` quando ainda não foi pedida — estado normal, não erro. */
export async function buscarLinhasArgumentativas(
  casoId: string,
): Promise<LeituraLinhasArgumentativas | null> {
  return buscar(
    `/api/agente/casos/${encodeURIComponent(casoId)}/jurimetria/linhas-argumentativas`,
  );
}

/** Dispara a contra-tese contra a hipótese aceita indicada. */
export async function dispararContraTese(
  casoId: string,
  hipoteseId: string,
): Promise<{ run_id: string; status: string }> {
  return enviar(`/api/agente/casos/${encodeURIComponent(casoId)}/jurimetria/contra-tese`, {
    hipotese_id: hipoteseId,
  });
}

export async function buscarContraTese(casoId: string): Promise<LeituraContraTese | null> {
  return buscar(`/api/agente/casos/${encodeURIComponent(casoId)}/jurimetria/contra-tese`);
}
