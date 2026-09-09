import { Md5 } from "ts-md5";

import api from "./api";
import { urlApi } from "@/lib/api";
import type {
  ConfiguracaoDeAcesso,
  DesafioDeAcesso,
  RespostaDeLogin,
  SessaoUsuario,
} from "@/app/page.interface";

/**
 * As chamadas de sessão, no mesmo formato do `auth.service.ts` do DFLegal.
 *
 * A senha sai daqui já em MD5 e o identificador em base64 — é o contrato que o
 * backend espera (`app/usuarios.py`). Vale dizer o que cada um faz e o que não
 * faz: o base64 não esconde nada de quem olha a requisição, é só formato; o MD5
 * evita que a senha em claro apareça no corpo e no log do servidor, mas NÃO
 * protege a tabela — se ela vazar, os hashes caem numa tabela pronta. É
 * justamente esse buraco que o segundo fator abaixo passa a cobrir.
 *
 * O TOKEN NÃO PASSA POR AQUI. Ele chega em cookie `HttpOnly`, que este código
 * não consegue ler nem escrever — e é justamente essa impossibilidade que o
 * protege de um XSS. O que volta no corpo são os dados de exibição da sessão.
 *
 * O LOGIN TEM DOIS PASSOS AGORA. `LoginService` confere senha e captcha; quando
 * o perfil exige segundo fator, ele devolve `etapa: "dois_fatores"` e NENHUMA
 * sessão — a credencial só nasce em `ConfirmarCodigoService`.
 */

type LoginPayload = {
  email: string;
  senha: string;
  /** Token do Turnstile. Vazio quando o captcha está desligado no servidor. */
  captcha?: string;
};

type Envelope<T> = { flag: boolean; message?: string; data: T };

export async function ConfigDeAcessoService(): Promise<ConfiguracaoDeAcesso | null> {
  /* Fetch direto e não o `api`: esta chamada roda na tela de login, onde não há
   * sessão, e o `api` reage a 401 mandando para o login — daria um laço. */
  try {
    const resposta = await fetch(urlApi("/api/config"), { cache: "no-store" });
    if (!resposta.ok) return null;
    return (await resposta.json()) as ConfiguracaoDeAcesso;
  } catch {
    /* API fora do ar: a tela desenha o formulário sem captcha e a tentativa de
     * entrar mostra o erro de rede, que é a mensagem certa. Bloquear o login
     * porque a configuração não chegou seria esconder o problema real. */
    return null;
  }
}

export async function LoginService(payload: LoginPayload): Promise<RespostaDeLogin> {
  /* `porta: true` para o 401 aqui chegar como "senha incorreta" e não como
   * "sessão expirada" — ver o comentário em `api.ts`. */
  const resposta = await api.post<Envelope<RespostaDeLogin>>(
    "/api/user/authenticate",
    {
      email: btoa(payload.email.trim().toLowerCase()),
      senha: Md5.hashStr(payload.senha),
      TipoLogin: "email",
      captcha: payload.captcha ?? "",
    },
    { porta: true },
  );

  if (!resposta?.flag || !resposta.data) {
    throw new Error(resposta?.message || "Não foi possível entrar.");
  }
  return resposta.data;
}

export async function ConfirmarCodigoService(payload: {
  desafio: string;
  codigo: string;
}): Promise<SessaoUsuario> {
  /* Também `porta: true`: um código errado devolve 401, e sem isto a tela diria
   * "sua sessão expirou" para quem ainda nem tem sessão — e ainda mandaria a
   * pessoa de volta ao começo, perdendo o código que acabou de chegar. */
  const resposta = await api.post<Envelope<RespostaDeLogin>>(
    "/api/user/authenticate/verify",
    { desafio: payload.desafio, codigo: payload.codigo.trim() },
    { porta: true },
  );

  if (!resposta?.flag || !resposta.data || resposta.data.etapa !== "sessao") {
    throw new Error(resposta?.message || "Não foi possível confirmar o código.");
  }
  return resposta.data;
}

export async function ReenviarCodigoService(desafio: string): Promise<DesafioDeAcesso> {
  const resposta = await api.post<Envelope<RespostaDeLogin>>(
    "/api/user/authenticate/resend",
    { desafio },
    { porta: true },
  );

  if (!resposta?.flag || !resposta.data || resposta.data.etapa !== "dois_fatores") {
    throw new Error(resposta?.message || "Não foi possível reenviar o código.");
  }
  return resposta.data;
}

export async function LogoutService(): Promise<void> {
  /* Falha de logout não pode travar a saída. Se a API não responder, o cookie de
   * sessão continua no navegador até vencer — ruim, mas menos ruim que prender
   * o usuário numa tela dizendo que não conseguiu sair. Quem chama limpa o
   * estado local de qualquer jeito. */
  await api.post("/api/user/logout").catch(() => undefined);
}

export async function MyAccountService(): Promise<SessaoUsuario | null> {
  try {
    /* NÃO usa o `api` global: ele redireciona para `/` ao receber 401, e esta
     * chamada roda em TODAS as páginas — inclusive as públicas (`/portal/[token]`,
     * `/chamada/[sala]`), onde 401 é o estado esperado. Fetch direto deixa o
     * 401 ser apenas "não logado", sem efeito colateral. */
    const resposta = await fetch(urlApi("/api/user/my-account"), {
      cache: "no-store",
      credentials: "include",
    });
    if (!resposta.ok) return null;
    const corpo = (await resposta.json()) as Envelope<SessaoUsuario>;
    return corpo?.data ?? null;
  } catch {
    return null;
  }
}

export async function ChangePasswordService(novaSenha: string): Promise<void> {
  /* Sem `codigo` no corpo, ao contrário do DFLegal: a conta alvo sai do token, no
   * servidor. Aceitar o código de quem terá a senha trocada transformaria esta
   * rota em redefinição de senha alheia no dia em que alguém esquecesse de
   * conferir quem chamou. */
  await api.put("/api/user/change-password", { senha: Md5.hashStr(novaSenha) });
}
