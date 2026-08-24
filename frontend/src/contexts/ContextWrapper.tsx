"use client";

import { deleteCookie, getCookie, setCookie } from "cookies-next";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import ReactQueryClientProvider from "@/components/ReactQueryClientProvider/ReactQueryClientProvider";
import { LogoutService, MyAccountService } from "@/global/services/auth.service";
import type { SessaoUsuario } from "@/app/page.interface";

/**
 * O estado global de "quem está logado".
 *
 * POR QUE OS DADOS DA SESSÃO FICAM EM COOKIE, SE O TOKEN JÁ É UM COOKIE
 *
 * O `JwtToken` é `HttpOnly`: o JavaScript não consegue lê-lo, e é isso que o
 * protege de um XSS. O efeito colateral é que a tela não tem como abrir o token
 * para descobrir o nome de quem entrou. Estes cookies auxiliares carregam esse
 * pouco — nome, perfil, código — para a interface se montar já preenchida, sem
 * a piscada de "carregando" a cada navegação.
 *
 * Eles NÃO são credencial. Quem autoriza é o token, conferido no servidor a cada
 * requisição; adulterar `UP` aqui muda o menu que a tela desenha e não abre porta
 * nenhuma — a rota continua respondendo 403. É a mesma divisão do DFLegal.
 *
 * O `my-account` corrige a deriva: perfil trocado no meio do expediente muda no
 * banco e não no cookie, e sem essa releitura o menu ficaria mostrando o alcance
 * antigo até a pessoa sair e entrar.
 */

const COOKIE_ID = "UID";
const COOKIE_PERFIL = "UP";
const COOKIE_NOME = "UN";
const COOKIE_MODULOS = "UM";
const COOKIE_SENHA_PADRAO = "USP";
const COOKIES_SESSAO = [COOKIE_ID, COOKIE_PERFIL, COOKIE_NOME, COOKIE_MODULOS, COOKIE_SENHA_PADRAO];

/** Acompanha a validade do token (24h). Cookie que sobrevive ao token faria a
 *  tela mostrar um usuário logado que leva 401 no primeiro clique. */
const VALIDADE_MS = 24 * 60 * 60 * 1000;

/* base64 no lugar do texto puro pelo mesmo motivo do DFLegal: mantém nome e
 * e-mail fora da lista de cookies em texto legível quando alguém abre o
 * inspetor durante um atendimento, com o cliente olhando a tela. */
function guardar(nome: string, valor: string) {
  setCookie(nome, btoa(encodeURIComponent(valor)), {
    expires: new Date(Date.now() + VALIDADE_MS),
    sameSite: "strict",
  });
}

function ler(nome: string): string | null {
  const bruto = getCookie(nome);
  if (!bruto) return null;
  try {
    return decodeURIComponent(atob(String(bruto)));
  } catch {
    // Cookie de uma versão anterior, ou truncado. Tratar como ausente é melhor
    // que estourar na montagem e deixar a aplicação inteira em tela branca.
    return null;
  }
}

interface Sessao {
  /** `null` enquanto não se sabe; `undefined` nunca — ver `carregando`. */
  loggedUser: SessaoUsuario | null;
  carregando: boolean;
  setCookieLoggedUser: (usuario: SessaoUsuario) => void;
  limparSessao: () => void;
  sair: () => Promise<void>;
}

const Context = createContext<Sessao | null>(null);

export const ContextWrapper = ({ children }: { children: ReactNode }) => {
  const [loggedUser, setLoggedUser] = useState<SessaoUsuario | null>(null);
  const [carregando, setCarregando] = useState(true);

  const setCookieLoggedUser = useCallback((usuario: SessaoUsuario) => {
    setLoggedUser(usuario);
    guardar(COOKIE_ID, usuario.codigo);
    guardar(COOKIE_PERFIL, usuario.perfil);
    guardar(COOKIE_NOME, usuario.nome);
    guardar(COOKIE_MODULOS, (usuario.modulos ?? []).join(","));
    guardar(COOKIE_SENHA_PADRAO, String(usuario.senhaPadrao));
  }, []);

  const limparSessao = useCallback(() => {
    setLoggedUser(null);
    COOKIES_SESSAO.forEach((nome) => deleteCookie(nome));
  }, []);

  const sair = useCallback(async () => {
    await LogoutService();
    limparSessao();
    if (typeof window !== "undefined") window.location.href = "/";
  }, [limparSessao]);

  // Restaura do cookie na montagem e confirma com o servidor logo em seguida.
  useEffect(() => {
    const codigo = ler(COOKIE_ID);
    const perfil = ler(COOKIE_PERFIL);

    if (codigo && perfil) {
      setLoggedUser({
        codigo,
        perfil,
        nome: ler(COOKIE_NOME) ?? "",
        email: "",
        senhaPadrao: ler(COOKIE_SENHA_PADRAO) === "true",
        modulos: (ler(COOKIE_MODULOS) ?? "").split(",").filter(Boolean),
      });
    }

    let ativo = true;
    void MyAccountService()
      .then((conta) => {
        if (!ativo) return;
        // `null` aqui é rede instável, não sessão inválida: o 401 já teria
        // levado para o login dentro do `api.ts`. Manter o que veio do cookie.
        if (conta) setCookieLoggedUser(conta);
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });

    return () => {
      ativo = false;
    };
  }, [setCookieLoggedUser]);

  // O `api.ts` dispara este evento ao receber 401. Sem limpar aqui, a tela de
  // login voltaria a "restaurar" um usuário que já não vale e mostraria o nome
  // de alguém que não está logado.
  useEffect(() => {
    const expirar = () => limparSessao();
    window.addEventListener("acervo:sessao-expirada", expirar);
    return () => window.removeEventListener("acervo:sessao-expirada", expirar);
  }, [limparSessao]);

  return (
    <ReactQueryClientProvider>
      <Context.Provider
        value={{ loggedUser, carregando, setCookieLoggedUser, limparSessao, sair }}
      >
        {children}
      </Context.Provider>
    </ReactQueryClientProvider>
  );
};

export const useUser = (): Sessao => {
  const context = useContext(Context);
  if (!context) throw new Error("useUser precisa estar dentro de <ContextWrapper>.");
  return context;
};
