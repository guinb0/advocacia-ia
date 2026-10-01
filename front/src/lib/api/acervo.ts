/** Arquivo de precedentes (acervo). */

import { buscar, comoJson } from "./base";

// ------------------------------------------------- acervo de precedentes

export interface ContagemAcervo { nome: string; trechos: number; documentos: number }

export interface PanoramaAcervo {
  fontes: number; trechos: number; vetorizados: number; sem_vetor: number;
  periodo: { de: string | null; ate: string | null };
  por_tipo_de_fonte: { nome: string; documentos: number }[];
  por_origem: ContagemAcervo[];
  por_tribunal: ContagemAcervo[];
  por_resultado: ContagemAcervo[];
  por_tipo_documento: ContagemAcervo[];
  por_classe: ContagemAcervo[];
}

export interface DocumentoAcervo {
  id: string; tipo: string; titulo: string; identificador: string | null;
  url: string | null; publicado_em: string | null; trechos: number;
  tribunal: string | null; resultado: string | null; origem: string | null;
  processo: string | null;
}

export interface DocumentoDetalhe {
  fonte: { id: string; tipo: string; titulo: string; identificador: string | null; url: string | null; publicado_em: string | null };
  trechos: { ordem: number; texto: string; caracteres: number; vetorizado: boolean; metadados: unknown }[];
  total_trechos: number;
}

export async function panoramaAcervo(): Promise<PanoramaAcervo> {
  return comoJson(await buscar("/api/dados"));
}

export async function listarDocumentosAcervo(f: {
  origem?: string; tribunal?: string; busca?: string;
}): Promise<{ itens: DocumentoAcervo[]; total: number }> {
  const p = new URLSearchParams();
  if (f.origem) p.set("origem", f.origem);
  if (f.tribunal) p.set("tribunal", f.tribunal);
  if (f.busca) p.set("busca", f.busca);
  return comoJson(await buscar(`/api/dados/documentos?${p.toString()}`));
}

export async function obterDocumentoAcervo(id: string): Promise<DocumentoDetalhe> {
  return comoJson(await buscar(`/api/dados/documentos/${encodeURIComponent(id)}`));
}

export interface PrazosAcervo {
  processos: number;
  segunda_instancia: number;
  percentual_recurso: number;
  duracao: { processos_medidos: number; mediana_dias: number | null; p90_dias: number | null };
  aviso: string;
}

export async function prazosAcervo(): Promise<PrazosAcervo> {
  return comoJson(await buscar("/api/dados/prazos"));
}
