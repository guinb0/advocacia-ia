"use client";

import Keycloak from "keycloak-js";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { definirTokenAtual } from "./api";

/* Fluxo Authorization Code + PKCE (S256) pelo adaptador oficial. Ele cuida do
 * code_verifier, da troca do código por token e da renovação — código de
 * segurança que não vale reescrever à mão.
 *
 * Sem NEXT_PUBLIC_KEYCLOAK_URL o app roda aberto, espelhando o backend, que só
 * exige token quando KEYCLOAK_URL está definida. Assim `iniciar.ps1 -SemAuth`
 * desliga os dois lados de uma vez. */

const URL_KC = process.env.NEXT_PUBLIC_KEYCLOAK_URL ?? "";
const REALM = process.env.NEXT_PUBLIC_KEYCLOAK_REALM ?? "advocacia";
const CLIENT_ID = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "acervo-frontend";

export const AUTH_ATIVA = Boolean(URL_KC);

/** Renova quando faltar menos que isto para expirar (o token dura 30 min). */
const MARGEM_RENOVACAO_S = 60;

interface Sessao {
  carregando: boolean;
  autenticado: boolean;
  usuario: string;
  nome: string;
  papeis: string[];
  erro: string | null;
  entrar: () => void;
  sair: () => void;
}

const Contexto = createContext<Sessao | null>(null);

export function useSessao(): Sessao {
  const ctx = useContext(Contexto);
  if (!ctx) throw new Error("useSessao precisa estar dentro de <ProvedorAuth>.");
  return ctx;
}

export function ProvedorAuth({ children }: { children: ReactNode }) {
  const [carregando, setCarregando] = useState(AUTH_ATIVA);
  const [autenticado, setAutenticado] = useState(!AUTH_ATIVA);
  const [erro, setErro] = useState<string | null>(null);
  const [perfil, setPerfil] = useState({ usuario: "", nome: "", papeis: [] as string[] });
  const kcRef = useRef<Keycloak | null>(null);

  useEffect(() => {
    if (!AUTH_ATIVA) {
      definirTokenAtual(null);
      return;
    }
    // O React 18+ monta duas vezes em dev; sem esta guarda o adaptador é
    // inicializado em duplicidade e o segundo init derruba o primeiro.
    if (kcRef.current) return;

    const kc = new Keycloak({ url: URL_KC, realm: REALM, clientId: CLIENT_ID });
    kcRef.current = kc;

    kc.onTokenExpired = () => {
      void kc.updateToken(MARGEM_RENOVACAO_S).catch(() => {
        // Refresh token venceu: só resta reautenticar.
        definirTokenAtual(null);
        setAutenticado(false);
      });
    };
    kc.onAuthRefreshSuccess = () => definirTokenAtual(kc.token ?? null);

    kc.init({
      onLoad: "check-sso",
      pkceMethod: "S256",
      // O iframe de verificação de sessão é bloqueado por navegadores que cortam
      // cookies de terceiros e derruba a sessão sem motivo; a renovação por
      // refresh token acima já cobre a expiração.
      checkLoginIframe: false,
    })
      .then((ok) => {
        definirTokenAtual(ok ? (kc.token ?? null) : null);
        setAutenticado(ok);
        if (ok) {
          const claims = (kc.tokenParsed ?? {}) as {
            preferred_username?: string;
            name?: string;
            realm_access?: { roles?: string[] };
          };
          setPerfil({
            usuario: claims.preferred_username ?? "",
            nome: claims.name ?? claims.preferred_username ?? "",
            papeis: claims.realm_access?.roles ?? [],
          });
        }
      })
      .catch((e: unknown) => {
        setErro(
          e instanceof Error
            ? e.message
            : `Não foi possível falar com o Keycloak em ${URL_KC}.`,
        );
      })
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    const expirar = () => {
      definirTokenAtual(null);
      setAutenticado(false);
      setErro("Sua sessão expirou. Entre novamente para continuar.");
    };
    window.addEventListener("acervo:sessao-expirada", expirar);
    return () => window.removeEventListener("acervo:sessao-expirada", expirar);
  }, []);

  const entrar = useCallback(() => {
    void kcRef.current?.login({ redirectUri: window.location.origin + "/" });
  }, []);

  const sair = useCallback(() => {
    definirTokenAtual(null);
    void kcRef.current?.logout({ redirectUri: window.location.origin + "/" });
  }, []);

  return (
    <Contexto.Provider
      value={{
        carregando,
        autenticado,
        usuario: perfil.usuario,
        nome: perfil.nome,
        papeis: perfil.papeis,
        erro,
        entrar,
        sair,
      }}
    >
      {children}
    </Contexto.Provider>
  );
}
