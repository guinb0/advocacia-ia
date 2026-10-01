/** Acervo Jurídico: leis versionadas, jurisprudência, embeddings e alertas (`/api/acervo/*`). */

import { buscar, comoJson } from "./base";

export type CorAcervo = "verde" | "amarelo" | "vermelho" | "cinza" | "azul";

export type SeloAcervo = { status: string; cor: CorAcervo; texto: string };

/** Toda leitura volta neste envelope: sem a migration 011 ou com o banco fora, a tela explica em vez de quebrar. */
export type EnvelopeAcervo = { migracao_aplicada: boolean | null; disponivel: boolean; erro?: string };

export type VerificacaoRag = { nome: string; ok: boolean; detalhe: string; selo: SeloAcervo };

export type SaudeRag = {
  modelo_configurado: string;
  dimensoes_configuradas: number;
  modelos_no_banco: string[];
  dimensoes_no_banco: number[];
  cobertura_percentual: number;
  chunks: number;
  chunks_com_embedding: number;
  chunks_pendentes: number;
  chunks_invalidados: number;
  verificacoes: VerificacaoRag[];
  saudavel: boolean;
};

export type SincronizacaoAcervo = {
  id: number;
  document_id: string;
  iniciada_em: string;
  concluida_em: string | null;
  status: string;
  origem: string;
  solicitado_por: string;
  dispositivos_total?: number;
  dispositivos_novos?: number;
  dispositivos_alterados?: number;
  dispositivos_revogados?: number;
  dispositivos_removidos?: number;
  embeddings_gerados?: number;
  embeddings_mantidos?: number;
  embeddings_invalidados?: number;
  tokens_embeddings_aprox?: number;
  duracao_ms?: number | null;
  erro: string;
};

export type ResumoAcervo = EnvelopeAcervo & {
  cartoes?: {
    normas: number;
    dispositivos_vigentes: number;
    revogados: number;
    versoes_historicas: number;
    jurisprudencia: number;
    jurisprudencia_aguardando: number;
    jurisprudencia_superada: number;
    alertas_abertos: number;
    alertas_altos: number;
  };
  normas_por_cor?: Partial<Record<CorAcervo, number>>;
  sincronizacao?: {
    automatica: boolean;
    agenda: string;
    proxima: string | null;
    ultima: SincronizacaoAcervo | null;
    fila: string;
  };
  saude_rag?: SaudeRag;
};

export type ContagemEmbeddings = {
  chunks: number;
  chunks_com_embedding: number;
  chunks_pendentes: number;
  chunks_invalidados: number;
};

export type NormaAcervo = {
  id: string;
  nome: string;
  nome_oficial: string;
  numero: string;
  ano: string;
  categoria: string;
  tipo: string;
  orgao: string;
  fonte: string;
  url: string;
  chave_norma: string;
  selo: SeloAcervo;
  ultimo_erro: string;
  ultima_verificacao: string | null;
  ultima_atualizacao: string | null;
  proxima_verificacao: string | null;
  fonte_modificada_em: string | null;
  content_hash: string;
  encoding: string;
  parser: string;
  dispositivos: number;
  artigos: number;
  revogados: number;
  versoes_historicas: number;
  legado: number;
  sem_vigencia: number;
  embeddings: ContagemEmbeddings;
  desatualizada: boolean;
};

export type NoArvoreAcervo = {
  id: number;
  dispositivo_id: string;
  tipo: string;
  rotulo: string;
  status: string;
  versao: number;
  valid_from: string | null;
  filhos: NoArvoreAcervo[];
  /** Só nos artigos: Livro/Título/Capítulo/Seção em que ele está. */
  contexto?: string[];
};

export type AlertaAcervo = {
  id: number;
  criado_em: string;
  tipo: string;
  severidade: "baixa" | "media" | "alta";
  document_id: string;
  dispositivo_id: string;
  authority_id: string;
  titulo: string;
  detalhe: string;
  resolvido_em: string | null;
};

export type AnotacaoAcervo = {
  id: number;
  criado_em: string;
  autor: string;
  document_id: string;
  dispositivo_id: string;
  authority_id: string;
  texto: string;
};

export type NormaDetalhe = NormaAcervo & {
  arvore: NoArvoreAcervo[];
  sincronizacoes: SincronizacaoAcervo[];
  alertas: AlertaAcervo[];
  anotacoes: AnotacaoAcervo[];
};

export type VersaoDispositivo = {
  id: number;
  versao: number;
  status: string;
  valid_from: string | null;
  valid_until: string | null;
  content_hash: string;
  texto: string;
  superada_por: string;
};

export type DispositivoAcervo = {
  id: number;
  document_id: string;
  norma: string;
  dispositivo_id: string;
  rotulo: string;
  tipo: string;
  texto: string;
  status: string;
  versao: number;
  valid_from: string | null;
  valid_until: string | null;
  valid_from_origem: string;
  content_hash: string;
  url: string;
  coletado_em: string | null;
  ultima_verificacao: string | null;
  superada_por: string;
  hierarquia: { ancestrais?: string[] };
  versoes: VersaoDispositivo[];
  embedding: {
    id: number;
    tem_embedding: boolean;
    modelo: string | null;
    dimensoes: number | null;
    gerado_em: string | null;
    content_hash: string | null;
    invalidado_em: string | null;
    artigo: string;
    versao_vinculada: number | null;
  } | null;
  como_o_gate_ve: { authority_id: string; chave: string; status: string; vigente_hoje: boolean | null; verificada: boolean };
  anotacoes: AnotacaoAcervo[];
};

export type JurisprudenciaAcervo = {
  id: string;
  tipo: string;
  tribunal: string;
  orgao: string;
  numero: string;
  titulo: string;
  status_juridico: string;
  superado_por: string;
  verificada: boolean;
  selo: SeloAcervo;
  url: string;
  fonte: string;
  vigencia_inicio: string | null;
  vigencia_fim: string | null;
  ultima_verificacao: string | null;
  texto: string;
};

export type ProblemaAcervo = { tipo: string; severidade: "baixa" | "media" | "alta"; norma: string; titulo: string; alerta_id?: number };

export type ConfiguracaoAcervo = {
  sincronizacao_ativa: boolean;
  agenda: string;
  embeddings_configurados: boolean;
  validade_dias: number;
  armazenamento: "pgvector" | "json-local";
};

export type DestinoAutoridade =
  | { tipo: "dispositivo"; document_id: string; version_id: number }
  | { tipo: "jurisprudencia"; authority_id: string }
  | { tipo: "desconhecida"; authority_id: string };

type Lista<T> = EnvelopeAcervo & { itens?: T[] };

function consulta(params: Record<string, string>): string {
  const busca = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== ""));
  const texto = busca.toString();
  return texto ? `?${texto}` : "";
}

export async function resumoDoAcervo(): Promise<ResumoAcervo> {
  return comoJson(await buscar("/api/acervo/resumo"));
}

export async function configuracaoDoAcervo(): Promise<ConfiguracaoAcervo> {
  return comoJson(await buscar("/api/acervo/configuracao"));
}

export async function normasDoAcervo(filtro: { busca?: string; status?: string } = {}): Promise<Lista<NormaAcervo>> {
  return comoJson(await buscar(`/api/acervo/normas${consulta({ busca: filtro.busca ?? "", status: filtro.status ?? "" })}`));
}

export async function normaDoAcervo(documentId: string): Promise<EnvelopeAcervo & { norma?: NormaDetalhe }> {
  return comoJson(await buscar(`/api/acervo/normas/${encodeURIComponent(documentId)}`));
}

export async function dispositivoDoAcervo(versionId: number): Promise<EnvelopeAcervo & { dispositivo?: DispositivoAcervo }> {
  return comoJson(await buscar(`/api/acervo/dispositivos/${versionId}`));
}

export async function resolverAutoridadeDoAcervo(autoridade: string): Promise<EnvelopeAcervo & { destino?: DestinoAutoridade }> {
  return comoJson(await buscar(`/api/acervo/autoridades/resolver${consulta({ autoridade })}`));
}

export async function jurisprudenciaDoAcervo(filtro: { busca?: string; status?: string } = {}): Promise<Lista<JurisprudenciaAcervo>> {
  return comoJson(await buscar(`/api/acervo/jurisprudencia${consulta({ busca: filtro.busca ?? "", status: filtro.status ?? "" })}`));
}

export async function sincronizacoesDoAcervo(documentId = ""): Promise<Lista<SincronizacaoAcervo>> {
  return comoJson(await buscar(`/api/acervo/sincronizacoes${consulta({ document_id: documentId })}`));
}

export async function alertasDoAcervo(): Promise<Lista<AlertaAcervo>> {
  return comoJson(await buscar("/api/acervo/alertas"));
}

export async function problemasDoAcervo(): Promise<Lista<ProblemaAcervo>> {
  return comoJson(await buscar("/api/acervo/problemas"));
}

export async function verificarNormaAgora(documentId: string): Promise<{ enfileirado: boolean; tarefa: string }> {
  return comoJson(await buscar(`/api/acervo/normas/${encodeURIComponent(documentId)}/verificar`, { method: "POST" }));
}

export async function reindexarNorma(documentId: string): Promise<{ enfileirado: boolean; tarefa: string }> {
  return comoJson(
    await buscar(`/api/acervo/normas/${encodeURIComponent(documentId)}/reindexar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmar: true }),
    }),
  );
}

export async function anotarNoAcervo(anotacao: {
  texto: string;
  document_id?: string;
  dispositivo_id?: string;
  authority_id?: string;
}): Promise<{ id: number }> {
  return comoJson(
    await buscar("/api/acervo/anotacoes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(anotacao),
    }),
  );
}

export async function resolverAlertaDoAcervo(alertaId: number): Promise<{ resolvido: boolean }> {
  return comoJson(await buscar(`/api/acervo/alertas/${alertaId}/resolver`, { method: "POST" }));
}

export async function importarJurisprudencia(itens: unknown[]): Promise<{
  novas: number;
  alteradas: number;
  inalteradas: number;
  superadas: number;
  invalidas: number;
}> {
  return comoJson(
    await buscar("/api/acervo/jurisprudencia/importar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itens }),
    }),
  );
}
