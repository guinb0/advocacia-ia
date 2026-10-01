/** Roteiros de entrevista e checklist do roteiro. */

import type { RoteiroCompleto, RoteiroImportado, RoteiroResumo } from "../types";
import { ApiError, buscar, comoJson } from "./base";

// ------------------------------------------------------ roteiro de entrevista

const TTL_ROTEIROS_MS = 30_000;

const TTL_CATALOGO_ROTEIROS_MS = 5 * 60_000;

const roteirosCompletos = new Map<string, { ate: number; valor: Promise<RoteiroCompleto> }>();

let catalogoRoteiros: { ate: number; valor: Promise<RoteiroResumo[]> } | null = null;

let ultimoCatalogoRoteiros: RoteiroResumo[] | null = null;

let ultimoAvisoCatalogoRoteiros = "";

function invalidarCacheRoteiros(codigo?: string): void {
  catalogoRoteiros = null;
  ultimoCatalogoRoteiros = null;
  ultimoAvisoCatalogoRoteiros = "";
  if (codigo) roteirosCompletos.delete(codigo);
  else roteirosCompletos.clear();
}

export async function obterRoteiro(codigo: string): Promise<RoteiroCompleto> {
  const agora = Date.now();
  const existente = roteirosCompletos.get(codigo);
  if (existente && existente.ate > agora) return existente.valor;
  const valor = buscar(`/api/roteiros/${codigo}`).then((resposta) =>
    comoJson<RoteiroCompleto>(resposta),
  );
  roteirosCompletos.set(codigo, { ate: agora + TTL_ROTEIROS_MS, valor });
  valor.catch(() => roteirosCompletos.delete(codigo));
  return valor;
}

export async function listarRoteiros(): Promise<RoteiroResumo[]> {
  const agora = Date.now();
  if (catalogoRoteiros && catalogoRoteiros.ate > agora) return catalogoRoteiros.valor;
  const valor = buscar("/api/roteiros")
    .then((resposta) => comoJson<{ roteiros: RoteiroResumo[]; aviso_catalogo?: string }>(resposta))
    .then((dados) => {
      ultimoCatalogoRoteiros = dados.roteiros;
      ultimoAvisoCatalogoRoteiros = dados.aviso_catalogo ?? "";
      return dados.roteiros;
    });
  catalogoRoteiros = { ate: agora + TTL_CATALOGO_ROTEIROS_MS, valor };
  valor.catch(() => {
    if (catalogoRoteiros?.valor === valor) catalogoRoteiros = null;
  });
  return valor;
}

/** Permite abrir o seletor instantaneamente enquanto uma atualização acontece. */
export function catalogoRoteirosEmCache(): RoteiroResumo[] | null {
  return ultimoCatalogoRoteiros;
}

export function avisoCatalogoRoteirosEmCache(): string {
  return ultimoAvisoCatalogoRoteiros;
}

export interface PaginaRoteiros {
  roteiros: RoteiroResumo[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
  importados: number;
  originais: number;
}

export async function listarRoteirosPaginado(
  pagina: number,
  tamanho: number,
): Promise<PaginaRoteiros> {
  const paginaSolicitada = Number.isFinite(pagina) ? Math.max(1, Math.floor(pagina)) : 1;
  const tamanhoSolicitado = Number.isFinite(tamanho) ? Math.max(1, Math.floor(tamanho)) : 10;
  const dados = await comoJson<Partial<PaginaRoteiros> & { roteiros?: RoteiroResumo[] }>(
    await buscar(`/api/roteiros?pagina=${paginaSolicitada}&tamanho=${tamanhoSolicitado}`),
  );
  const numeroSeguro = (valor: unknown, fallback: number) =>
    typeof valor === "number" && Number.isFinite(valor) ? valor : fallback;
  const roteiros = dados.roteiros ?? [];
  const total = Math.max(0, numeroSeguro(dados.total, roteiros.length));
  const paginaAtual = Math.max(1, numeroSeguro(dados.pagina, paginaSolicitada));
  const tamanhoAtual = Math.max(1, numeroSeguro(dados.tamanho, tamanhoSolicitado));
  const paginas = Math.max(
    1,
    numeroSeguro(dados.paginas, Math.max(1, Math.ceil(total / tamanhoAtual))),
  );
  const importados = Math.min(
    total,
    Math.max(
      0,
      numeroSeguro(dados.importados, roteiros.filter((roteiro) => roteiro.importado).length),
    ),
  );
  return {
    roteiros,
    total,
    pagina: paginaAtual,
    tamanho: tamanhoAtual,
    paginas,
    importados,
    originais: Math.max(0, numeroSeguro(dados.originais, total - importados)),
  };
}

/** Lê o documento anexado e monta um roteiro a partir dele.
 *
 * São de dez segundos a dois minutos: o arquivo pode precisar de OCR e a
 * montagem é uma chamada ao modelo por bloco. Por isso o `aoProgredir` — sem
 * ele o advogado olha para um botão travado sem saber se falta muito.
 */
export async function importarRoteiro(
  arquivo: File,
  aoProgredir?: (pct: number, etapa: string) => void,
): Promise<RoteiroImportado> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  const criado = await comoJson<{ job_id: string }>(
    await buscar("/api/roteiros/importar", { method: "POST", body: form }),
  );

  // Generoso porque o teto real é o do worker: um PDF digitalizado de vinte
  // páginas gasta OCR antes da primeira chamada ao modelo.
  const limite = Date.now() + 10 * 60_000;
  while (Date.now() < limite) {
    const job = await comoJson<{
      status: "QUEUED" | "STARTED" | "PROCESSING" | "COMPLETED" | "FAILED";
      progresso?: number;
      erro?: string | null;
      resultado?: (RoteiroImportado & { etapa?: string }) | null;
    }>(await buscar(`/api/jobs/${criado.job_id}`));

    if (job.status === "COMPLETED" && job.resultado?.roteiro) return job.resultado;
    if (job.status === "FAILED") {
      throw new ApiError(job.erro || "Não foi possível montar o roteiro deste documento.");
    }
    // Enquanto corre, `resultado` carrega só a etapa: o backend não tem coluna
    // para ela e reaproveitar o campo evita uma migração por uma frase.
    aoProgredir?.(job.progresso ?? 0, job.resultado?.etapa ?? "Na fila");
    await new Promise((resolver) => window.setTimeout(resolver, 1500));
  }
  throw new ApiError("A importação continua em andamento. Tente consultar em instantes.");
}

/** Grava o roteiro no catálogo — o recém-importado ou o editado no atendimento. */
export async function salvarRoteiro(
  roteiro: RoteiroCompleto,
  origem = "",
): Promise<RoteiroCompleto> {
  const salvo = await comoJson<RoteiroCompleto>(
    await buscar("/api/roteiros", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roteiro, origem }),
    }),
  );
  invalidarCacheRoteiros(roteiro.codigo);
  roteirosCompletos.set(salvo.codigo, {
    ate: Date.now() + TTL_ROTEIROS_MS,
    valor: Promise.resolve(salvo),
  });
  return salvo;
}

/** Tira o roteiro do catálogo. Num que também existe em código, desfaz a edição. */
export async function excluirRoteiroSalvo(
  codigo: string,
): Promise<{ revertido_para_o_modulo: boolean }> {
  const resultado = await comoJson<{ revertido_para_o_modulo: boolean }>(
    await buscar(`/api/roteiros/${codigo}`, { method: "DELETE" }),
  );
  invalidarCacheRoteiros(codigo);
  return resultado;
}

/* ------------------------------------------- checklist do roteiro (secretário)
 *
 * O checklist tem DUAS origens, e elas não se misturam de propósito.
 *
 * `ChecklistRegistro` sai do banco — assinatura enviada, avaliação marcada,
 * documento recebido. É fato, é barato de consultar e carrega junto com a tela.
 *
 * `Auditoria` (acima) sai da leitura da transcrição pelo modelo, custa uma ida ao
 * DeepSeek e por isso só roda quando o secretário pede. A tela junta as duas em uma
 * lista só, mas mantém visível de onde cada linha veio: uma diz o que ACONTECEU,
 * a outra o que APARECE na conversa — e a segunda erra. */

export type SituacaoItem = "feito" | "pendente" | "incerto" | "nao_aplica";

export interface ItemChecklist {
  id: string;
  titulo: string;
  detalhe: string;
  /** Pílula à direita da linha: "Assinatura", "Dossiê", "Crítico"… */
  etiqueta: string;
  situacao: SituacaoItem;
  /** O que não tem segunda chance depois que o cliente desliga. */
  critico: boolean;
}

export interface FaseChecklist {
  codigo: string;
  titulo: string;
  descricao: string;
  itens: ItemChecklist[];
}

export interface ChecklistRegistro {
  entrevista_id: string;
  entrevistador: string;
  caso: { id: string; cliente: string; categoria: string };
  realizada_em: string | null;
  criado_em: string | null;
  avaliacao_google: boolean;
  /** "ao_vivo" foi conduzida pelo roteiro e tem áudio; "anexada" veio de arquivo. */
  origem: "ao_vivo" | "anexada";
  gravacao_id: string;
  fases: FaseChecklist[];
  progresso: { feitos: number; total: number; percentual: number };
}

/** GET, e não POST: nada aqui vai ao modelo, então repetir a chamada não custa. */
export async function obterChecklist(id: string): Promise<ChecklistRegistro> {
  return comoJson(
    await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}/checklist`),
  );
}

/** Conserta a marcação da avaliação do Google. Devolve o checklist já refeito. */
export async function corrigirAvaliacaoGoogle(
  id: string,
  concluida: boolean,
): Promise<ChecklistRegistro> {
  return comoJson(
    await buscar(`/api/supervisao/entrevistas/${encodeURIComponent(id)}/avaliacao-google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ concluida }),
    }),
  );
}

/** A marcação do atendente, no atendimento — com o cliente ainda na chamada. */
export async function marcarAvaliacaoGoogle(
  casoId: string,
  entrevistaId: string,
  concluida: boolean,
): Promise<{ avaliacao_google: boolean }> {
  return comoJson(
    await buscar(
      `/api/casos/${encodeURIComponent(casoId)}/entrevista/${encodeURIComponent(entrevistaId)}/avaliacao-google`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ concluida }),
      },
    ),
  );
}
