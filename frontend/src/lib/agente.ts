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

import { ApiError, CREDENCIAIS, cabecalhos, urlApi } from "./api";

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
  anexos?: { nome: string; url: string; pagina?: number | null; campo?: string | null }[];
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
    anexo?: { nome: string; url: string | null; indexado: boolean };
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
  readiness: {
    /** Dá para GERAR. Falta de prova não derruba mais isto — ver `readiness.py`. */
    ready: boolean;
    /** O que impede a peça de existir. Hoje só "caso não classificado". */
    blocking_issues: string[];
    warnings: string[];
    /** O que falta COMPROVAR. A peça sai assim mesmo, marcada. */
    pendencias?: string[];
    /** Dá para PROTOCOLAR: nada falta, nem estrutura nem prova. */
    completo?: boolean;
  };
  review: { findings?: AchadoRevisao[]; summary?: string; blocking?: number };
  blocking_findings: number;
  model?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  sections?: SecaoPeticao[];
  jurimetria?: {
    disponivel: boolean;
    origem?: string;
    consulta_vetorial?: boolean;
    aviso?: string;
    sintese?: string;
    estatisticas?: {
      processos_analisados: number;
      desfechos_merito: { processos: number; favoraveis: number; percentual: number };
      similaridade_amostra: { minima: number; mediana: number; maxima: number };
    };
    fundamentos?: Array<{ ponto?: string; impacto?: string; processos: string[] }>;
    riscos?: Array<{ ponto?: string; distincao?: string; processos: string[] }>;
    precedentes?: Array<{
      indice: string;
      processo?: string;
      resultado?: string;
      vara?: string;
      similaridade?: number;
      url?: string;
    }>;
  };
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
      nome?: string;
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

/** A chamada crua a `/api/agente/*`, com o cookie de sessão e o tratamento de erro.
 *
 * Exportada com nome próprio porque `lib/conversas.ts` fala com as mesmas rotas: sem
 * isto, o chat geral teria um `fetch` paralelo — e o dia em que a autenticação mudasse,
 * uma das duas telas passaria a receber 401 sem ninguém saber por quê.
 */
export async function chamarAgente<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const resposta = await fetch(urlApi(caminho), {
    ...init,
    // O cookie de sessão só acompanha a chamada com isto — ver `lib/api.ts`.
    credentials: CREDENCIAIS,
    //
    // `FormData` fica **sem** `Content-Type` de propósito: o navegador precisa escrever o
    // cabeçalho ele mesmo, porque só ele conhece o boundary que separa as partes. Declarar
    // `multipart/form-data` à mão produz um corpo que o servidor não consegue desmontar, e o
    // erro que aparece é um 422 reclamando de campo ausente.
    headers: cabecalhos({
      ...(init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...((init.headers as Record<string, string>) ?? {}),
    }),
  });

  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe, { status: resposta.status });
  }
  return corpo as T;
}

/** Apelido interno: as demais funções deste arquivo já se escrevem com ele. */
const chamar = chamarAgente;

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
): Promise<{
  caso_ref: string;
  documentos_enviados: number;
  documentos_com_falha: number;
  entrevistas_enviadas?: number;
  entrevistas_com_falha?: number;
  ultimo_erro?: string | null;
}> {
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

/**
 * Dispara a minuta. Responde 202: a peça aparece no dossiê quando ficar pronta.
 *
 * `requested_at` e `expected_sections` são o que permite acompanhar a redação em vez de
 * anunciar que ela terminou: o primeiro delimita esta geração, o segundo diz quantas seções
 * o modelo ainda vai escrever.
 */
export function gerarPeticao(casoId: string, opcao = 0): Promise<{
  run_id: string;
  status: string;
  requested_at: string;
  expected_sections?: number;
  caso_ref?: string;
  embeddings?: string[];
}> {
  return chamar(`/api/agente/casos/${casoId}/peticao?opcao=${opcao}`, { method: "POST" });
}

export interface AnaliseFluxo {
  resumo: string;
  cruzamento_entrevista_documentos?: string;
  pontos_fortes: string[];
  lacunas: string[];
  fatos_confirmados?: string[];
  fatos_so_na_entrevista?: string[];
  achados_documentos?: Array<{
    informacao: string;
    documento: string;
    citacao?: string;
    relevancia?: string;
    contradiz?: boolean;
  }>;
  observacoes: string;
}

export interface PreparacaoFluxo {
  documentos_lidos?: number;
  achados_documentos?: number;
  checklist_obrigatorios?: number;
  checklist_entregues?: number;
}

export interface EstrategiaFluxo {
  titulo: string;
  tese: string;
  fundamentacao: string;
  pedidos: string[];
  riscos: string[];
  quando_usar: string;
}

export interface EstadoPeticaoFluxo {
  entrevista?: {
    entrevista_id: string;
    arquivo?: string;
    caracteres: number;
    previa: string;
    texto: string;
  };
  analise?: AnaliseFluxo;
  estrategias?: EstrategiaFluxo[];
  escolha?: number;
  preparacao?: PreparacaoFluxo;
  categoria?: string;
  taxonomy_code?: string;
  peticao_id?: string | null;
  peticao_pronta?: boolean;
}

export function estadoPeticaoFluxo(casoId: string): Promise<EstadoPeticaoFluxo> {
  return chamar(`/api/agente/casos/${casoId}/peticao-fluxo`);
}

export function analisarPeticaoFluxo(casoId: string): Promise<{
  entrevista_id: string;
  analise: AnaliseFluxo;
  taxonomy_code: string;
  preparacao?: PreparacaoFluxo;
}> {
  return chamar(`/api/agente/casos/${casoId}/peticao-fluxo/analise`, { method: "POST" });
}

export function proporEstrategiasPeticaoFluxo(casoId: string): Promise<{
  estrategias: EstrategiaFluxo[];
}> {
  return chamar(`/api/agente/casos/${casoId}/peticao-fluxo/estrategias`, { method: "POST" });
}

export function gerarAnaliseEPeticao(casoId: string): Promise<{
  run_id: string;
  status: string;
  requested_at: string;
  generation_id: string;
  pipeline?: string;
  peticao: Peticao;
  analise?: AnaliseFluxo;
}> {
  return chamar(`/api/agente/casos/${casoId}/peticao-fluxo/completo`, { method: "POST" });
}

export function gerarPeticaoFluxo(
  casoId: string,
  opcao: number,
): Promise<{
  run_id: string;
  status: string;
  requested_at: string;
  pipeline?: string;
  embeddings?: string[];
}> {
  return chamar(`/api/agente/casos/${casoId}/peticao-fluxo/gerar?opcao=${opcao}`, {
    method: "POST",
  });
}

export interface ProgressoPeticao {
  status: "RUNNING" | "DONE";
  /** Seções redigidas mais a revisão — execuções de IA já gravadas, não estimativa. */
  completed_steps: number;
  /** Só existe quando a peça terminou; é o sinal de que a tela pode mostrá-la. */
  generation_id: string | null;
  blocking_findings: number;
}

/** Onde a redação está agora. `desde` é o `requested_at` devolvido pelo POST. */
export function progressoPeticao(casoId: string, desde: string): Promise<ProgressoPeticao> {
  return chamar(
    `/api/agente/casos/${casoId}/peticao/progresso?desde=${encodeURIComponent(desde)}`,
  );
}

export function buscarPeticao(casoId: string, pecaId: string): Promise<Peticao> {
  return chamar(`/api/agente/casos/${casoId}/peticao/${pecaId}`);
}

export function salvarRascunhoPeticao(
  casoId: string,
  pecaId: string,
  secoes: { code: string; content: string }[],
): Promise<Peticao> {
  return chamar(`/api/agente/casos/${casoId}/peticao/${pecaId}/rascunho`, {
    method: "PUT",
    body: JSON.stringify({ secoes }),
  });
}

/**
 * Aprovar ou rejeitar — a revisão humana que o `§2.10` exige antes de qualquer uso.
 *
 * `secoes` leva o texto como o advogado o entregou. O agente guarda essa versão **ao lado**
 * da gerada, nunca por cima: a diferença entre as duas é o único sinal que o sistema tem
 * sobre o estilo do escritório, e ela deixa de existir se uma delas for sobrescrita.
 *
 * Omitir é diferente de mandar as seções idênticas. O primeiro caso é "revisei sem mexer no
 * texto"; o segundo prova que o advogado passou por cada seção.
 */
export function decidirPeticao(
  casoId: string,
  pecaId: string,
  aprovada: boolean,
  nota?: string,
  secoes?: { code: string; content: string }[],
): Promise<Peticao> {
  return chamar(`/api/agente/casos/${casoId}/peticao/${pecaId}`, {
    method: "PATCH",
    body: JSON.stringify({
      aprovada,
      nota: nota ?? null,
      ...(secoes ? { secoes } : {}),
    }),
  });
}

/* ------------------------------------------------------------------- estilo */

/** O padrão de escrita do grupo, com a amostra e o nível que o produziram. */
export interface PerfilDeEstilo {
  level: string;
  taxonomy_code: string | null;
  document_type: string | null;
  /** Peças **deste** grupo. `parent_n` são as do ancestral que completou o padrão. */
  n: number;
  parent_n: number;
  parent_level: string | null;
  shrinkage_k: number;
  schema_version: string;
  contributing_levels: string[];
  raw: Record<string, EstatisticaDeEstilo>;
  effective: Record<string, EstatisticaDeEstilo>;
}

export interface EstatisticaDeEstilo {
  n: number;
  median: number;
  mad: number;
  p10: number | null;
  p25: number | null;
  p75: number | null;
  p90: number | null;
}

export function perfilDeEstilo(
  taxonomyCode?: string | null,
  documentType = "INITIAL_PETITION",
  unidade = "DOCUMENT",
): Promise<PerfilDeEstilo> {
  const busca = new URLSearchParams({ document_type: documentType, unidade });
  if (taxonomyCode) busca.set("taxonomy_code", taxonomyCode);
  return chamar(`/api/agente/estilo/perfil?${busca.toString()}`);
}

export interface NoDaTaxonomia {
  code: string;
  label: string;
  description?: string;
}

export interface ConfiguracaoDeGeracao {
  taxonomy_code: string;
  document_type: string;
  display_name: string;
  drafting_instructions: string;
  required_documents: string[];
  updated_at?: string | null;
}

export function configuracaoDeGeracao(
  taxonomyCode: string,
  documentType = "INITIAL_PETITION",
): Promise<ConfiguracaoDeGeracao> {
  const busca = new URLSearchParams({ taxonomy_code: taxonomyCode, document_type: documentType });
  return chamar(`/api/agente/estilo/configuracao?${busca}`);
}

export function salvarConfiguracaoDeGeracao(
  configuracao: ConfiguracaoDeGeracao,
): Promise<ConfiguracaoDeGeracao> {
  return chamar("/api/agente/estilo/configuracao", {
    method: "PUT",
    body: JSON.stringify(configuracao),
  });
}

/** Os códigos de ação que o agente conhece. A tela oferece só estes. */
export async function taxonomiaDeEstilo(): Promise<NoDaTaxonomia[]> {
  const dados = await chamar<{ items?: NoDaTaxonomia[]; nodes?: NoDaTaxonomia[] }>(
    "/api/agente/estilo/taxonomia",
  );
  return dados.items ?? dados.nodes ?? [];
}

/** As peças já cadastradas, com o que a segmentação achou em cada uma. */
export interface PecaDeEstilo {
  id: string;
  taxonomy_code: string;
  document_type: string;
  source: string;
  filename: string | null;
  document_format: string | null;
  word_count: number;
  segmentation: { quality: "FULL" | "PARTIAL" | "POOR"; recognized_ratio: number };
  eligibility: {
    eligible_for_document_profile: boolean;
    eligible_for_section_profile: boolean;
    document_eligibility_reasons: string[];
    section_eligibility_reasons: string[];
  };
  created_at: string | null;
}

export async function pecasDeEstilo(
  taxonomyCode?: string | null,
  documentType = "INITIAL_PETITION",
): Promise<PecaDeEstilo[]> {
  const busca = new URLSearchParams();
  if (taxonomyCode) busca.set("taxonomy_code", taxonomyCode);
  if (documentType) busca.set("document_type", documentType);
  const dados = await chamar<{ items: PecaDeEstilo[] }>(
    `/api/agente/estilo/pecas${busca.toString() ? `?${busca}` : ""}`,
  );
  return dados.items ?? [];
}

/** Sobe uma peça pronta do escritório para o corpus de estilo. */
export async function enviarPecaDeEstilo(
  arquivo: File,
  taxonomyCode: string,
  documentType = "INITIAL_PETITION",
): Promise<{ id: string; word_count: number }> {
  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  corpo.append("taxonomy_code", taxonomyCode);
  corpo.append("document_type", documentType);
  return chamar(`/api/agente/estilo/pecas`, { method: "POST", body: corpo });
}

/**
 * URL do arquivo da peça. O download passa pelo backend, que é quem tem o token do agente.
 *
 * O PDF sai `inline` do servidor, e é por isso que ele pode ser exibido dentro do dossiê;
 * o `.docx` continua vindo como anexo, para o advogado editar e assinar.
 */
export function urlDaPeticao(
  casoId: string,
  pecaId: string,
  formato: "pdf" | "docx" = "docx",
): string {
  return urlApi(`/api/agente/casos/${casoId}/peticao/${pecaId}/arquivo?formato=${formato}`);
}

/**
 * O arquivo da peça em memória, para a tela exibi-lo sem uma segunda viagem ao servidor.
 *
 * Não dá para apontar um `<iframe>` direto para a URL do backend: a sessão vive num cookie
 * `HttpOnly` de **outra origem** (a API está noutra porta), e o navegador não manda cookie
 * de terceiro numa subrequisição de moldura — o visualizador abriria em branco ou em 401.
 * Buscando por `fetch` com `credentials`, o cookie vai; o `blob:` resultante é da mesma
 * origem da página e sempre renderiza. O mesmo objeto serve ao botão de baixar.
 */
export async function baixarArquivoDaPeticao(
  casoId: string,
  pecaId: string,
  formato: "pdf" | "docx" = "pdf",
): Promise<Blob> {
  const resposta = await fetch(urlDaPeticao(casoId, pecaId, formato), {
    headers: cabecalhos(),
    credentials: CREDENCIAIS,
  });
  if (!resposta.ok) {
    throw new ApiError(`Não foi possível abrir o arquivo da peça (erro ${resposta.status}).`);
  }
  return resposta.blob();
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
    credentials: CREDENCIAIS,
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

export function gerarEstrategia(casoId: string): Promise<{
  run_id: string;
  status: string;
  preparo?: {
    classificacao?: boolean;
    pesquisa?: boolean;
    analise_enfileirada?: boolean;
    pesquisa_enfileirada?: boolean;
  };
}> {
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

export async function removerPecaDeEstilo(id: string): Promise<void> {
  await chamar(`/api/agente/estilo/pecas/${encodeURIComponent(id)}`, { method: "DELETE" });
}


/* ------------------------------------------------------------- chat do caso
 *
 * A conversa com o agente sobre UM caso, e a proposta de alteração que pode sair dela.
 *
 * Os tipos daqui são os que as DUAS telas usam — o painel ao lado do dossiê e o chat
 * geral (`lib/conversas.ts` importa deste arquivo de propósito). Uma segunda tradução
 * divergiria no dia em que `preview` mudasse de nome, e a confirmação passaria a mostrar
 * o "antes" vazio numa das telas: o advogado aprovaria uma alteração sem ver o que perde.
 */

/** A natureza de cada afirmação da resposta. É o que vira o selo na tela.
 *
 * Chega no vocabulário do agente (`PROVEN_FACT`, `ALLEGED_FACT`) e assim fica: traduzir
 * para nomes locais faria o mapa de selos depender de uma tabela a mais para valer, e a
 * distinção entre provado e alegado é justamente a que o guardrail do backend protege. */
export type NaturezaDaAfirmacao =
  | "PROVEN_FACT"
  | "ALLEGED_FACT"
  | "HYPOTHESIS"
  | "INFERENCE"
  | "RECOMMENDATION"
  | "STATISTICAL_PATTERN"
  | "PRECEDENT";

export interface AfirmacaoDoAgente {
  statement: string;
  nature: NaturezaDaAfirmacao;
  /** Proveniência: o fato, o documento ou o caso de onde a afirmação saiu. */
  refs: string[];
}

/** Uma alteração que o agente propôs — e que NÃO aconteceu.
 *
 * Nada é aplicado sem confirmação explícita (`AGENTS.md §2.4`), e é por isso que o
 * `antes` viaja junto: proposta sem o antes não é revisável, porque quem aprova não sabe
 * o que perde. */
export interface PropostaDoAgente {
  id: string;
  acao: string;
  intencao: string;
  motivo: string;
  antes: string;
  depois: string;
  impacto: string[];
  risco: "NONE" | "REVERSIBLE" | "SENSITIVE";
  /** `PENDING` é a única que a tela oferece para aplicar; as demais são histórico. */
  estado: "PENDING" | "APPLIED" | "EXPIRED" | "REJECTED" | string;
  expiraEm: string | null;
}

/** Uma linha da conversa, com o lastro junto do texto.
 *
 * O lastro anda com a mensagem, e não em estado à parte: reabrir a conversa mostrando a
 * conclusão sem as afirmações que a sustentam é exatamente o que este sistema não pode
 * produzir. */
export interface MensagemDoChat {
  id: string;
  papel: "USER" | "ASSISTANT";
  conteudo: string;
  criadaEm: string;
  citacoes: string[];
  afirmacoes: AfirmacaoDoAgente[];
  /** O que o agente disse que faltou para responder melhor (as `gaps` de lá). */
  pendencias: string[];
}

export interface RespostaDoChat {
  /** O fio do raciocínio do agente. Sem ele, a pergunta seguinte recomeça do zero. */
  conversaId: string;
  mensagem: MensagemDoChat;
  propostas: PropostaDoAgente[];
}

/* ------------------------------------------------------------------ tradução */

function objeto(valor: unknown): Record<string, unknown> {
  return valor && typeof valor === "object" && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : {};
}

function textos(valor: unknown): string[] {
  return Array.isArray(valor) ? valor.map((item) => String(item)) : [];
}

function traduzirAfirmacoes(valor: unknown): AfirmacaoDoAgente[] {
  if (!Array.isArray(valor)) return [];
  return valor.map((item) => {
    const bruta = objeto(item);
    return {
      statement: String(bruta.statement ?? ""),
      // `INFERENCE` como último recurso, e não `PROVEN_FACT`: natureza desconhecida tem
      // de cair no lado que promete menos. O contrário faria um campo novo do agente
      // aparecer como prova na tela.
      nature: (bruta.nature ?? "INFERENCE") as NaturezaDaAfirmacao,
      refs: textos(bruta.refs),
    };
  });
}

/** O formato do agente (`intent`, `preview.before/after`) no vocabulário da tela.
 *
 * Exportada porque `lib/conversas.ts` recebe as mesmas propostas pela conversa geral: as
 * duas telas mostram a mesma proposta, e uma cópia desta função é uma chance a mais de
 * elas discordarem sobre o que está sendo aprovado.
 */
export function traduzirPropostaCrua(cru: unknown): PropostaDoAgente {
  const bruta = objeto(cru);
  const previa = objeto(bruta.preview);
  return {
    id: String(bruta.id ?? ""),
    acao: String(bruta.action ?? ""),
    intencao: String(bruta.intent ?? ""),
    motivo: String(bruta.rationale ?? ""),
    antes: String(previa.before ?? ""),
    depois: String(previa.after ?? ""),
    impacto: textos(bruta.impact),
    risco: (bruta.risk ?? "REVERSIBLE") as PropostaDoAgente["risco"],
    estado: String(bruta.status ?? "PENDING"),
    expiraEm: bruta.expires_at ? String(bruta.expires_at) : null,
  };
}

function traduzirMensagem(cru: unknown): MensagemDoChat {
  const bruta = objeto(cru);
  const lastro = objeto(bruta.payload);
  const papel = String(bruta.role ?? bruta.papel ?? "ASSISTANT").toUpperCase();
  return {
    id: String(bruta.id ?? ""),
    papel: papel === "USER" ? "USER" : "ASSISTANT",
    conteudo: String(bruta.content ?? ""),
    criadaEm: String(bruta.created_at ?? new Date().toISOString()),
    citacoes: textos(bruta.citations),
    afirmacoes: traduzirAfirmacoes(lastro.assertions),
    pendencias: textos(lastro.gaps),
  };
}

/* --------------------------------------------------------------------- rotas */

/** A pergunta sobre um caso. Síncrona: quem perguntou está olhando a conversa. */
export async function perguntarAoCaso(
  casoId: string,
  mensagem: string,
  conversaId?: string,
): Promise<RespostaDoChat> {
  const corpo = await chamar<{
    conversation_id?: string;
    message?: unknown;
    proposals?: unknown[] | null;
  }>(`/api/agente/casos/${casoId}/chat`, {
    method: "POST",
    body: JSON.stringify({
      message: mensagem,
      ...(conversaId ? { conversation_id: conversaId } : {}),
    }),
  });

  return {
    conversaId: String(corpo.conversation_id ?? conversaId ?? ""),
    mensagem: traduzirMensagem(corpo.message),
    propostas: (corpo.proposals ?? []).map(traduzirPropostaCrua),
  };
}

/** A transcrição que o agente guarda daquele fio — para reabrir a conversa do caso. */
export async function conversaDoCaso(
  casoId: string,
  conversaId: string,
): Promise<MensagemDoChat[]> {
  const corpo = await chamar<{ messages?: unknown[] | null }>(
    `/api/agente/casos/${casoId}/chat/${conversaId}`,
  );
  return (corpo.messages ?? []).map(traduzirMensagem);
}

/** Aplica a proposta. É o único caminho pelo qual uma conversa altera o caso. */
export async function confirmarProposta(
  casoId: string,
  propostaId: string,
): Promise<PropostaDoAgente> {
  return traduzirPropostaCrua(
    await chamar<unknown>(
      `/api/agente/casos/${casoId}/chat/propostas/${propostaId}/confirmar`,
      { method: "POST" },
    ),
  );
}
