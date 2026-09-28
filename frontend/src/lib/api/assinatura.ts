/** Assinatura eletrônica: provedores, envio e acompanhamento. */

import type {
  Assinatura,
  AssinaturaConsultada,
  AssinaturaCriada,
  ConfigAssinatura,
  ProvedorAssinatura,
  StatusProvedorAssinatura,
} from "../types";
import { ApiError, buscar, comoJson, nomeDoAnexo } from "./base";

// --------------------------------------------- assinatura eletrônica do contrato

/** Se o envio para assinatura está ligado — sem a chave no `.env` ele não existe. */
export async function configAssinatura(): Promise<ConfigAssinatura> {
  return comoJson<ConfigAssinatura>(await buscar("/api/assinatura/config"));
}

/** Status de cada provedor (ZapSign, Clicksign, Autentique) — nunca o token. */
export async function listarProvedoresAssinatura(): Promise<StatusProvedorAssinatura[]> {
  const dados = await comoJson<{ provedores: StatusProvedorAssinatura[] }>(
    await buscar("/api/assinatura/provedores"),
  );
  return dados.provedores;
}

/** Cifra e salva o token do escritório para Clicksign/Autentique. Não testa
 *  sozinho — o botão "Testar conexão" (`testarProvedorAssinatura`) faz isso. */
export async function salvarTokenProvedorAssinatura(
  provedor: "clicksign" | "autentique",
  token: string,
): Promise<void> {
  await comoJson(
    await buscar(`/api/assinatura/provedores/${provedor}/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  );
}

/** Bate na API do provedor com o token salvo. Lança se a conexão falhar — a
 *  mensagem de erro já vem pronta para a tela. */
export async function testarProvedorAssinatura(
  provedor: "clicksign" | "autentique",
): Promise<{ ok: boolean; mensagem: string }> {
  return comoJson(await buscar(`/api/assinatura/provedores/${provedor}/testar`, { method: "POST" }));
}

/** Torna o provedor escolhido o caminho de envio. Exige teste aprovado antes
 *  (Clicksign/Autentique) — a ZapSign pode voltar a ser ativada a qualquer hora. */
export async function ativarProvedorAssinatura(
  provedor: ProvedorAssinatura,
): Promise<{ ok: boolean; provedor_ativo: ProvedorAssinatura }> {
  return comoJson(
    await buscar("/api/assinatura/provedores/ativar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provedor }),
    }),
  );
}

/** Envia um documento à assinatura pelo SITE do ZapSign (plano sem API), via
 *  navegador, e — havendo telefone e link — manda o link pela Evolution. */
export async function enviarAssinaturaPeloSite(dados: {
  arquivo: File;
  clienteNome: string;
  clienteEmail: string;
  clienteWhatsapp?: string;
}): Promise<{ ok: boolean; link: string; whatsapp_enviado: boolean }> {
  const form = new FormData();
  form.append("arquivo", dados.arquivo);
  form.append("cliente_nome", dados.clienteNome);
  form.append("cliente_email", dados.clienteEmail);
  form.append("cliente_whatsapp", dados.clienteWhatsapp ?? "");
  return comoJson(await buscar("/api/assinatura/navegador", { method: "POST", body: form }));
}

/** Gera os TRÊS documentos e os manda assinar de uma vez pela conta ZapSign
 *  (site), num login só. Cada um volta com o seu link; havendo telefone, cada
 *  link vai pelo WhatsApp. Demora o tempo da automação (~1 min por documento). */
export async function enviarTodosParaAssinaturaSite(dados: {
  respostas: Record<string, string | string[]>;
  municipio?: string;
  clienteWhatsapp?: string;
}): Promise<{ ok: boolean; documentos: { rotulo: string; link: string }[]; whatsapp_enviado: boolean }> {
  return comoJson(await buscar("/api/assinatura/navegador/todos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      respostas: dados.respostas,
      municipio: dados.municipio ?? "",
      cliente_whatsapp: dados.clienteWhatsapp ?? "",
    }),
  }));
}

/** Gera um documento no servidor e o manda assinar pela conta ZapSign (site),
 *  num clique — sem baixar o PDF e reanexar. O convite sai por e-mail e, havendo
 *  telefone, o link também vai pelo WhatsApp. Demora o tempo da automação. */
export async function enviarDocumentoParaAssinaturaSite(dados: {
  respostas: Record<string, string | string[]>;
  documento: string;
  municipio?: string;
  clienteWhatsapp?: string;
}): Promise<{ ok: boolean; link: string; whatsapp_enviado: boolean }> {
  return comoJson(await buscar("/api/assinatura/navegador/documento", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      respostas: dados.respostas,
      municipio: dados.municipio ?? "",
      documento: dados.documento,
      cliente_whatsapp: dados.clienteWhatsapp ?? "",
    }),
  }));
}

/** (Re)envia ao cliente, pelo WhatsApp, o link de assinatura já criado no ZapSign.
 *  Serve quando o convite caiu no spam ou o telefone não estava à mão na criação. */
export async function reenviarLinkAssinaturaSite(
  telefone: string,
  link: string,
): Promise<{ enviado: boolean }> {
  return comoJson(await buscar("/api/assinatura/navegador/whatsapp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telefone, link }),
  }));
}

/** Gera o contrato e o manda assinar. O .docx é o mesmo de `gerarContrato`. */
export async function enviarParaAssinatura(
  respostas: Record<string, string | string[]>,
  signatarios: { nome: string; email?: string; telefone?: string; papel?: string }[] = [],
  municipio = "",
  casoId?: string,
): Promise<AssinaturaCriada> {
  return comoJson<AssinaturaCriada>(
    await buscar("/api/contrato/assinatura", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        respostas,
        municipio,
        signatarios,
        caso_id: casoId ?? null,
      }),
    }),
  );
}

/** Os contratos já mandados assinar, com o último estado conhecido. */
export async function listarAssinaturas(filtro: {
  casoId?: string;
  cliente?: string;
  cpf?: string;
} = {}): Promise<Assinatura[]> {
  const query = new URLSearchParams();
  if (filtro.casoId) query.set("caso_id", filtro.casoId);
  if (filtro.cliente) query.set("cliente", filtro.cliente);
  if (filtro.cpf) query.set("cpf", filtro.cpf);
  const sufixo = query.size > 0 ? `?${query}` : "";
  const dados = await comoJson<{ assinaturas: Assinatura[] }>(
    await buscar(`/api/assinaturas${sufixo}`),
  );
  return dados.assinaturas;
}

/** Quem já assinou e quem falta, consultado na ZapSign agora. */
export async function obterAssinatura(id: string): Promise<AssinaturaConsultada> {
  return comoJson<AssinaturaConsultada>(await buscar(`/api/assinaturas/${id}`));
}

export async function vincularAssinaturaAoCaso(id: string, casoId: string): Promise<void> {
  const form = new FormData();
  form.append("caso_id", casoId);
  await comoJson(await buscar(`/api/assinaturas/${id}/caso`, { method: "POST", body: form }));
}

/** Tira o contrato da lista local. Na ZapSign ele continua, com a auditoria. */
export async function excluirAssinatura(id: string): Promise<void> {
  await comoJson(await buscar(`/api/assinaturas/${id}`, { method: "DELETE" }));
}

/** O PDF assinado, com a trilha de auditoria. Vem pelo backend, que o guarda. */
export async function baixarContratoAssinado(
  id: string,
): Promise<{ arquivo: Blob; nome: string }> {
  const r = await buscar(`/api/assinaturas/${id}/arquivo`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return { arquivo: await r.blob(), nome: nomeDoAnexo(r, "contrato-assinado.pdf") };
}
