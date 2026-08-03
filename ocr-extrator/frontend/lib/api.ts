import type {
  Caso,
  Categoria,
  Documento,
  Pedido,
  RespostaEnvio,
  SituacaoCaso,
  TipoDocumento,
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
  const dados = await comoJson<{ tipos: TipoDocumento[] }>(await fetch(urlApi("/api/tipos")));
  return dados.tipos;
}

export async function verificarSaude(): Promise<boolean> {
  const dados = await comoJson<{ modelo_carregado: boolean }>(
    await fetch(urlApi("/api/saude")),
  );
  return dados.modelo_carregado;
}

export async function aquecerModelo(): Promise<void> {
  await comoJson(await fetch(urlApi("/api/aquecer"), { method: "POST" }));
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
    await fetch(urlApi("/api/extrair"), { method: "POST", body: form }),
  );
}

export async function baixarTexto(caminho: string): Promise<string> {
  const r = await fetch(urlApi(caminho));
  if (!r.ok) throw new ApiError(`Erro ${r.status}`);
  return r.text();
}

// ------------------------------------------------------------- categorias

export async function listarCategorias(): Promise<Categoria[]> {
  const dados = await comoJson<{ categorias: Categoria[] }>(
    await fetch(urlApi("/api/categorias")),
  );
  return dados.categorias;
}

// ------------------------------------------------------------------ casos

export async function listarCasos(): Promise<Caso[]> {
  const dados = await comoJson<{ casos: Caso[] }>(await fetch(urlApi("/api/casos")));
  return dados.casos;
}

export async function criarCaso(
  cliente: string,
  categoria: string,
  observacao = "",
): Promise<Caso> {
  const form = new FormData();
  form.append("cliente", cliente);
  form.append("categoria", categoria);
  form.append("observacao", observacao);
  return comoJson<Caso>(await fetch(urlApi("/api/casos"), { method: "POST", body: form }));
}

export async function obterCaso(casoId: string): Promise<SituacaoCaso> {
  return comoJson<SituacaoCaso>(await fetch(urlApi(`/api/casos/${casoId}`)));
}

export async function excluirCaso(casoId: string): Promise<void> {
  await comoJson(await fetch(urlApi(`/api/casos/${casoId}`), { method: "DELETE" }));
}

export async function obterPedido(casoId: string, incluirOpcionais: boolean): Promise<Pedido> {
  const query = incluirOpcionais ? "?incluir_opcionais=true" : "";
  return comoJson<Pedido>(await fetch(urlApi(`/api/casos/${casoId}/pedido${query}`)));
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
    await fetch(urlApi(`/api/casos/${casoId}/documentos`), { method: "POST", body: form }),
  );
}

export async function vincularIdentidadeUnificada(
  casoId: string,
  entregaId: string,
): Promise<RespostaEnvio> {
  const form = new FormData();
  form.append("entrega_id", entregaId);
  return comoJson<RespostaEnvio>(
    await fetch(urlApi(`/api/casos/${casoId}/identidade-unificada`), {
      method: "POST",
      body: form,
    }),
  );
}

export async function excluirEntrega(entregaId: string): Promise<void> {
  await comoJson(await fetch(urlApi(`/api/entregas/${entregaId}`), { method: "DELETE" }));
}

export function urlArquivoEntrega(entregaId: string): string {
  return urlApi(`/api/entregas/${entregaId}/arquivo`);
}
