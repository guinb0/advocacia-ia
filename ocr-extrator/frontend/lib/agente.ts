/**
 * Cliente do módulo do agente jurídico.
 *
 * Fala com `/api/agente/*` do próprio backend do Acervo, que por sua vez conversa
 * com o serviço `ia-juridica`. A tela nunca chama o agente direto: assim o token, a
 * organização e o vínculo entre os dois casos ficam num lugar só, no servidor.
 *
 * Os estados de indisponibilidade viajam como dado, não como exceção — `disponivel`,
 * `motivo`, `estado: "indisponivel"`. É o que permite à tela dizer "o agente não
 * respondeu" em vez de mostrar um caso vazio, que se pareceria com "não há nada".
 */

import { ApiError, cabecalhos, urlApi } from "./api";

export type EstadoEtapa = "pendente" | "andamento" | "pronto" | "atencao" | "indisponivel";

export interface Etapa {
  codigo: string;
  titulo: string;
  estado: EstadoEtapa;
  detalhe: string;
}

export interface CampoDoCliente {
  rotulo: string;
  valor: string;
  confianca: number | null;
  status: string;
  fontes: string[];
}

export interface FatoDoAgente {
  id: string;
  type: string;
  value: Record<string, unknown>;
  status: string;
  confidence: number;
  legal_relevance?: string;
  /** Proveniência: documento e página de onde o fato saiu. Fato sem isto não existe. */
  sources?: {
    source_type: string;
    page?: number | null;
    ocr_field?: string | null;
    user_subject?: string | null;
  }[];
}

export interface ClassificacaoDoAgente {
  code: string;
  label: string;
  confidence: number;
  status: string;
  rationale?: string | null;
  playbook_id?: string | null;
  issues?: { code: string; label: string; confidence: number }[];
}

export interface PendenciaDoAgente {
  id: string;
  kind: string;
  code: string;
  label: string;
  severity: "BLOCKING" | "RECOMMENDED";
  status: string;
  playbook_id?: string | null;
  requirement?: string | null;
  question?: string | null;
}

export interface PesquisaResumo {
  id: string;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  query: string;
  issue_codes: string[];
  filters: Record<string, unknown>;
  corpus_coverage: {
    total_chunks: number;
    embedded_chunks: number;
    ratio: number;
    complete: boolean;
  } | null;
  failure_reason: string | null;
  created_at: string;
}

export interface PrecedenteAnalise {
  applicability: "HIGH" | "MEDIUM" | "LOW" | "NOT_APPLICABLE";
  summary: string;
  favorable_points: string[];
  unfavorable_points: string[];
  cited_excerpts: string[];
  confidence: number;
  model?: string | null;
}

export interface Precedente {
  id: string;
  corpus_id: string;
  process_number: string;
  court: string;
  judging_body: string | null;
  document_type: string | null;
  subjects: string[];
  decided_at: string | null;
  outcome: string | null;
  excerpt: string;
  similarity: number | null;
  rank_position: number;
  rank_reason: string | null;
  analyses: PrecedenteAnalise[];
}

export interface IndicadorDesfecho {
  sample_size: number;
  scope: string;
  small_sample: boolean;
  nature: string;
  unclassified: number;
  indicators: { label: string; count: number; share: number }[];
}

export interface PesquisaDetalhe {
  research: PesquisaResumo;
  precedentes?: Precedente[];
  precedents: Precedente[];
  outcome_indicators: IndicadorDesfecho | null;
}

export interface SecaoPeticao {
  code: string;
  label: string;
  content: string;
  written_by: "template" | "agent";
  supporting_fact_ids: string[];
  cited_precedent_ids: string[];
}

export interface AchadoRevisao {
  severity: "BLOCKING" | "WARNING";
  category: string;
  section: string;
  message: string;
  detail?: string;
}

export interface Peticao {
  id: string;
  document_type: string;
  status: "DRAFT" | "IN_REVIEW" | "APPROVED" | "REJECTED";
  version: number;
  title: string;
  /** A saída do readiness: por que a peça saiu assim, e o que faltava. */
  readiness: { ready: boolean; blocking_issues: string[]; warnings: string[] };
  review: { findings?: AchadoRevisao[]; summary?: string; blocking?: number };
  blocking_findings: number;
  model?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  sections?: SecaoPeticao[];
}

export interface Hipotese {
  id: string;
  statement: string;
  issue_codes: string[];
  /** As duas listas juntas: estratégia que só mostra o que ajuda é propaganda. */
  supporting_fact_ids: string[];
  weakening_fact_ids: string[];
  supporting_precedent_ids: string[];
  contradiction_ids: string[];
  strength: number;
  status: "PROPOSED" | "ACCEPTED" | "DISCARDED";
  missing_requirements: string[];
  rationale?: string | null;
}

export interface PontoEstrategia {
  /** A natureza do `§47`: fato provado, alegado, hipótese, inferência, recomendação… */
  nature: string;
  statement: string;
  supporting_fact_ids: string[];
  precedent_ids: string[];
}

export interface Estrategia {
  version: number;
  status: "PROPOSED" | "APPROVED" | "REJECTED";
  summary: string;
  claims: PontoEstrategia[];
  risks: PontoEstrategia[];
  pending_points: PontoEstrategia[];
  /** O que o guardrail de ancoragem descartou, com o motivo. */
  rejected_items: { kind: string; statement: string; reason: string }[];
  hypotheses: Hipotese[];
  reviewed_by?: string | null;
}

export interface Contradicao {
  id: string;
  type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  legal_relevance: "HIGH" | "MEDIUM" | "LOW";
  status: "OPEN" | "UNDER_REVIEW" | "RESOLVED" | "DISMISSED";
  /** A divergência concreta e o caminho de conferência — nunca uma escolha de vencedor. */
  possible_resolution: string | null;
  facts: { fact_id: string; fact_type?: string; value?: Record<string, unknown> }[];
  resolutions: {
    to_status: string;
    resolution: string;
    justification: string;
    resolved_by_subject: string;
    created_at: string;
  }[];
}

export interface BlocoAgente {
  ligado: boolean;
  disponivel: boolean;
  vinculado: boolean;
  caso_ref: string | null;
  ultimo_erro: string | null;
  motivo: string | null;
  fatos: FatoDoAgente[];
  classificacoes: ClassificacaoDoAgente[];
  pendencias: PendenciaDoAgente[];
  contradicoes: Contradicao[];
  documentos: { id: string; document_type?: string; status?: string }[];
  pesquisas: PesquisaResumo[];
  peticoes: Peticao[];
  estrategia: Estrategia | null;
  parciais?: { bloco: string; motivo: string }[];
}

/** A entrevista do atendimento como o dossiê a resume. O texto inteiro vem sob demanda. */
export interface EntrevistaResumo {
  id: string;
  arquivo: string;
  realizada_em: string;
  entrevistador: string;
  resumo: string;
  perguntas: string[];
  fatos_gerados: number;
  enviada: boolean;
  criado_em: string;
  caracteres: number;
  previa: string;
  truncada: boolean;
}

export interface EntrevistaCompleta extends EntrevistaResumo {
  texto: string;
  caso_id: string;
}

export interface Dossie {
  caso: {
    id: string;
    cliente: string;
    categoria: string;
    observacao: string;
    criado_em: string;
    atualizado_em: string;
  };
  cliente: { nome: string; campos: CampoDoCliente[]; documentos_entregues: number | null };
  checklist: {
    categoria: string | null;
    progresso: Record<string, number | boolean> | null;
    itens: {
      codigo: string;
      rotulo: string;
      status: string;
      obrigatorio: boolean;
      alertas: string[];
    }[];
  };
  contrato: {
    assinado: boolean;
    assinaturas: {
      id: string;
      nome: string;
      estado: string;
      assinaram: number;
      total: number;
      faltam: string[];
    }[];
  };
  entrevistas: EntrevistaResumo[];
  agente: BlocoAgente;
  etapas: Etapa[];
}

export interface ConfigAgente {
  ligado: boolean;
  disponivel: boolean;
  url: string;
  jurisdicao_padrao: string;
  motivo?: string;
}

/** Uma dependência do agente — banco de aplicação, corpus de jurisprudência ou cache. */
export interface DependenciaAgente {
  status: "ok" | "not_configured" | "error";
  latency_ms: number;
  detail?: string;
}

/** Tempo de raciocínio puro: latência de cada chamada ao modelo, sem contar retentativa. */
export interface RaciocinioAgente {
  calls: number;
  avg_call_latency_ms: number;
  min_call_latency_ms: number;
  max_call_latency_ms: number;
}

/** Quanto um agente (estratégia, pesquisa, redação...) demorou e acertou nas últimas 24h. */
export interface DesempenhoAgente {
  agent_name: string;
  task: string;
  runs: number;
  avg_duration_ms: number;
  max_duration_ms: number;
  success_rate: number;
  last_run_at: string | null;
  /** `null` quando o agente rodou sem chegar a chamar o modelo. */
  reasoning: RaciocinioAgente | null;
}

export interface SaudeAgente {
  ligado: boolean;
  status?: "ok" | "unavailable";
  dependencies?: {
    database: DependenciaAgente;
    cache: DependenciaAgente;
    jurisprudence: DependenciaAgente;
  };
  agents?: {
    window_hours: number;
    by_agent: DesempenhoAgente[];
  };
}

async function chamar<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const resposta = await fetch(urlApi(caminho), {
    ...init,
    // O Bearer vem de `lib/api.ts`: um token só para a aplicação inteira.
    headers: cabecalhos({
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...((init.headers as Record<string, string>) ?? {}),
    }),
  });

  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe);
  }
  return corpo as T;
}

export function configDoAgente(): Promise<ConfigAgente> {
  return chamar<ConfigAgente>("/api/agente/config");
}

export function saudeDoAgente(): Promise<SaudeAgente> {
  return chamar<SaudeAgente>("/api/agente/saude");
}

export function buscarDossie(casoId: string): Promise<Dossie> {
  return chamar<Dossie>(`/api/agente/casos/${casoId}`);
}

/** Cria o caso no agente (se ainda não existe) e manda os documentos que faltavam. */
export function sincronizarComAgente(
  casoId: string,
  jurisdicao?: string,
): Promise<{ caso_ref: string; documentos_enviados: number; documentos_com_falha: number }> {
  return chamar(`/api/agente/casos/${casoId}/sincronizar`, {
    method: "POST",
    body: JSON.stringify({ jurisdicao: jurisdicao ?? null }),
  });
}

export function analisarNoAgente(casoId: string): Promise<{ run_id: string; status: string }> {
  return chamar(`/api/agente/casos/${casoId}/analise`, { method: "POST" });
}

export function pesquisarNoAgente(casoId: string): Promise<{ run_id: string; status: string }> {
  return chamar(`/api/agente/casos/${casoId}/pesquisa`, { method: "POST" });
}

export function buscarPesquisa(casoId: string, pesquisaId: string): Promise<PesquisaDetalhe> {
  return chamar(`/api/agente/casos/${casoId}/pesquisa/${pesquisaId}`);
}

/** Confere a qualificação do contrato contra os fatos vindos dos documentos. */
export function conferirContrato(
  casoId: string,
  campos: Record<string, unknown>,
): Promise<{
  disponivel: boolean;
  motivo?: string;
  conferidos: string[];
  divergencias: {
    campo: string;
    no_contrato: string;
    nos_documentos: string;
    tipo_de_fato: string;
  }[];
}> {
  return chamar(`/api/agente/casos/${casoId}/contrato/conferencia`, {
    method: "POST",
    body: JSON.stringify(campos),
  });
}

/* ------------------------------------------------------------------ petição */

/** Dispara a minuta. Responde 202: a peça aparece no dossiê quando ficar pronta. */
export function gerarPeticao(casoId: string): Promise<{ run_id: string; status: string }> {
  return chamar(`/api/agente/casos/${casoId}/peticao`, { method: "POST" });
}

export function buscarPeticao(casoId: string, pecaId: string): Promise<Peticao> {
  return chamar(`/api/agente/casos/${casoId}/peticao/${pecaId}`);
}

/** Aprovar ou rejeitar — a revisão humana que o `§2.10` exige antes de qualquer uso. */
export function decidirPeticao(
  casoId: string,
  pecaId: string,
  aprovada: boolean,
  nota?: string,
): Promise<Peticao> {
  return chamar(`/api/agente/casos/${casoId}/peticao/${pecaId}`, {
    method: "PATCH",
    body: JSON.stringify({ aprovada, nota: nota ?? null }),
  });
}

/** URL do `.docx`. O download passa pelo backend, que é quem tem o token do agente. */
export function urlDaPeticao(casoId: string, pecaId: string): string {
  return urlApi(`/api/agente/casos/${casoId}/peticao/${pecaId}/arquivo`);
}

/* --------------------------------------------------------------- entrevista */

/** Anexa o arquivo do atendimento ao caso. O texto é lido no servidor. */
export async function anexarEntrevista(
  casoId: string,
  arquivo: File,
  realizadaEm: string,
  entrevistador: string,
): Promise<EntrevistaResumo> {
  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  corpo.append("realizada_em", realizadaEm);
  corpo.append("entrevistador", entrevistador);

  // `FormData` monta o próprio `Content-Type` com o boundary; declarar um aqui faria o
  // servidor não achar o arquivo.
  const resposta = await fetch(urlApi(`/api/casos/${casoId}/entrevista`), {
    method: "POST",
    headers: cabecalhos(),
    body: corpo,
  });
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    throw new ApiError(
      dados && typeof dados === "object" && "detail" in dados
        ? String((dados as { detail: unknown }).detail)
        : `Erro ${resposta.status}`,
    );
  }
  return dados as EntrevistaResumo;
}

/** O texto inteiro da entrevista — buscado só quando o advogado abre para ler. */
export function buscarEntrevista(
  casoId: string,
  entrevistaId: string,
): Promise<EntrevistaCompleta> {
  return chamar(`/api/casos/${casoId}/entrevista/${entrevistaId}`);
}

/** Manda a entrevista para o agente ler. Os fatos entram como **alegados**. */
export function lerEntrevistaNoAgente(
  casoId: string,
  entrevistaId: string,
): Promise<{ facts_recorded?: number; summary?: string; failure?: string; ja_enviada?: boolean }> {
  return chamar(`/api/agente/casos/${casoId}/entrevista/${entrevistaId}`, { method: "POST" });
}

/** URL do arquivo original, como o advogado o enviou. */
export function urlDaEntrevista(casoId: string, entrevistaId: string): string {
  return urlApi(`/api/casos/${casoId}/entrevista/${entrevistaId}/arquivo`);
}

/* --------------------------------------------------------------- estratégia */

export function gerarEstrategia(casoId: string): Promise<{ run_id: string; status: string }> {
  return chamar(`/api/agente/casos/${casoId}/estrategia`, { method: "POST" });
}

/** Aprovar é o que faz a petição parar de tirar os pedidos do playbook (`§13`). */
export function decidirEstrategia(
  casoId: string,
  versao: number,
  aprovada: boolean,
  nota?: string,
): Promise<Estrategia> {
  return chamar(`/api/agente/casos/${casoId}/estrategia/${versao}`, {
    method: "PATCH",
    body: JSON.stringify({ aprovada, nota: nota ?? null }),
  });
}

export function decidirHipotese(
  casoId: string,
  hipoteseId: string,
  aceita: boolean,
  enunciado?: string,
): Promise<Hipotese> {
  return chamar(`/api/agente/casos/${casoId}/estrategia/hipoteses/${hipoteseId}`, {
    method: "PATCH",
    body: JSON.stringify({ aceita, enunciado: enunciado ?? null }),
  });
}

/* ----------------------------------------------------------- contradições */

/** A decisão do advogado sobre uma divergência.
 *
 * "Ambos permanecem como tese" é resposta legítima e frequente: no vínculo não registrado, a
 * divergência entre o que o cliente conta e o que a CTPS diz é a própria causa. */
export function resolverContradicao(
  casoId: string,
  contradicaoId: string,
  estado: "RESOLVED" | "DISMISSED" | "UNDER_REVIEW",
  resolucao: string,
  justificativa: string,
): Promise<Contradicao> {
  return chamar(`/api/agente/casos/${casoId}/contradicoes/${contradicaoId}`, {
    method: "PATCH",
    body: JSON.stringify({ estado, resolucao, justificativa }),
  });
}