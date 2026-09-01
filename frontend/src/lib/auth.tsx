"use client";

import { useUser } from "@/contexts/ContextWrapper";

/**
 * `useSessao`, agora servido pelo `ContextWrapper`.
 *
 * POR QUE ESTE ARQUIVO CONTINUA EXISTINDO
 *
 * Ele era o adaptador do Keycloak — instanciava o `keycloak-js`, cuidava do
 * PKCE e renovava o token num relógio de 30 em 30 segundos. Nada disso sobrou:
 * o token é um cookie `HttpOnly` que o JavaScript não vê nem precisa renovar,
 * e quem barra quem não tem sessão é o `src/proxy.ts`, no servidor.
 *
 * O que ficou é a FORMA. Quatro componentes (`Carteira`, `Roteiro` e os que
 * vierem) pedem `useSessao()` para saber o nome de quem está atendendo e para
 * oferecer o "sair". Reescrever os quatro para `useUser()` seria trocar o nome
 * da mesma coisa em quatro lugares; manter este adaptador custa vinte linhas e
 * deixa a migração acontecer quando cada um for mexido por outro motivo.
 */

export interface Sessao {
  carregando: boolean;
  autenticado: boolean;
  /** O e-mail, que neste sistema é o nome de usuário. */
  usuario: string;
  nome: string;
  /** O perfil, em lista — a forma que os componentes já consumiam quando o
   *  perfil era papel de realm e podia haver mais de um. */
  papeis: string[];
  /** Os módulos do Acervo que este perfil alcança (ver `app/perfis.py`). */
  modulos: string[];
  erro: string | null;
  entrar: () => void;
  sair: () => void;
}

/**
 * A autenticação está ligada?
 *
 * Vem de `NEXT_PUBLIC_AUTH_DESATIVADA` e não mais da presença de uma URL de
 * Keycloak. Quem desliga os dois lados de uma vez continua sendo o
 * `iniciar.ps1 -SemAuth`, que zera esta variável e o `JWT_SECRET` do backend —
 * é o alinhamento que evita o pior estado possível: tela pedindo login com a
 * API aberta, ou o contrário.
 */
export const AUTH_ATIVA = process.env.NEXT_PUBLIC_AUTH_DESATIVADA !== "1";

export function useSessao(): Sessao {
  const { loggedUser, carregando, sair } = useUser();

  return {
    carregando,
    // Sem autenticação, todo mundo está "autenticado" — é o que mantém as telas
    // que checam isto funcionando no modo de depuração, como antes.
    autenticado: !AUTH_ATIVA || Boolean(loggedUser),
    usuario: loggedUser?.email ?? "",
    nome: loggedUser?.nome ?? "",
    papeis: loggedUser?.perfil ? [loggedUser.perfil] : [],
    modulos: loggedUser?.modulos ?? [],
    erro: null,
    /* `entrar` virou navegação, e não mais um redirecionamento para o servidor
     * de identidade: a tela de login é uma página desta aplicação. */
    entrar: () => {
      if (typeof window !== "undefined") window.location.href = "/";
    },
    sair: () => void sair(),
  };
}
