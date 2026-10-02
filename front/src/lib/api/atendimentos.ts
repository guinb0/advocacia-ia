/** Atendimento: agenda, presença na sala, alertas e o fluxo pós-entrevista. */

import { buscar, comoJson, urlApi, CREDENCIAIS } from "./base";

export type EstadoAtendimento =
  | "AGENDADA"
  | "CLIENTE_AGUARDANDO"
  | "EM_ATENDIMENTO"
  | "ENTREVISTA_FINALIZADA"
  | "ANALISE_JURIDICA"
  | "AGUARDANDO_CONFIRMACAO_ACOES"
  | "QUALIFICACAO"
  | "AVALIACAO_ESCRITORIO"
  | "DOCUMENTACAO_PENDENTE"
  | "CONCLUIDA"
  | "CLIENTE_FALTOU"
  | "CANCELADA";

export const ROTULO_ESTADO: Record<EstadoAtendimento, string> = {
  AGENDADA: "Agendada",
  CLIENTE_AGUARDANDO: "Cliente aguardando",
  EM_ATENDIMENTO: "Em atendimento",
  ENTREVISTA_FINALIZADA: "Entrevista finalizada",
  ANALISE_JURIDICA: "Análise jurídica",
  AGUARDANDO_CONFIRMACAO_ACOES: "Confirmar ações",
  QUALIFICACAO: "Qualificação",
  AVALIACAO_ESCRITORIO: "Avaliação do escritório",
  DOCUMENTACAO_PENDENTE: "Documentação pendente",
  CONCLUIDA: "Concluída",
  CLIENTE_FALTOU: "Cliente faltou",
  CANCELADA: "Cancelada",
};

export interface ConfigLembretes {
  ativo: boolean;
  intervalo_dias: number;
  minutos_antes_no_dia: number[];
}

export interface CasoDoAtendimento {
  id: string;
  categoria: string;
  acao: string;
  origem: "ia" | "triagem" | "manual";
  rascunho_ia: boolean;
  portal_url?: string;
  /** Só na resposta que criou o caso: a senha não pode ser consultada depois. */
  portal?: { url: string; token: string; senha: string; aviso: string } | null;
}

export interface DocumentoConsolidado {
  nome: string;
  tipo: string | null;
  origem: "caso" | "outro_caso" | "entrevista" | "checklist";
  casos: string[];
}

export interface DocumentosConsolidados {
  disponiveis: DocumentoConsolidado[];
  faltantes: DocumentoConsolidado[];
  declarados?: string[];
  atualizado_em?: string;
}

export interface Atendimento {
  id: string;
  cliente: string;
  telefone: string;
  data_hora: string | null;
  duracao_min: number;
  sala: string | null;
  link_cliente: string | null;
  responsavel_id: string | null;
  responsavel_nome: string | null;
  atendente_id: string | null;
  atendente_nome: string | null;
  entrevista_id: string | null;
  casos: CasoDoAtendimento[];
  acoes: { codigo: string; nome: string; origem: string; nova: boolean; caso_id: string }[];
  documentos: DocumentosConsolidados | null;
  estado: EstadoAtendimento;
  origem: "agenda" | "avulso";
  revisada: boolean;
  config_lembretes: ConfigLembretes | null;
  observacao: string | null;
  cliente_na_sala: boolean;
  escritorio_na_sala: boolean;
  versao: number;
  criado_em: string;
  atualizado_em: string;
}

export interface ConfigAtendimento {
  escalonar_apos_min: number;
  tolerancia_falta_min: number;
  enviar_falta_automatico: boolean;
  lembretes: ConfigLembretes;
  fluxo_v2?: boolean;
}

export interface AlertaAtendimento {
  id: string;
  tipo: "cliente_aguardando" | "escalonamento" | "documentacao_pendente";
  atendimento_id: string;
  titulo: string;
  texto: string;
  acao: "entrar" | "assumir" | "abrir_caso";
  dados: {
    cliente?: string;
    sala?: string;
    desde?: string;
    responsavel?: string;
    acoes?: string[];
    casos?: CasoDoAtendimento[];
    disponiveis?: string[];
    pendentes?: string[];
    data_entrevista?: string;
  };
  criado_em: string;
}

const JSON_CT = { "Content-Type": "application/json" };

function enviar<T>(caminho: string, corpo: unknown = {}, metodo = "POST"): Promise<T> {
  return buscar(caminho, { method: metodo, headers: JSON_CT, body: JSON.stringify(corpo) }).then(
    (r) => comoJson<T>(r),
  );
}

const rota = (id: string, sufixo = "") => `/api/atendimentos/${encodeURIComponent(id)}${sufixo}`;

// ---------------------------------------------------------------- agenda

export async function listarAtendimentos(filtro: { de?: string; ate?: string; estados?: string[] } = {}) {
  const q = new URLSearchParams();
  if (filtro.de) q.set("de", filtro.de);
  if (filtro.ate) q.set("ate", filtro.ate);
  for (const e of filtro.estados ?? []) q.append("estado", e);
  const dados = await comoJson<{ atendimentos: Atendimento[] }>(
    await buscar(`/api/atendimentos${q.toString() ? `?${q}` : ""}`),
  );
  return dados.atendimentos;
}

export async function obterAtendimento(id: string): Promise<Atendimento> {
  return comoJson(await buscar(rota(id)));
}

export interface NovoAgendamento {
  cliente: string;
  telefone: string;
  data_hora: string;
  duracao_min?: number;
  responsavel_id?: string | null;
  responsavel_nome?: string | null;
  observacao?: string;
  lembretes?: ConfigLembretes | null;
  enviar_confirmacao?: boolean;
}

export const agendarAtendimento = (dados: NovoAgendamento) => enviar<Atendimento>("/api/atendimentos", dados);

export const editarAtendimento = (
  id: string,
  dados: Partial<NovoAgendamento> & { versao: number; usar_lembretes_padrao?: boolean },
) => enviar<Atendimento>(rota(id), dados, "PATCH");

export const cancelarAtendimento = (id: string) => enviar<Atendimento>(rota(id, "/cancelar"));
export const marcarFaltaAtendimento = (id: string) => enviar<Atendimento>(rota(id, "/falta"));
export const reagendarAtendimento = (id: string) => enviar<Atendimento>(rota(id, "/reagendar"));
export const assumirAtendimento = (id: string) => enviar<Atendimento>(rota(id, "/assumir"));

export interface ResultadoEnvioWhatsapp {
  status: "enviado" | "ja_enviado" | "destinatario_invalido" | "desativado" | "falhou" | "sem_whatsapp" | "sem_telefone";
  enviado: boolean;
  motivo?: string;
  envio?: Record<string, unknown> | null;
}

export const enviarConfirmacaoAtendimento = (id: string, forcar = false) =>
  enviar<ResultadoEnvioWhatsapp>(rota(id, "/confirmacao"), { forcar });

export async function obterConfigAtendimento(): Promise<ConfigAtendimento> {
  return comoJson(await buscar("/api/atendimentos/config"));
}

export const salvarConfigAtendimento = (dados: Partial<ConfigAtendimento>) =>
  enviar<ConfigAtendimento>("/api/atendimentos/config", dados, "PUT");

// --------------------------------------------------------------- presença

export type EventoPresenca = "entrou" | "batida" | "saiu";

/** `keepalive` deixa o "saiu" chegar mesmo com a aba fechando. */
export function avisarPresenca(sala: string, evento: EventoPresenca, lado: "cliente" | "escritorio"): Promise<void> {
  const caminho =
    lado === "cliente"
      ? `/api/chamada/sala/${encodeURIComponent(sala)}/presenca`
      : `/api/atendimentos/sala/${encodeURIComponent(sala)}/presenca`;
  return fetch(urlApi(caminho), {
    method: "POST",
    headers: JSON_CT,
    body: JSON.stringify({ evento }),
    credentials: CREDENCIAIS,
    keepalive: evento === "saiu",
  }).then(
    () => undefined,
    () => undefined,
  );
}

export const ligarEntrevistaAoAtendimento = (dados: {
  entrevista_id: string;
  cliente?: string;
  sala?: string | null;
  atendimento_id?: string | null;
}) => enviar<Atendimento>("/api/atendimentos/entrevista", dados);

// ---------------------------------------------------------------- alertas

export async function listarAlertasAtivos(): Promise<AlertaAtendimento[]> {
  const dados = await comoJson<{ alertas: AlertaAtendimento[] }>(await buscar("/api/alertas/ativos"));
  return dados.alertas;
}

// --------------------------------------------------------- pós-entrevista

export const finalizarEntrevistaAtendimento = (id: string) =>
  enviar<Atendimento>(rota(id, "/finalizar-entrevista"));

export const seguirParaAnalise = (id: string, revisada: boolean) =>
  enviar<Atendimento>(rota(id, "/seguir-para-analise"), { revisada });

/** Só autoridades que a busca devolveu: o resto é descartado no servidor. */
export interface FundamentoAnalise {
  authority_id: string;
  titulo: string;
  tipo: string;
  url?: string | null;
  verificada: boolean;
  motivo: string;
}

export interface SugestaoAcao {
  tipo_codigo: string;
  nome: string;
  confianca: number;
  justificativa: string;
  criterios_atendidos: string[];
  criterios_pendentes: string[];
  documentos_minimos_faltantes: string[];
  fundamentos: FundamentoAnalise[];
  origem: "ia" | "triagem";
  triagem_concorda?: boolean;
}

export interface NovaAcaoSugerida {
  id: string;
  nome: string;
  descricao: string;
  justificativa: string;
  criterios: string[];
  documentos: { nome: string; minimo: boolean }[];
  informacoes_necessarias: string[];
  fundamentos: FundamentoAnalise[];
}

export interface ResultadoAnalise {
  sugestoes: SugestaoAcao[];
  novas_acoes: NovaAcaoSugerida[];
  observacoes: string;
  reserva?: boolean;
  triagem?: { principal: string | null; divergiu: boolean };
  fundamentos_descartados?: number;
  autoridades_consultadas?: number;
  erros_recuperacao?: string[];
}

export interface AnaliseAtendimento {
  id: string;
  atendimento_id: string;
  status: "pendente" | "processando" | "concluida" | "falhou";
  resultado: ResultadoAnalise | null;
  erro: string | null;
  criado_em: string;
  atualizado_em: string;
}

export interface EntradaAnalise {
  transcricao: string;
  relato?: string;
  respostas?: Record<string, unknown>;
  perguntas?: Record<string, string>;
  documentos?: string[];
  triagem_ao_vivo?: Record<string, unknown> | null;
  refazer?: boolean;
}

export const iniciarAnaliseAtendimento = (id: string, entrada: EntradaAnalise) =>
  enviar<{ analise: AnaliseAtendimento; atendimento: Atendimento }>(rota(id, "/analise"), entrada);

export async function obterAnaliseAtendimento(
  id: string,
): Promise<{ analise: AnaliseAtendimento | null; atendimento: Atendimento }> {
  return comoJson(await buscar(rota(id, "/analise")));
}

export interface AcaoConfirmada {
  codigo?: string;
  nome?: string;
  origem: "ia" | "triagem" | "manual";
  nova?: Partial<NovaAcaoSugerida> | null;
}

export const confirmarAcoesAtendimento = (
  id: string,
  dados: { acoes: AcaoConfirmada[]; documentos_declarados?: string[]; cliente?: string; telefone?: string },
) =>
  enviar<{ atendimento: Atendimento; casos: CasoDoAtendimento[]; repetido: boolean }>(
    rota(id, "/confirmar-acoes"),
    dados,
  );

export const concluirQualificacaoAtendimento = (id: string, dados?: Record<string, unknown> | null) =>
  enviar<Atendimento>(rota(id, "/qualificacao"), { dados: dados ?? null });

export interface EstadoAvaliacao {
  status: "pendente" | "enviado" | "entregue" | "lido" | "falhou";
  envio: Record<string, unknown> | null;
}

export async function obterAvaliacaoAtendimento(id: string): Promise<EstadoAvaliacao> {
  return comoJson(await buscar(rota(id, "/avaliacao")));
}

export const enviarAvaliacaoAtendimento = (id: string, telefone: string, forcar = false) =>
  enviar<ResultadoEnvioWhatsapp & { avaliacao: EstadoAvaliacao }>(rota(id, "/avaliacao"), { telefone, forcar });

export const finalizarAtendimento = (id: string, pularAvaliacao = false) =>
  enviar<Atendimento>(rota(id, "/finalizar"), { pular_avaliacao: pularAvaliacao });

export async function obterDocumentosConsolidados(id: string): Promise<DocumentosConsolidados> {
  return comoJson(await buscar(rota(id, "/documentos-consolidados")));
}
