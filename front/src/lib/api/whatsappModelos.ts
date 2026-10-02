/** Modelos de mensagem do WhatsApp e histórico de envios. */

import { buscar, comoJson } from "./base";

export interface ModeloWhatsapp {
  codigo: string;
  nome: string;
  descricao: string | null;
  texto: string;
  ativo: boolean;
  versao: number;
  atualizado_em?: string | null;
  atualizado_por?: string | null;
  padrao: string | null;
  personalizado: boolean;
}

export interface EnvioWhatsapp {
  chave: string;
  tipo: string;
  caso_id: string | null;
  atendimento_id: string | null;
  destino: string;
  status: string;
  status_entrega: string | null;
  tentativas: number;
  ultimo_erro: string | null;
  texto_resumo: string | null;
  enviado_em: string | null;
  entregue_em: string | null;
  lido_em: string | null;
  criado_em: string;
  atualizado_em: string;
}

const JSON_CT = { "Content-Type": "application/json" };

export async function listarModelosWhatsapp(): Promise<{ modelos: ModeloWhatsapp[]; variaveis: string[] }> {
  return comoJson(await buscar("/api/whatsapp/modelos"));
}

export async function salvarModeloWhatsapp(
  codigo: string,
  dados: { texto: string; ativo: boolean; versao: number },
): Promise<ModeloWhatsapp> {
  return comoJson(
    await buscar(`/api/whatsapp/modelos/${encodeURIComponent(codigo)}`, {
      method: "PUT",
      headers: JSON_CT,
      body: JSON.stringify(dados),
    }),
  );
}

export async function restaurarModeloWhatsapp(codigo: string): Promise<ModeloWhatsapp> {
  return comoJson(await buscar(`/api/whatsapp/modelos/${encodeURIComponent(codigo)}/restaurar`, { method: "POST" }));
}

export async function previaModeloWhatsapp(codigo: string, texto?: string): Promise<string> {
  const r = await comoJson<{ texto: string }>(
    await buscar(`/api/whatsapp/modelos/${encodeURIComponent(codigo)}/previa`, {
      method: "POST",
      headers: JSON_CT,
      body: JSON.stringify({ texto: texto ?? null }),
    }),
  );
  return r.texto;
}

export async function historicoWhatsapp(filtro: { dias?: number; tipo?: string } = {}): Promise<EnvioWhatsapp[]> {
  const q = new URLSearchParams();
  if (filtro.dias) q.set("dias", String(filtro.dias));
  if (filtro.tipo) q.set("tipo", filtro.tipo);
  const r = await comoJson<{ envios: EnvioWhatsapp[] }>(
    await buscar(`/api/whatsapp/historico${q.toString() ? `?${q}` : ""}`),
  );
  return r.envios;
}
