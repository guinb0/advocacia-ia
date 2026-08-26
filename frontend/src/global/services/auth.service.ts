import { Md5 } from "ts-md5";

import api from "./api";
import type { SessaoUsuario } from "@/app/page.interface";

/**
 * As chamadas de sessão, no mesmo formato do `auth.service.ts` do DFLegal.
 *
 * A senha sai daqui já em MD5 e o identificador em base64 — é o contrato que o
 * backend espera (`app/usuarios.py`). Vale dizer o que cada um faz e o que não
 * faz: o base64 não esconde nada de quem olha a requisição, é só formato; o MD5
 * evita que a senha em claro apareça no corpo e no log do servidor, mas NÃO
 * protege a tabela — se ela vazar, os hashes caem numa tabela pronta.
 *
 * O TOKEN NÃO PASSA POR AQUI. Ele chega em cookie `HttpOnly`, que este código
 * não consegue ler nem escrever — e é justamente essa impossibilidade que o
 * protege de um XSS. O que volta no corpo são os dados de exibição da sessão.
 */

type LoginPayload = {
  email: string;
  senha: string;
};

type Envelope<T> = { flag: boolean; message?: string; data: T };

export async function LoginService(payload: LoginPayload): Promise<SessaoUsuario> {
  /* `porta: true` para o 401 aqui chegar como "senha incorreta" e não como
   * "sessão expirada" — ver o comentário em `api.ts`. */
  const resposta = await api.post<Envelope<SessaoUsuario>>(
    "/api/user/authenticate",
    {
      email: btoa(payload.email.trim().toLowerCase()),
      senha: Md5.hashStr(payload.senha),
      TipoLogin: "email",
    },
    { porta: true },
  );

  if (!resposta?.flag || !resposta.data) {
    throw new Error(resposta?.message || "Não foi possível entrar.");
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
    const resposta = await api.get<Envelope<SessaoUsuario>>("/api/user/my-account");
    return resposta?.data ?? null;
  } catch {
    // 401 já derruba para o login dentro do `api.ts`. Qualquer outra falha aqui
    // é rede instável, e devolver `null` deixa a tela seguir com o que já tem.
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
