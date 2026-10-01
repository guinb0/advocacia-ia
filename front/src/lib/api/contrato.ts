/** Modelos de contrato e geração do contrato do caso. */

import type { DocumentoDoCliente } from "../types";
import { ApiError, buscar, comoJson, nomeDoAnexo, urlApi } from "./base";

export interface ModeloContrato {
  codigo: "contrato" | "procuracao" | "hipossuficiencia";
  rotulo: string;
  disponivel: boolean;
  origem: "banco" | "docs" | "nenhuma";
  arquivo: string;
  enviado_por?: string;
  atualizado_em?: string;
  tem_anterior?: boolean;
  anterior_arquivo?: string;
}

export interface ResultadoModeloContrato extends ModeloContrato {
  marcadores?: string[];
  sem_origem?: string[];
}

export async function listarModelosContrato(): Promise<ModeloContrato[]> {
  const resposta = await comoJson<{ modelos: ModeloContrato[] }>(await buscar("/api/modelos"));
  return resposta.modelos;
}

export async function enviarModeloContrato(codigo: ModeloContrato["codigo"], arquivo: File): Promise<ResultadoModeloContrato> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar(`/api/modelos/${encodeURIComponent(codigo)}`, { method: "POST", body: form }));
}

export async function restaurarModeloContratoAnterior(codigo: ModeloContrato["codigo"]): Promise<ModeloContrato> {
  return comoJson(await buscar(`/api/modelos/${encodeURIComponent(codigo)}/restaurar-anterior`, { method: "POST" }));
}

export function urlModeloContrato(codigo: ModeloContrato["codigo"]): string {
  return urlApi(`/api/modelos/${encodeURIComponent(codigo)}/arquivo`);
}

// ---------------------------------------------------------------- contrato

function cpfValido(cpf: string): boolean {
  const normalizado = cpf.normalize("NFKC");
  if (!/^[0-9.\-\s]+$/.test(normalizado)) return false;
  const digitos = normalizado.replace(/[^0-9]/g, "");
  if (digitos.length !== 11 || /^(\d)\1{10}$/.test(digitos)) return false;

  for (const posicao of [9, 10]) {
    let soma = 0;
    for (let indice = 0; indice < posicao; indice += 1) {
      soma += Number(digitos[indice]) * (posicao + 1 - indice);
    }
    let verificador = (soma * 10) % 11;
    if (verificador === 10) verificador = 0;
    if (verificador !== Number(digitos[posicao])) return false;
  }
  return true;
}

/** Antecipação visual da barreira definitiva que também existe no servidor. */
export function requisitosDoContrato(
  respostas: Record<string, string | string[]>,
): string[] {
  const nome = typeof respostas.nome === "string" ? respostas.nome.trim() : "";
  const cpf = typeof respostas.cpf === "string" ? respostas.cpf : "";
  const partesDoNome = nome.split(/\s+/);
  const particulas = new Set(["da", "das", "de", "do", "dos", "e"]);
  const partesSubstantivas = partesDoNome.filter(
    (parte) => !particulas.has(parte.toLocaleLowerCase("pt-BR").replace(/\.+$/, "")),
  );
  const nomeCompleto =
    partesSubstantivas.length >= 2 &&
    partesDoNome.every(
      (parte) => /\p{L}/u.test(parte) && /^[\p{L}.'’-]+$/u.test(parte),
    ) &&
    partesSubstantivas.every(
      (parte) => parte.replace(/[^\p{L}]/gu, "").length >= 2,
    );
  const requisitos: string[] = [];
  if (!nomeCompleto) requisitos.push("nome completo do cliente");
  if (!cpfValido(cpf)) requisitos.push("CPF válido");
  return requisitos;
}

export interface ContratoGerado {
  arquivo: Blob;
  nome: string;
  /** Campos do modelo que a entrevista não respondeu — saem entre colchetes. */
  faltando: string[];
}

/** Preenche o modelo oficial do escritório com as respostas da entrevista.
 *
 * Volta um .docx para conferir e assinar. As cláusulas vêm do arquivo em
 * `docs/`, palavra por palavra — nada aqui é redigido por modelo de linguagem. */
export async function gerarContrato(
  respostas: Record<string, string | string[]>,
  municipio = "",
  documento: DocumentoDoCliente = "contrato",
  formato: "docx" | "pdf" = "docx",
): Promise<ContratoGerado> {
  const r = await buscar("/api/contrato", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respostas, municipio, documento, formato }),
  });

  return interpretarContrato(r);
}

/** Os três documentos que o cliente assina, na ordem em que o escritório os
 *  junta. Os rótulos são os mesmos de `contrato.MODELOS`, no backend. */
export const DOCUMENTOS_DO_CLIENTE: { codigo: DocumentoDoCliente; rotulo: string }[] = [
  { codigo: "contrato", rotulo: "Contrato de honorários" },
  { codigo: "procuracao", rotulo: "Procuração" },
  { codigo: "hipossuficiencia", rotulo: "Declaração de hipossuficiência" },
];

/** Gera a partir dos fatos atuais do caso; nenhum dado pessoal vem do navegador. */
export async function gerarContratoDoCaso(casoId: string): Promise<ContratoGerado> {
  const r = await buscar(`/api/agente/casos/${encodeURIComponent(casoId)}/contrato`, {
    method: "POST",
  });
  return interpretarContrato(r);
}

async function interpretarContrato(r: Response): Promise<ContratoGerado> {
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }

  const faltando = (r.headers.get("X-Campos-Faltando") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  return { arquivo: await r.blob(), nome: nomeDoAnexo(r), faltando };
}
