"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * O widget do Cloudflare Turnstile na tela de login.
 *
 * POR QUE RENDERIZAÇÃO EXPLÍCITA, E NÃO O `class="cf-turnstile"` AUTOMÁTICO
 *
 * O modo automático varre o HTML depois que o script carrega e desenha o que
 * encontrar. Isso não sobrevive ao React: o formulário é montado e desmontado
 * pelo roteador, e o widget automático ou some ou aparece duplicado quando a
 * página remonta. Com `render()` explícito, quem controla o ciclo de vida é este
 * componente — e o `remove()` na limpeza garante que não fique um widget órfão
 * apontando para um `<div>` que já saiu do DOM.
 *
 * O TOKEN VALE UMA VEZ SÓ, E É POR ISSO QUE EXISTE O `reset`
 *
 * A Cloudflare recusa um token já usado com `timeout-or-duplicate`. Sem resetar,
 * a pessoa que erra a senha uma vez fica presa: a segunda tentativa manda o
 * mesmo token, o servidor recusa por causa do captcha, e a tela passa a acusar
 * um problema de segurança em quem só digitou a senha errada. Quem chama pega o
 * `reset` por `aoPronto` e o dispara depois de cada falha.
 */

type Turnstile = {
  render: (
    elemento: HTMLElement,
    opcoes: {
      sitekey: string;
      callback: (token: string) => void;
      "error-callback"?: () => void;
      "expired-callback"?: () => void;
      theme?: "auto" | "light" | "dark";
      language?: string;
      appearance?: "always" | "execute" | "interaction-only";
    },
  ) => string;
  reset: (id?: string) => void;
  remove: (id?: string) => void;
};

declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const SCRIPT_ID = "cf-turnstile-script";

/** Carrega o script uma vez só, mesmo com dois componentes pedindo ao mesmo tempo.
 *
 * A promessa fica guardada no módulo em vez de num estado do React: dois
 * montagens em sequência (o Strict Mode do desenvolvimento faz exatamente isso)
 * pediriam duas tags `<script>` para o mesmo arquivo, e a segunda redefiniria o
 * `window.turnstile` no meio do uso da primeira. */
let carregamento: Promise<void> | null = null;

function carregarScript(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.turnstile) return Promise.resolve();
  if (carregamento) return carregamento;

  carregamento = new Promise<void>((resolver, rejeitar) => {
    const existente = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    const script = existente ?? document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = SCRIPT_URL;
    script.async = true;
    script.defer = true;
    script.addEventListener("load", () => resolver());
    script.addEventListener("error", () => {
      /* Zera para uma próxima montagem poder tentar de novo — rede que cai por
       * um instante não pode deixar o login sem captcha para sempre. */
      carregamento = null;
      rejeitar(new Error("Não foi possível carregar a verificação de segurança."));
    });
    if (!existente) document.head.appendChild(script);
  });

  return carregamento;
}

export default function TurnstileWidget({
  siteKey,
  aoResolver,
  aoExpirar,
  aoPronto,
}: {
  siteKey: string;
  /** Chamado com o token que acompanha o login. */
  aoResolver: (token: string) => void;
  /** Token vencido ou erro do widget: quem chama limpa o token que guardou. */
  aoExpirar: () => void;
  /** Entrega o `reset` para quem chama disparar depois de uma tentativa falha. */
  aoPronto?: (reset: () => void) => void;
}) {
  const caixa = useRef<HTMLDivElement | null>(null);
  const widgetId = useRef<string | null>(null);

  /* Os callbacks entram em `ref` porque o widget é desenhado UMA vez e guarda as
   * funções que recebeu. Se eles entrassem nas dependências do efeito, cada
   * re-render do formulário (a cada tecla digitada) destruiria e redesenharia o
   * captcha — e o desafio recomeçaria do zero no meio da digitação. */
  const resolverRef = useRef(aoResolver);
  const expirarRef = useRef(aoExpirar);
  resolverRef.current = aoResolver;
  expirarRef.current = aoExpirar;

  const reiniciar = useCallback(() => {
    if (widgetId.current && window.turnstile) window.turnstile.reset(widgetId.current);
  }, []);

  useEffect(() => {
    let cancelado = false;

    carregarScript()
      .then(() => {
        if (cancelado || !caixa.current || !window.turnstile) return;
        if (widgetId.current) return;

        widgetId.current = window.turnstile.render(caixa.current, {
          sitekey: siteKey,
          theme: "auto",
          language: "pt-br",
          callback: (token) => resolverRef.current(token),
          "error-callback": () => expirarRef.current(),
          "expired-callback": () => expirarRef.current(),
        });
        aoPronto?.(reiniciar);
      })
      .catch(() => {
        /* Script bloqueado (rede corporativa, extensão de privacidade) ou fora do
         * ar. A tela não trava por isso: o backend decide, e com
         * `TURNSTILE_FALHA_ABERTA=1` a tentativa segue sem o token. Um alerta
         * vermelho aqui assustaria quem não pode fazer nada a respeito. */
        expirarRef.current();
      });

    return () => {
      cancelado = true;
      if (widgetId.current && window.turnstile) {
        window.turnstile.remove(widgetId.current);
        widgetId.current = null;
      }
    };
    // `aoPronto` e `reiniciar` são estáveis; `siteKey` vem do servidor e não muda
    // durante a sessão da página.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteKey]);

  return <div ref={caixa} className="flex justify-center" aria-live="polite" />;
}
