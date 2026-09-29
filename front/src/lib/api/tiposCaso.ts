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
