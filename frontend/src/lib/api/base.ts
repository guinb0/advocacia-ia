/** Transporte comum: endereço da API, `buscar` com o cookie de sessão, erros e anexos. */

import type { DuplicidadeDocumento } from "../types";

/**
 * O navegador fala direto com o FastAPI, sem passar pelo rewrite do Next.
 *
 * O proxy do Next derruba a conexão em 30s (timeout fixo, sem opção de config) e
 * ainda bufferiza o upload inteiro na memória do Node. Como uma foto de celular tem
 * vários MB e o OCR leva de 3 a 30s, o upload morria com "socket hang up". Falar
 * direto com o Python elimina o intermediário — o backend já habilita CORS.
 */
/* Mesma regra do `global/services/api.ts`, e pelo mesmo motivo: a API precisa
 * ficar no host da página, senão o cookie de sessão não alcança o `proxy.ts` e o
 * login entra em laço. O default acompanha de onde o app foi aberto — `origin`
 * inteiro, protocolo E porta.
 *
 * NÃO cravar `:8100` aqui. Em produção o backend fica atrás de um proxy na 443 e
 * a porta 8100 não é publicada: `https://host:8100` vira `ERR_CONNECTION_REFUSED`
 * em todas as telas que usam este cliente. Em desenvolvimento, quando o front
 * roda numa porta diferente do backend, defina `NEXT_PUBLIC_OCR_API`
 * (ou `OCR_API_PUBLIC_URL`, que o `iniciar.sh`/`iniciar.ps1` propagam). */
const BASE =
  process.env.NEXT_PUBLIC_OCR_API ||
  (typeof window !== "undefined" ? window.location.origin : "http://localhost:8100");

/** Monta a URL absoluta da API a partir de um caminho tipo "/api/temp/x.json". */
export function urlApi(caminho: string): string {
  return `${BASE}${caminho}`;
}

export class ApiError extends Error {
  readonly status?: number;
  /** O corpo JSON da resposta de erro — é por onde o 409 de duplicidade traz a lista. */
  readonly dados?: unknown;

  constructor(message: string, options?: ErrorOptions & { status?: number; dados?: unknown }) {
    super(message, options);
    this.name = "ApiError";
    this.status = options?.status;
    this.dados = options?.dados;
  }
}

/* O TOKEN NÃO PASSA MAIS POR AQUI.
 *
 * Ele era guardado nesta variável — fora do localStorage, para que um XSS não
 * levasse a sessão inteira. Agora ele vive num cookie `HttpOnly`, que o
 * JavaScript não consegue ler de jeito nenhum: a mesma proteção, garantida pelo
 * navegador em vez de por disciplina nossa.
 *
 * O preço é que toda chamada precisa de `credentials: "include"`, senão o
 * navegador não manda cookie para outra origem e a rota responde 401. É o par
 * do `allow_credentials=True` do FastAPI (ver `app/main.py`).
 */
export const CREDENCIAIS: RequestCredentials = "include";

/* Continua exportada porque `lib/agente.ts` tem o próprio cliente e chama por
 * aqui. Não acrescenta mais nada aos cabeçalhos — o que autenticava era o
 * `Authorization`, e ele saiu. Fica como ponto único caso volte a existir um
 * cabeçalho comum a todas as chamadas. */
export function cabecalhos(extra?: HeadersInit): HeadersInit | undefined {
  return extra;
}

/** fetch com o cookie de sessão anexado — todo acesso à API passa por aqui. */
/* "Failed to fetch" é o que o navegador diz quando a requisição não chega ao
 * servidor — conexão recusada, CORS barrado, extensão bloqueando. A frase não
 * nomeia o endereço, e como este app fala com TRÊS servidores em portas
 * diferentes (API na 8100, transcrição na 8200, chamadas na 8081), ela manda
 * procurar o defeito em três lugares ao mesmo tempo.
 *
 * Aqui a falha de rede vira uma frase que diz para onde a chamada ia. O erro
 * original segue em `cause`, para o console não perder o rastro. */
export async function buscar(caminho: string, init: RequestInit = {}): Promise<Response> {
  const url = urlApi(caminho);
  let resposta: Response;
  try {
    resposta = await fetch(url, { ...init, credentials: CREDENCIAIS });
  } catch (erro) {
    throw new ApiError(
      `Não foi possível falar com o servidor em ${url}. ` +
        "Confira se ele está no ar e se o endereço está certo.",
      { cause: erro },
    );
  }
  if (resposta.status === 401 && typeof window !== "undefined") {
    // A sessão venceu. A carteira não deve fingir que é falha de dados: limpa o
    // estado local (quem escuta é o `ContextWrapper`) e devolve ao login.
    window.dispatchEvent(new Event("acervo:sessao-expirada"));
    /* Apaga o cookie no servidor antes de sair, senão o `proxy.ts` devolve para
     * `/home` e o 401 se repete — o laço. */
    void fetch(urlApi("/api/user/logout"), { method: "POST", credentials: CREDENCIAIS })
      .catch(() => undefined)
      .finally(() => {
        if (window.location.pathname !== "/") window.location.href = "/";
      });
  }
  return resposta;
}

export async function comoJson<T>(resposta: Response): Promise<T> {
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new ApiError(detalhe, { status: resposta.status, dados: corpo });
  }
  return corpo as T;
}

/** Os documentos parecidos, quando o erro é o 409 de duplicidade; `null` nos demais.
 *
 * O 409 também serve a outros conflitos (versão do glossário, categoria removida),
 * então quem decide é o `codigo` do corpo, e não o status sozinho. */
export function duplicidadesDoErro(erro: unknown): DuplicidadeDocumento[] | null {
  if (!(erro instanceof ApiError) || erro.status !== 409) return null;
  const dados = erro.dados as { codigo?: string; duplicidades?: DuplicidadeDocumento[] } | null;
  return dados?.codigo === "DOCUMENTO_DUPLICADO" && Array.isArray(dados.duplicidades)
    ? dados.duplicidades
    : null;
}

/** Nome do arquivo vindo do Content-Disposition, preferindo a forma UTF-8. */
export function nomeDoAnexo(r: Response, padrao = "contrato.docx"): string {
  const cabecalho = r.headers.get("Content-Disposition") ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      /* nome malformado: cai no genérico abaixo */
    }
  }
  return /filename="([^"]+)"/i.exec(cabecalho)?.[1] ?? padrao;
}
