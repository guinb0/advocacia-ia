/** Integrações do escritório: WhatsApp, Google Drive e Tactiq. */

import { buscar, comoJson } from "./base";

export interface StatusWhatsapp {
  configurado: boolean;
  conectado: boolean;
  /** "open" (conectado), "connecting", "close" (caído), "indisponivel"… */
  estado: string;
  instancia?: string;
  /** Número pareado, formatado (+55 (DD) 9XXXX-XXXX), quando conectado. */
  numero?: string;
  /** Nome do perfil do WhatsApp conectado, quando a Evolution o expõe. */
  perfil?: string;
  erro?: string;
  /** Identifica a versão do diagnóstico e denuncia backend antigo no deploy. */
  diagnostico?: string;
}

/** Se o WhatsApp do escritório (Evolution) está conectado — para o painel. */
export async function statusWhatsapp(): Promise<StatusWhatsapp> {
  return comoJson(await buscar("/api/whatsapp/status"));
}

/** Pede um QR novo para religar a instância caída ou trocar de número. */
export async function conectarWhatsapp(): Promise<{ qrcode: string; codigo: string; instancia: string }> {
  return comoJson(await buscar("/api/whatsapp/conectar", { method: "POST" }));
}

/** Desliga o número do WhatsApp (logout) — depois é só escanear outro QR. */
export async function desconectarWhatsapp(): Promise<{ desconectado: boolean; instancia: string }> {
  return comoJson(await buscar("/api/whatsapp/desconectar", { method: "POST" }));
}

export interface StatusDrive {
  configurado: boolean;
  credenciais_do_ambiente: boolean;
  conectado: boolean;
  conta: string;
  pasta_url: string;
  redirect_uri: string;
  origem: string;
  client_id: string;
}

export async function testarDrive(): Promise<{ ok: boolean; mensagem: string }> {
  return comoJson(await buscar("/api/drive/testar", { method: "POST" }));
}

export async function statusDrive(): Promise<StatusDrive> {
  return comoJson(await buscar("/api/drive/status"));
}

export async function salvarCredenciaisDrive(clientId: string, clientSecret: string): Promise<StatusDrive> {
  return comoJson(await buscar("/api/drive/credenciais", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  }));
}

export async function urlConectarDrive(): Promise<{ url: string }> {
  return comoJson(await buscar("/api/drive/conectar"));
}

export async function desconectarDrive(): Promise<StatusDrive> {
  return comoJson(await buscar("/api/drive/desconectar", { method: "POST" }));
}

export async function enviarGravacaoDrive(arquivo: Blob, nome: string): Promise<{ id: string; link: string }> {
  const form = new FormData();
  form.append("arquivo", arquivo, nome);
  form.append("nome", nome);
  return comoJson(await buscar("/api/drive/gravacoes", { method: "POST", body: form }));
}

export interface StatusTactiq { conectado: boolean; conectado_em: string; servidor: string; disponivel?: boolean; motivo?: string }

export async function statusTactiq(verificar = false): Promise<StatusTactiq> {
  return comoJson<StatusTactiq>(await buscar(`/api/tactiq/status${verificar ? "?verificar=true" : ""}`));
}

export async function conectarTactiq(): Promise<{ url: string }> {
  return comoJson<{ url: string }>(await buscar("/api/tactiq/conectar", { method: "POST" }));
}

export interface ReuniaoTactiq { id: string; titulo: string; data: string }

export async function listarReunioesTactiq(): Promise<ReuniaoTactiq[]> {
  const dados = await comoJson<{ reunioes: ReuniaoTactiq[] }>(await buscar("/api/tactiq/reunioes"));
  return dados.reunioes;
}

export async function obterTranscricaoTactiq(reuniaoId: string): Promise<{ id: string; titulo: string; texto: string }> {
  return comoJson(await buscar(`/api/tactiq/reunioes/${encodeURIComponent(reuniaoId)}/transcricao`));
}
