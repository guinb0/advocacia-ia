"use client";

import { ApiError, urlApi } from "./api";

/* Cliente HTTP do portal. Separado de `api.ts` de propósito: aquele manda o
 * cookie de sessão do escritório, e o cliente final não tem conta nenhuma —
 * quem autentica aqui é a sessão obtida com a senha do caso. Misturar os dois
 * arrastaria a sessão do advogado para uma tela pública. */

export interface ItemPortal {
  codigo: string;
  nome: string;
  observacao: string;
  obrigatorio: boolean;
  status: "pendente" | "processando" | "conferir" | "entregue";
  enviados: number;
  /** Só vem preenchido quando o item precisa ser reenviado. */
  motivo: string;
}

export interface SituacaoPortal {
  cliente: string;
  categoria: string;
  itens: ItemPortal[];
  /** Arquivos recebidos que ainda estão sendo identificados. */
  em_analise: number;
  /** Subconjunto ainda na fila/OCR; usado para encerrar o polling. */
  processando: number;
  progresso: {
    obrigatorios_total: number;
    obrigatorios_entregues: number;
    percentual: number;
    pronto: boolean;
  };
}

export interface RespostaLotePortal {
  lote_id: string;
  recebidos: Array<{ arquivo: string; entrega_id: string }>;
  recusados: Array<{ arquivo: string; motivo: string }>;
  processando: boolean;
  situacao: SituacaoPortal;
}

export interface Sessao {
  sessao: string;
  expira_em: number;
  duracao_s: number;
  cliente: string;
}

async function comoJson<T>(r: Response): Promise<T> {
  const corpo = await r.json().catch(() => null);
  if (!r.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`;
    throw new ApiError(detalhe);
  }
  return corpo as T;
}

export async function entrar(token: string, senha: string): Promise<Sessao> {
  const form = new FormData();
  form.append("senha", senha);
  return comoJson<Sessao>(
    await fetch(urlApi(`/api/portal/${token}/entrar`), { method: "POST", body: form }),
  );
}

export async function situacao(token: string, sessao: string): Promise<SituacaoPortal> {
  return comoJson<SituacaoPortal>(
    await fetch(urlApi(`/api/portal/${token}/situacao`), {
      headers: { Authorization: `Bearer ${sessao}` },
    }),
  );
}

export async function enviarDocumento(
  token: string,
  sessao: string,
  item: string,
  arquivo: File,
): Promise<SituacaoPortal> {
  const form = new FormData();
  form.append("item", item);
  form.append("arquivo", arquivo);
  return comoJson<SituacaoPortal>(
    await fetch(urlApi(`/api/portal/${token}/documentos`), {
      method: "POST",
      body: form,
      headers: { Authorization: `Bearer ${sessao}` },
    }),
  );
}

export async function enviarDocumentosEmLote(
  token: string,
  sessao: string,
  arquivos: File[],
): Promise<RespostaLotePortal> {
  const form = new FormData();
  arquivos.forEach((arquivo) => form.append("arquivos", arquivo));
  return comoJson<RespostaLotePortal>(
    await fetch(urlApi(`/api/portal/${token}/documentos/lote`), {
      method: "POST",
      body: form,
      headers: { Authorization: `Bearer ${sessao}` },
    }),
  );
}

/* A sessão fica em sessionStorage, não em localStorage: morre ao fechar a aba.
 * O cliente costuma abrir esse link no celular, às vezes emprestado — deixar a
 * sessão gravada no aparelho depois que ele fecha seria expor os documentos. */
const CHAVE = "acervo-portal-sessao";

export function guardarSessao(token: string, sessao: string, expiraEm: number): void {
  sessionStorage.setItem(CHAVE, JSON.stringify({ token, sessao, expiraEm }));
}

export function recuperarSessao(token: string): string | null {
  try {
    const bruto = sessionStorage.getItem(CHAVE);
    if (!bruto) return null;
    const dados = JSON.parse(bruto) as { token: string; sessao: string; expiraEm: number };
    if (dados.token !== token || dados.expiraEm * 1000 < Date.now()) return null;
    return dados.sessao;
  } catch {
    return null;
  }
}

export function esquecerSessao(): void {
  sessionStorage.removeItem(CHAVE);
}
