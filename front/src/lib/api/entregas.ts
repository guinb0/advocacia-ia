/** Documentos e entregas do caso: envio, reclassificação, downloads e releitura. */

import type {
  Entrega,
  EntregaDetalhe,
  EventoHistorico,
  OpcoesReclassificacao,
  RespostaEnvio,
} from "../types";
import { ApiError, buscar, comoJson, nomeDoAnexo, urlApi } from "./base";

// --------------------------------------------------------------- entregas

export async function enviarDocumento(
  casoId: string,
  itemCodigo: string,
  arquivo: File,
  idioma = "pt",
  usarParaRgECpf = false,
  /** Envia mesmo sendo idêntico a outro arquivo do caso (a confirmação fica no histórico). */
  confirmarDuplicidade = false,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("item", itemCodigo);
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("usar_para_rg_e_cpf", String(usarParaRgECpf));
  form.append("confirmar_duplicidade", String(confirmarDuplicidade));
  return comoJson<RespostaEnvio>(
    await buscar(`/api/casos/${casoId}/documentos`, { method: "POST", body: form }),
  );
}

export interface RespostaLote {
  lote_id: string;
  recebidos: Array<{ arquivo: string; entrega_id: string }>;
  recusados: Array<{ arquivo: string; motivo: string }>;
  processando: boolean;
}

/** Envia vários arquivos sem atribuir item: cada leitura encontra seu destino. */
export async function enviarDocumentosEmLote(
  casoId: string,
  arquivos: File[],
  idioma = "pt",
): Promise<RespostaLote> {
  const form = new FormData();
  arquivos.forEach((arquivo) => form.append("arquivos", arquivo));
  form.append("idioma", idioma);
  return comoJson<RespostaLote>(
    await buscar(`/api/casos/${casoId}/documentos/lote`, { method: "POST", body: form }),
  );
}

/** Palavra final do escritório sobre o item e o tipo de um documento já lido.
 *
 * Com suspeita de duplicidade o servidor devolve 409 sem gravar — ver
 * `duplicidadesDoErro` — e só `confirmarDuplicidade` conclui. */
export async function reatribuirEntrega(
  entregaId: string,
  itens: string[],
  opcoes: OpcoesReclassificacao = {},
): Promise<Entrega> {
  return comoJson<Entrega>(
    await buscar(`/api/entregas/${entregaId}/itens`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        itens,
        tipo: opcoes.tipo || null,
        confirmar_duplicidade: opcoes.confirmarDuplicidade ?? false,
        motivo: opcoes.motivo ?? "",
      }),
    }),
  );
}

/** Reclassificações, devoluções à triagem, repetidos aceitos e remoção do documento. */
export async function historicoEntrega(entregaId: string): Promise<EventoHistorico[]> {
  const r = await comoJson<{ eventos: EventoHistorico[] }>(
    await buscar(`/api/entregas/${entregaId}/historico`),
  );
  return r.eventos;
}

export async function vincularIdentidadeUnificada(
  casoId: string,
  entregaId: string,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("entrega_id", entregaId);
  return comoJson<RespostaEnvio>(
    await buscar(`/api/casos/${casoId}/identidade-unificada`, {
      method: "POST",
      body: form,
    }),
  );
}

export async function excluirEntrega(entregaId: string): Promise<void> {
  await comoJson(await buscar(`/api/entregas/${entregaId}`, { method: "DELETE" }));
}

/** Reenfileira a leitura de uma entrega com "Falha na leitura", sem reenviar o arquivo. */
export async function tentarNovamenteEntrega(entregaId: string): Promise<void> {
  await comoJson(
    await buscar(`/api/entregas/${entregaId}/tentar-novamente`, { method: "POST" }),
  );
}

export interface ResultadoTentarNovamenteCaso {
  reenfileiradas: number;
  falharam: { entrega_id: string; arquivo: string; motivo: string }[];
}

/** Reenfileira TODO documento com "Falha na leitura" do caso, de uma vez. */
export async function tentarNovamenteCaso(casoId: string): Promise<ResultadoTentarNovamenteCaso> {
  return comoJson<ResultadoTentarNovamenteCaso>(
    await buscar(`/api/casos/${casoId}/tentar-novamente`, { method: "POST" }),
  );
}

/** A entrega com a extração completa — os campos que o visor mostra. */
export async function obterEntrega(entregaId: string): Promise<EntregaDetalhe> {
  return comoJson<EntregaDetalhe>(await buscar(`/api/entregas/${entregaId}`));
}

export interface PacoteDocumentos {
  arquivo: Blob;
  nome: string;
  /** Quantos documentos entraram no pacote. */
  arquivos: number;
  /** Quantos constavam no caso mas não estavam mais no disco. */
  faltando: number;
}

/** Tudo que o cliente enviou, num ZIP só, na ordem do checklist.
 *
 * Vai por `fetch` e não por `<a href download>` porque o link cru não manda o
 * Bearer — desceria um 401 salvo em disco com nome de .zip, e o atendente só
 * descobriria ao tentar abrir. Mesmo motivo de `baixarArquivoEntrega`. */
export async function baixarDocumentosDoCaso(casoId: string): Promise<PacoteDocumentos> {
  const r = await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos.zip`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return {
    arquivo: await r.blob(),
    nome: nomeDoAnexo(r, "documentos.zip"),
    arquivos: Number(r.headers.get("X-Arquivos") ?? 0),
    faltando: Number(r.headers.get("X-Faltando") ?? 0),
  };
}

/** ZIP só com as entregas marcadas DENTRO de uma classificação (um item do
 * checklist). É a versão seletiva de `baixarDocumentosDoCaso`: o atendente
 * escolheu a classificação, marcou alguns arquivos dela e leva só esses.
 *
 * O servidor recusa o pedido inteiro se algum id não for daquela classificação
 * — a mensagem de erro já vem pronta em `detail`. */
export async function baixarSelecaoDeDocumentos(
  casoId: string,
  classificacao: string,
  entregas: string[],
): Promise<PacoteDocumentos> {
  const r = await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos.zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ classificacao, entregas }),
  });
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return {
    arquivo: await r.blob(),
    nome: nomeDoAnexo(r, "documentos.zip"),
    arquivos: Number(r.headers.get("X-Arquivos") ?? 0),
    faltando: Number(r.headers.get("X-Faltando") ?? 0),
  };
}

export interface PacotePdfCombinado extends PacoteDocumentos {
  /** Páginas do PDF final — PDF original preserva as próprias; imagem vira 1. */
  paginas: number;
}

/** Os mesmos documentos marcados, mas combinados num PDF só em vez de um ZIP.
 *
 * Irmã de `baixarSelecaoDeDocumentos`: mesma seleção, mesmas guardas. O
 * servidor recusa (415) se algum arquivo não for PDF nem imagem, ou se a soma
 * de páginas passar do teto — nesses casos o ZIP continua sendo a opção. */
export async function baixarSelecaoEmPdf(
  casoId: string,
  classificacao: string,
  entregas: string[],
): Promise<PacotePdfCombinado> {
  const r = await buscar(`/api/casos/${encodeURIComponent(casoId)}/documentos.pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ classificacao, entregas }),
  });
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return {
    arquivo: await r.blob(),
    nome: nomeDoAnexo(r, "documentos.pdf"),
    arquivos: Number(r.headers.get("X-Arquivos") ?? 0),
    paginas: Number(r.headers.get("X-Paginas") ?? 0),
    faltando: Number(r.headers.get("X-Faltando") ?? 0),
  };
}

/** URL absoluta do arquivo. Serve para abrir em nova aba quando não há
 * autenticação; com token ligado use `baixarArquivoEntrega`, porque `<img>` e
 * `<iframe>` não enviam o header Authorization e levariam 401. */
export function urlArquivoEntrega(entregaId: string, download = false): string {
  return urlApi(`/api/entregas/${entregaId}/arquivo${download ? "?download=1" : ""}`);
}

/** Busca o arquivo COM o Bearer e devolve o blob — a origem do object URL que
 * a pré-visualização usa em `src`. */
export async function baixarArquivoEntrega(entregaId: string): Promise<Blob> {
  const r = await buscar(`/api/entregas/${entregaId}/arquivo`);
  if (!r.ok) throw new ApiError(r.status === 401 ? "Sessão expirada." : `Erro ${r.status}`);
  return r.blob();
}

export async function baixarArquivoEntregaPdf(
  entregaId: string,
): Promise<{ arquivo: Blob; nome: string }> {
  const r = await buscar(`/api/entregas/${encodeURIComponent(entregaId)}/arquivo.pdf`);
  if (!r.ok) {
    const corpo = await r.json().catch(() => null);
    throw new ApiError(
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${r.status}`,
    );
  }
  return { arquivo: await r.blob(), nome: nomeDoAnexo(r, "documento.pdf") };
}
