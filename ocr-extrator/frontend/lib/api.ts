import type {
  Caso,
  CasoCriado,
  Categoria,
  Documento,
  EntregaDetalhe,
  Estrategia,
  Pedido,
  PortalEstado,
  PortalGerado,
  RespostaEnvio,
  SituacaoCaso,
  TipoDocumento,
  Triagem as TriagemResposta,
} from "./types";

/**
 * O navegador fala direto com o FastAPI, sem passar pelo rewrite do Next.
 *
 * O proxy do Next derruba a conexão em 30s (timeout fixo, sem opção de config) e
 * ainda bufferiza o upload inteiro na memória do Node. Como uma foto de celular tem
 * vários MB e o OCR leva de 3 a 30s, o upload morria com "socket hang up". Falar
 * direto com o Python elimina o intermediário — o backend já habilita CORS.
 */
const BASE = process.env.NEXT_PUBLIC_OCR_API ?? "http://127.0.0.1:8100";

/** Monta a URL absoluta da API a partir de um caminho tipo "/api/temp/x.json". */
export function urlApi(caminho: string): string {
  return `${BASE}${caminho}`;
}

export class ApiError extends Error {}

/* O token vive aqui, não em localStorage: um XSS que lesse o storage levaria a
 * sessão inteira. Quem mantém isto atualizado é o ProvedorAuth (lib/auth.tsx),
 * inclusive nas renovações. */
let tokenAtual: string | null = null;

export function definirTokenAtual(token: string | null): void {
  tokenAtual = token;
}

function cabecalhos(extra?: HeadersInit): HeadersInit | undefined {
  if (!tokenAtual) return extra;
  return { ...(extra ?? {}), Authorization: `Bearer ${tokenAtual}` };
}

/** fetch com o Bearer anexado — todo acesso à API passa por aqui. */
async function buscar(caminho: string, init: RequestInit = {}): Promise<Response> {
  return fetch(urlApi(caminho), { ...init, headers: cabecalhos(init.headers) });
}

async function comoJson<T>(resposta: Response): Promise<T> {
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe);
  }
  return corpo as T;
}

export async function listarTipos(): Promise<TipoDocumento[]> {
  const dados = await comoJson<{ tipos: TipoDocumento[] }>(await buscar("/api/tipos"));
  return dados.tipos;
}

export async function verificarSaude(): Promise<boolean> {
  const dados = await comoJson<{ modelo_carregado: boolean }>(
    await buscar("/api/saude"),
  );
  return dados.modelo_carregado;
}

export async function aquecerModelo(): Promise<void> {
  await comoJson(await buscar("/api/aquecer", { method: "POST" }));
}

export async function extrair(
  arquivo: File,
  idioma: string,
  tipo: string,
): Promise<Documento> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("tipo", tipo);
  return comoJson<Documento>(
    await buscar("/api/extrair", { method: "POST", body: form }),
  );
}

export async function baixarTexto(caminho: string): Promise<string> {
  const r = await buscar(caminho);
  if (!r.ok) throw new ApiError(`Erro ${r.status}`);
  return r.text();
}

// ------------------------------------------------------------- categorias

export async function listarCategorias(): Promise<Categoria[]> {
  const dados = await comoJson<{ categorias: Categoria[] }>(
    await buscar("/api/categorias"),
  );
  return dados.categorias;
}

// ------------------------------------------------------------------ casos

export async function listarCasos(): Promise<Caso[]> {
  const dados = await comoJson<{ casos: Caso[] }>(await buscar("/api/casos"));
  return dados.casos;
}

export async function criarCaso(
  cliente: string,
  categoria: string,
  observacao = "",
): Promise<CasoCriado> {
  const form = new FormData();
  form.append("cliente", cliente);
  form.append("categoria", categoria);
  form.append("observacao", observacao);
  return comoJson<CasoCriado>(await buscar("/api/casos", { method: "POST", body: form }));
}

export async function obterCaso(casoId: string): Promise<SituacaoCaso> {
  return comoJson<SituacaoCaso>(await buscar(`/api/casos/${casoId}`));
}

export async function excluirCaso(casoId: string): Promise<void> {
  await comoJson(await buscar(`/api/casos/${casoId}`, { method: "DELETE" }));
}

export async function obterPedido(casoId: string, incluirOpcionais: boolean): Promise<Pedido> {
  const query = incluirOpcionais ? "?incluir_opcionais=true" : "";
  return comoJson<Pedido>(await buscar(`/api/casos/${casoId}/pedido${query}`));
}

// ----------------------------------------------------- triagem da entrevista

/** Classifica o relato e sugere a categoria. NÃO cria caso — só sugere. */
export async function triarEntrevista(texto: string, arquivo?: File): Promise<TriagemResposta> {
  const form = new FormData();
  form.append("texto", texto);
  if (arquivo) form.append("arquivo", arquivo);
  return comoJson<TriagemResposta>(
    await buscar("/api/triagem", { method: "POST", body: form }),
  );
}

/** Recupera processos semelhantes e gera apoio estratégico fundamentado. */
export async function analisarEstrategia(relato: string): Promise<Estrategia> {
  return comoJson<Estrategia>(
    await buscar("/api/estrategia", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relato, limite_precedentes: 8 }),
    }),
  );
}

// -------------------------------------------------------- portal do cliente

/** Gera (ou troca) o link e a senha. A senha volta só nesta resposta. */
export async function gerarPortal(casoId: string): Promise<PortalGerado> {
  return comoJson<PortalGerado>(
    await buscar(`/api/casos/${casoId}/portal`, { method: "POST" }),
  );
}

export async function consultarPortal(casoId: string): Promise<PortalEstado> {
  return comoJson<PortalEstado>(await buscar(`/api/casos/${casoId}/portal`));
}

// --------------------------------------------------------------- entregas

export async function enviarDocumento(
  casoId: string,
  itemCodigo: string,
  arquivo: File,
  idioma = "pt",
  usarParaRgECpf = false,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("item", itemCodigo);
  form.append("arquivo", arquivo);
  form.append("idioma", idioma);
  form.append("usar_para_rg_e_cpf", String(usarParaRgECpf));
  return comoJson<RespostaEnvio>(
    await buscar(`/api/casos/${casoId}/documentos`, { method: "POST", body: form }),
  );
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

/** A entrega com a extração completa — os campos que o visor mostra. */
export async function obterEntrega(entregaId: string): Promise<EntregaDetalhe> {
  return comoJson<EntregaDetalhe>(await buscar(`/api/entregas/${entregaId}`));
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
