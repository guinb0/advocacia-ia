/** Mensagens ao cliente: cobrança de documentos, portal, link de assinatura e avaliação. */

import type { CobrancaDocumentos } from "../types";
import { buscar, comoJson } from "./base";

export async function enviarAvaliacaoGoogle(
  telefone: string,
  forcar = false,
): Promise<{ enviado: boolean; ja_enviado?: boolean }> {
  return comoJson(await buscar("/api/whatsapp/avaliacao-google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telefone, forcar }),
  }));
}

export async function obterCobrancaDocumentos(casoId: string): Promise<CobrancaDocumentos> {
  return comoJson(await buscar(`/api/whatsapp/casos/${encodeURIComponent(casoId)}/cobranca-documentos`));
}

export async function salvarCobrancaDocumentos(
  casoId: string,
  config: Pick<
    CobrancaDocumentos,
    "ativa" | "telefone" | "intervalo_dias" | "intervalo_horas" | "max_envios_dia" | "incluir_opcionais"
  >,
): Promise<CobrancaDocumentos> {
  return comoJson(await buscar(`/api/whatsapp/casos/${encodeURIComponent(casoId)}/cobranca-documentos`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  }));
}

export async function enviarDocumentosWhatsApp(
  casoId: string,
  incluirOpcionais = false,
): Promise<{ enviado: boolean; portal_criado: boolean }> {
  return comoJson(await buscar(
    `/api/whatsapp/casos/${encodeURIComponent(casoId)}/enviar-documentos`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ incluir_opcionais: incluirOpcionais }),
    },
  ));
}

export async function dispararTesteCobrancaDocumentos(
  casoId: string,
  config?: Pick<
    CobrancaDocumentos,
    "ativa" | "telefone" | "intervalo_dias" | "intervalo_horas" | "max_envios_dia" | "incluir_opcionais"
  >,
): Promise<{ enviado: boolean; teste_temporario: boolean; ultimo_erro?: string }> {
  return comoJson(await buscar(
    `/api/whatsapp/casos/${encodeURIComponent(casoId)}/cobranca-documentos/teste-disparo`,
    {
      method: "POST",
      headers: config ? { "Content-Type": "application/json" } : undefined,
      body: config ? JSON.stringify(config) : undefined,
    },
  ));
}

export async function enviarPortalWhatsApp(
  casoId: string,
  senha: string,
  telefone: string,
): Promise<{ enviado: boolean }> {
  return comoJson(await buscar(`/api/whatsapp/casos/${encodeURIComponent(casoId)}/enviar-portal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha, telefone }),
  }));
}

/** O link de assinatura de UM documento para UM signatário, pelo WhatsApp.
 *
 * Manda identificadores, nunca a URL nem o telefone: o servidor busca os dois no
 * registro do documento. Ver o cabeçalho de `app/whatsapp.py`. */
export async function enviarLinkAssinatura(
  assinaturaId: string,
  signatarioToken: string,
): Promise<{ enviado: boolean }> {
  return comoJson(await buscar("/api/whatsapp/link-assinatura", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assinatura_id: assinaturaId, signatario_token: signatarioToken }),
  }));
}
