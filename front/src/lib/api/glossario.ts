/** Glossário de tipos de documento. */

import type { EventoHistorico, ImpactoTipoDocumento, TipoDocumentoGlossario } from "../types";
import { buscar, comoJson } from "./base";

// -------------------------------------------------- glossário de documentos
// Consultar é livre para a equipe; criar e editar pedem o módulo
// `glossario_documentos` (ver `app/tipos_documento.py`).

export async function listarTiposDocumento(
  incluirInativos = false,
): Promise<TipoDocumentoGlossario[]> {
  const r = await comoJson<{ tipos: TipoDocumentoGlossario[] }>(
    await buscar(`/api/tipos-documento?incluir_inativos=${incluirInativos}`),
  );
  return r.tipos;
}

export async function criarTipoDocumento(dados: {
  nome: string;
  /** Vazio = gerado a partir do nome. */
  codigo?: string;
  descricao: string;
  sinonimos: string[];
  /** Categorias (tipos de caso) em cujo checklist o tipo passa a ser pedido. */
  categorias: string[];
}): Promise<TipoDocumentoGlossario> {
  return comoJson(
    await buscar("/api/tipos-documento", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

export async function editarTipoDocumento(
  codigo: string,
  dados: {
    nome: string;
    descricao: string;
    sinonimos: string[];
    ativo: boolean;
    /** A versão lida ao abrir o formulário; outra no servidor = 409. */
    versao: number;
    motivo?: string;
    /** Ausente mantém os tipos de caso marcados; vazio desmarca todos. */
    categorias?: string[];
  },
): Promise<TipoDocumentoGlossario> {
  return comoJson(
    await buscar(`/api/tipos-documento/${encodeURIComponent(codigo)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}

export async function impactoTipoDocumento(codigo: string): Promise<ImpactoTipoDocumento> {
  return comoJson(
    await buscar(`/api/tipos-documento/${encodeURIComponent(codigo)}/impacto`),
  );
}

export async function historicoTipoDocumento(codigo: string): Promise<EventoHistorico[]> {
  const r = await comoJson<{ eventos: EventoHistorico[] }>(
    await buscar(`/api/tipos-documento/${encodeURIComponent(codigo)}/historico`),
  );
  return r.eventos;
}
