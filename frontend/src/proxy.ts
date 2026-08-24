import { jwtVerify } from "jose";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * A guarda de rota, no papel que o `middleware.ts` do DFLegal exerce lá.
 *
 * O ARQUIVO NÃO SE CHAMA `middleware.ts` PORQUE ESTE NEXT É O 16: a convenção
 * foi renomeada para `proxy.ts`, com a função exportada como `proxy`. Um
 * `middleware.ts` aqui seria ignorado em silêncio — e "guarda ignorada em
 * silêncio" é a pior falha possível para um arquivo com este propósito.
 *
 * Ela roda no SERVIDOR (o `proxy` usa o runtime Node por padrão), antes de
 * qualquer JavaScript da página. É por isso que `JWT_SECRET` pode ser lido aqui
 * e não precisa — nem deve — ter o prefixo `NEXT_PUBLIC_`: o que tem esse
 * prefixo é embutido no pacote que vai para o navegador, e um segredo de
 * assinatura publicado assim deixaria qualquer pessoa forjar sessão.
 *
 * O QUE ESTA GUARDA É, E O QUE ELA NÃO É
 *
 * Ela evita a piscada: sem token válido, o usuário nunca chega a ver a tela do
 * escritório carregando para só então ser expulso. Não é a proteção dos dados —
 * essa é do backend, que confere o mesmo token em toda requisição. Se um dia as
 * duas discordarem, quem manda é o backend.
 */

const SEGREDO = process.env.JWT_SECRET ?? "";
const COOKIE = process.env.JWT_COOKIE || "JwtToken";

/** Os cookies auxiliares de sessão (ver `contexts/ContextWrapper.tsx`). Saem
 *  junto do token: deixá-los para trás faria o login exibir o nome de quem
 *  acabou de ser expulso. */
const COOKIES_SESSAO = [COOKIE, "UID", "UP", "UN", "UM", "USP"];

/** Rotas do escritório. Tudo que começa com isto exige sessão.
 *
 * É uma lista do que se PROTEGE, e não do que se libera, porque o resto do app
 * é feito de páginas que precisam ficar abertas: `/` é o login, `/portal/[token]`
 * é do cliente — que não tem conta no escritório e entra pela senha do caso — e
 * `/chamada/[sala]` é aberta por link, como qualquer videoconferência. Uma lista
 * de exceções teria que crescer junto delas, e esquecer uma tranca o cliente
 * para fora do próprio processo. */
const PROTEGIDAS = ["/home"];

async function sessaoValida(token: string): Promise<boolean> {
  try {
    await jwtVerify(token, new TextEncoder().encode(SEGREDO));
    return true;
  } catch {
    // Assinatura errada, token vencido ou corrompido — para esta guarda dá tudo
    // no mesmo: não entra. O motivo exato aparece no 401 do backend.
    return false;
  }
}

function paraOLogin(request: NextRequest) {
  const resposta = NextResponse.redirect(new URL("/", request.url));
  COOKIES_SESSAO.forEach((nome) => resposta.cookies.delete(nome));
  return resposta;
}

export async function proxy(request: NextRequest) {
  const caminho = request.nextUrl.pathname;

  /* Sem segredo configurado a autenticação está DESLIGADA, espelhando o backend
   * (`JWT_SECRET` vazio abre a API). Os dois lados precisam concordar: uma
   * guarda que barrasse aqui com a API aberta deixaria o sistema inacessível
   * pela tela e acessível por `curl` — o pior dos dois mundos. */
  if (!SEGREDO) return NextResponse.next();

  const token = request.cookies.get(COOKIE)?.value;

  // Já logado abrindo o login: vai direto para a carteira, em vez de digitar
  // senha de novo por ter clicado no favorito.
  if (caminho === "/" && token && (await sessaoValida(token))) {
    return NextResponse.redirect(new URL("/home", request.url));
  }

  const protegida = PROTEGIDAS.some((rota) => caminho === rota || caminho.startsWith(rota + "/"));
  if (!protegida) return NextResponse.next();

  if (!token) return paraOLogin(request);
  if (!(await sessaoValida(token))) return paraOLogin(request);

  return NextResponse.next();
}

export const config = {
  /* Deixa de fora o que não é página: rotas de API do próprio Next, os estáticos
   * do build e o favicon. Rodar a guarda neles custaria uma verificação de
   * assinatura por imagem carregada, sem proteger nada. */
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
