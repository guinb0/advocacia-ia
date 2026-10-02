/** Catálogo de tipos de caso. */

import type { EventoHistorico, ImpactoTipoCaso, TipoCaso } from "../types";
import { buscar, comoJson } from "./base";

// ------------------------------------------------------- tipos de caso
// Consultar é livre para a equipe (a criação do caso precisa da lista); criar e
// editar pedem o módulo `tipos_caso` (ver `app/tipos_caso.py`).

export async function listarTiposCaso(incluirInativos = false): Promise<TipoCaso[]> {
  const r = await comoJson<{ tipos: TipoCaso[] }>(
    await buscar(`/api/tipos-caso?incluir_inativos=${incluirInativos}`),
  );
  return r.tipos;
}

/** O que a tela manda ao criar ou editar uma ação. */
export interface DadosTipoCaso {
  nome: string;
  descricao: string;
  /** Como o modelo da triagem reconhece a ação no relato. */
  quando_usar: string;
  pistas: { expressao: string; peso: number }[];
  /** Item sem `codigo` é novo: o servidor dá um que nunca se repete. */
  itens: {
    codigo: string;
    nome: string;
    obrigatorio: boolean;
    tipo_documento: string | null;
    observacao: string;
  }[];
}

export async function criarTipoCaso(
  dados: DadosTipoCaso & { codigo?: string },
): Promise<TipoCaso> {
  return comoJson(
    await buscar("/api/tipos-caso", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

export async function editarTipoCaso(
  codigo: string,
  /** `versao` é a lida ao abrir o formulário; outra no servidor = 409. */
  dados: DadosTipoCaso & { ativo: boolean; versao: number; motivo?: string },
): Promise<TipoCaso> {
  return comoJson(
    await buscar(`/api/tipos-caso/${encodeURIComponent(codigo)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

export async function impactoTipoCaso(codigo: string): Promise<ImpactoTipoCaso> {
  return comoJson(await buscar(`/api/tipos-caso/${encodeURIComponent(codigo)}/impacto`));
}

export async function historicoTipoCaso(codigo: string): Promise<EventoHistorico[]> {
  const r = await comoJson<{ eventos: EventoHistorico[] }>(
    await buscar(`/api/tipos-caso/${encodeURIComponent(codigo)}/historico`),
  );
  return r.eventos;
}

// ------------------------------------------- critérios e tipos gerados pela IA
// Ver `app/criterios_caso.py`: critério ajuda a análise a reconhecer a ação no
// relato; não muda o checklist do cliente.

export interface CriterioTipoCaso {
  id: string;
  tipo_codigo: string;
  ordem: number;
  texto: string;
  ativo: boolean;
  atualizado_em: string;
  atualizado_por: string | null;
}

export interface MetadadosTipoIa {
  tipo_codigo: string;
  origem: string;
  requer_revisao: boolean;
  informacoes_necessarias: string[];
  fundamentos: { referencia?: string; descricao?: string }[];
  gerado_em: string;
  gerado_por: string | null;
  aprovado_em: string | null;
  aprovado_por: string | null;
}

const JSON_HEADERS = { "Content-Type": "application/json" };
const rotaCriterios = (codigo: string) => `/api/tipos-caso/${encodeURIComponent(codigo)}/criterios`;

export async function listarCriterios(codigo: string): Promise<CriterioTipoCaso[]> {
  const r = await comoJson<{ criterios: CriterioTipoCaso[] }>(await buscar(rotaCriterios(codigo)));
  return r.criterios;
}

export async function criarCriterio(codigo: string, texto: string): Promise<CriterioTipoCaso> {
  return comoJson(
    await buscar(rotaCriterios(codigo), { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ texto }) }),
  );
}

export async function editarCriterio(
  codigo: string,
  id: string,
  dados: { texto?: string; ativo?: boolean },
): Promise<CriterioTipoCaso> {
  return comoJson(
    await buscar(`${rotaCriterios(codigo)}/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(dados),
    }),
  );
}

export async function removerCriterio(codigo: string, id: string): Promise<void> {
  await comoJson(await buscar(`${rotaCriterios(codigo)}/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export async function reordenarCriterios(codigo: string, ids: string[]): Promise<CriterioTipoCaso[]> {
  const r = await comoJson<{ criterios: CriterioTipoCaso[] }>(
    await buscar(`/api/tipos-caso/${encodeURIComponent(codigo)}/criterios-ordem`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ ids }),
    }),
  );
  return r.criterios;
}

export async function metadadosTiposIa(): Promise<Record<string, MetadadosTipoIa>> {
  const r = await comoJson<{ tipos: Record<string, MetadadosTipoIa> }>(await buscar("/api/tipos-caso-ia"));
  return r.tipos;
}

export async function aprovarTipoIa(codigo: string): Promise<MetadadosTipoIa> {
  return comoJson(await buscar(`/api/tipos-caso/${encodeURIComponent(codigo)}/aprovar`, { method: "POST" }));
}
