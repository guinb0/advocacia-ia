/**
 * Função base de todas as requisições da aplicação — o mesmo `apiFetch` dos
 * demais projetos da Level, com uma diferença registrada abaixo.
 *
 * `credentials: "include"` é o que faz o cookie `JwtToken` acompanhar a chamada.
 * Sem ele o navegador não manda cookie para outra origem, e toda rota protegida
 * responderia 401 — que era exatamente o sintoma de quem esquecia esta linha.
 *
 * O PAR DISSO NO SERVIDOR: o FastAPI precisa de `allow_credentials=True` e da
 * lista explícita de origens (ver `app/main.py`). Com `allow_origins=["*"]` o
 * navegador RECUSA a resposta quando há credencial em jogo — o erro que aparece
 * é um CORS genérico que não menciona cookie nenhum.
 */

/* A base da API tem de ficar no MESMO HOST da página, e isso não é preferência.
 *
 * O cookie de sessão é gravado pelo host que responde. Se a página vem de
 * `192.168.5.241:3000` e a API de `localhost:8100`, o cookie nasce em
 * `localhost`: a API passa a enxergá-lo e o `proxy.ts` — que roda no servidor do
 * Next, em `192.168.5.241` — NÃO. Aí a API diz "autenticado", o guarda de rota
 * diz "não autenticado", e os dois se empurram num laço infinito de
 * /home -> / -> /home. Foi exatamente o que aconteceu.
 *
 * Por isso o default deriva do host da própria página em vez de cravar
 * `localhost`: assim ele acompanha de onde o app foi aberto, seja localhost, IP
 * da rede ou domínio publicado. `NEXT_PUBLIC_OCR_API` continua vencendo quando
 * definido — e quando o que ele define não bate com a página, o aviso abaixo
 * grita, em vez de deixar o laço acontecer em silêncio. */
const PORTA_API = "8100";

function baseDaApi(): string {
  const definida = process.env.API_URL || process.env.NEXT_PUBLIC_OCR_API;
  if (typeof window === "undefined") return definida || `http://localhost:${PORTA_API}`;

  const doNavegador = window.location.origin;
  if (!definida) return doNavegador;

  try {
    if (new URL(definida).hostname !== window.location.hostname) {
      console.error(
        `[Acervo] A API está configurada em ${definida}, mas a página foi aberta em ` +
          `${window.location.origin}. São hosts diferentes: o cookie de sessão não ` +
          `alcança o guarda de rota e o login entra em laço. Ajuste OCR_API_PUBLIC_URL ` +
          `e APP_PUBLIC_URL no .env para o mesmo host.`,
      );
    }
  } catch {
    // Valor inválido no .env: o `||` abaixo devolve o do navegador.
  }
  return definida;
}

const API_URL = baseDaApi();


export class AuthError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "AuthError";
  }
}

export class HttpError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** Monta a URL absoluta da API a partir de um caminho tipo "/api/casos". */
export function urlApi(caminho: string): string {
  return `${API_URL}${caminho}`;
}

/* O prazo é longo (10 min) porque o OCR de um documento leva de 3 a 30s e a
 * transcrição de uma entrevista leva minutos. Um timeout curto aqui não protege
 * ninguém: só transforma trabalho concluído em erro na tela. */
const PRAZO_PADRAO = 600_000;

/** Opções que não são do `fetch`, e sim de como tratar a resposta. */
interface Tratamento {
  /** Esta chamada é a PORTA (login), e não uma chamada de dentro da sessão.
   *
   * Muda o significado do 401. Numa chamada comum ele quer dizer "sua sessão
   * acabou" e o certo é voltar ao login. No próprio login ele quer dizer "essa
   * senha não confere" — e tratar os dois igual produz a pior mensagem
   * possível: o usuário digita a senha errada e a tela responde que a sessão
   * expirou, mandando-o resolver um problema que ele não tem. Aconteceu. */
  porta?: boolean;
}

async function baseFetch<T = unknown>(
  url: string,
  options: RequestInit = {},
  timeoutMs = PRAZO_PADRAO,
  tratamento: Tratamento = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(urlApi(url), {
      ...options,
      credentials: "include", // manda o cookie JwtToken
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      if (response.status === 401 && !tratamento.porta) {
        /* Sessão vencida ou ausente: o lugar de resolver isso é o login.
         *
         * O evento vem antes do redirecionamento porque quem escuta (o
         * `ContextWrapper`) precisa limpar os cookies de sessão — sem isso a
         * tela de login voltaria a "restaurar" um usuário que não vale mais e
         * mostraria o nome de alguém que não está logado. */
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("acervo:sessao-expirada"));
          /* Derruba o cookie NO SERVIDOR antes de sair. Sem isto, o `proxy.ts`
           * ainda enxergaria uma sessão válida em `/` e devolveria para `/home`,
           * que tornaria a levar 401 — o laço. Apagar a credencial é o que faz
           * os dois lados concordarem que não há sessão. */
          void fetch(urlApi("/api/user/logout"), { method: "POST", credentials: "include" })
            .catch(() => undefined)
            .finally(() => {
              if (window.location.pathname !== "/") window.location.href = "/";
            });
        }
        throw new AuthError("Sua sessão expirou. Entre novamente.");
      }

      const errorData = await response.json().catch(() => ({}));
      // O FastAPI devolve o motivo em `detail`; os projetos .NET, em `message`.
      // Aceitar os dois deixa este cliente servir aos dois back-ends sem ramo.
      const message =
        typeof errorData === "string"
          ? errorData
          : (errorData?.detail ?? errorData?.message ?? "");

      throw new HttpError(message || "Erro desconhecido na requisição", response.status);
    }

    if (response.status === 204) return null as T;
    return (await response.json()) as T;
  } catch (err: unknown) {
    clearTimeout(timeout);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Requisição expirada (timeout)");
    }
    throw err;
  }
}

async function baseFetchBlob(
  url: string,
  options: RequestInit = {},
  timeoutMs = PRAZO_PADRAO,
): Promise<Blob> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(urlApi(url), {
      ...options,
      credentials: "include",
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      if (response.status === 401 && typeof window !== "undefined") {
        window.dispatchEvent(new Event("acervo:sessao-expirada"));
        window.location.href = "/";
      }
      const errorData = await response.json().catch(() => ({}));
      const message =
        typeof errorData === "string"
          ? errorData
          : (errorData?.detail ?? errorData?.message ?? "");
      throw new HttpError(message || "Erro desconhecido na requisição", response.status);
    }

    return response.blob();
  } catch (err: unknown) {
    clearTimeout(timeout);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Requisição expirada (timeout)");
    }
    throw err;
  }
}

const jsonHeaders = { "Content-Type": "application/json" };

function buildQueryParams(params?: Record<string, unknown>): string {
  if (!params) return "";

  const queryParams = new URLSearchParams();

  for (const key in params) {
    const value = params[key];
    if (
      value !== undefined &&
      value !== null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0)
    ) {
      if (Array.isArray(value)) {
        // Repete a chave para valores em lista: ?key=a&key=b
        value.forEach((item) => queryParams.append(key, String(item)));
      } else {
        queryParams.append(key, String(value));
      }
    }
  }

  const queryString = queryParams.toString();
  return queryString ? `?${queryString}` : "";
}

const apiFetch = {
  get: <T = unknown>(url: string, options?: { params?: Record<string, unknown> }) =>
    baseFetch<T>(`${url}${buildQueryParams(options?.params)}`, { method: "GET" }),

  getBlob: (url: string, options?: { params?: Record<string, unknown> }) =>
    baseFetchBlob(`${url}${buildQueryParams(options?.params)}`, { method: "GET" }),

  // `FormData` não leva `Content-Type`: quem o define é o navegador, junto do
  // `boundary`. Escrevê-lo à mão corrompe o upload — o corpo chega ilegível.
  post: <T = unknown>(url: string, body?: unknown, tratamento?: Tratamento) =>
    baseFetch<T>(
      url,
      {
        method: "POST",
        headers: body instanceof FormData ? undefined : jsonHeaders,
        body: body instanceof FormData ? body : JSON.stringify(body),
      },
      PRAZO_PADRAO,
      tratamento,
    ),

  put: <T = unknown>(url: string, body?: unknown) =>
    baseFetch<T>(url, { method: "PUT", headers: jsonHeaders, body: JSON.stringify(body) }),

  patch: <T = unknown>(url: string, body?: unknown) =>
    baseFetch<T>(url, {
      method: "PATCH",
      headers: body instanceof FormData ? undefined : jsonHeaders,
      body: body instanceof FormData ? body : JSON.stringify(body),
    }),

  delete: <T = unknown>(url: string) => baseFetch<T>(url, { method: "DELETE" }),
};

export default apiFetch;
