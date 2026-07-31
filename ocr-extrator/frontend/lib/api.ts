import type { Documento, TipoDocumento } from "./types";

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
