/** Atendimento da Documentação e municípios. */

import { buscar, comoJson } from "./base";

export interface AtendimentoDocumentacao {
  entrevista_id: string;
  caso_id: string | null;
  cliente: string;
  sala: string | null;
  status: "entrevista" | "solicitado" | "aguardando_documentacao" | "assumido" | "encerrado";
  entrevistador_nome: string;
  documentador_nome: string | null;
  iniciado_em: string;
  solicitado_em: string | null;
  documentos: null | {
    categoria: string;
    arquivos_recebidos: number;
    obrigatorios_total: number;
    obrigatorios_entregues: number;
    percentual: number;
    pendencias: string[];
    a_conferir: string[];
    processando: number;
    em_triagem: number;
    pronto: boolean;
    ultima_entrega_em: string | null;
  };
  /** ISO-8601 UTC da última batida do entrevistador (a cada ~30s enquanto a
   *  entrevista está aberta). Fica velho quando ele sai — é o sinal de que a
   *  chamada já não está de pé. */
  atualizado_em: string;
}

export async function registrarAtendimentoDocumentacao(entrevistaId: string, cliente: string): Promise<void> {
  await comoJson(await buscar("/api/documentacao/atendimentos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entrevista_id: entrevistaId, cliente }),
  }));
}

export async function baterAtendimentoDocumentacao(entrevistaId: string): Promise<void> {
  await comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/batida`, { method: "POST" }));
}

export async function solicitarDocumentacao(entrevistaId: string, casoId: string, sala: string, cliente: string): Promise<void> {
  await comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/solicitar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caso_id: casoId, sala, cliente }),
  }));
}

export async function obterAtendimentoDocumentacao(entrevistaId: string): Promise<AtendimentoDocumentacao> {
  return comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}`));
}

export async function listarAtendimentosDocumentacao(): Promise<{
  entrevistas_ativas: number;
  solicitacoes: number;
  aguardando_documentacao?: number;
  documentadores_online: number;
  arquivos_recebidos: number;
  pendencias_obrigatorias: number;
  itens_a_conferir: number;
  casos_prontos: number;
  atendimentos: AtendimentoDocumentacao[];
}> {
  return comoJson(await buscar("/api/documentacao/atendimentos"));
}

export async function registrarPresencaDocumentacao(): Promise<void> {
  await comoJson(await buscar("/api/documentacao/presenca", { method: "POST" }));
}

/** Tira o atendimento da fila (entrevista fechada sem pedir a Documentação). */
export async function encerrarAtendimentoDocumentacao(entrevistaId: string): Promise<void> {
  await comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/encerrar`, { method: "POST" }));
}

export async function assumirAtendimentoDocumentacao(entrevistaId: string): Promise<AtendimentoDocumentacao> {
  return comoJson(await buscar(`/api/documentacao/atendimentos/${encodeURIComponent(entrevistaId)}/assumir`, { method: "POST" }));
}

export interface MunicipioLocalidade { id: number; nome: string; uf: string }

export async function listarMunicipios(uf: string): Promise<MunicipioLocalidade[]> {
  const dados = await comoJson<{ municipios: MunicipioLocalidade[] }>(
    await buscar(`/api/localidades/municipios?uf=${encodeURIComponent(uf)}`),
  );
  return dados.municipios;
}
