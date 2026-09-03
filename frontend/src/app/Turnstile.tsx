"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

type TurnstileApi = {
  render: (elemento: HTMLElement, opcoes: Record<string, unknown>) => string;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

export default function Turnstile({ onToken }: { onToken: (token: string) => void }) {
  const recipiente = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const [scriptPronto, setScriptPronto] = useState(false);

  const renderizar = useCallback(() => {
    if (!SITE_KEY || !recipiente.current || !window.turnstile || widget.current) return;
    widget.current = window.turnstile.render(recipiente.current, {
      sitekey: SITE_KEY,
      action: "login",
      theme: "dark",
      size: "flexible",
      appearance: "interaction-only",
      callback: (token: string) => onToken(token),
      "expired-callback": () => onToken(""),
      "error-callback": () => onToken(""),
    });
  }, [onToken]);

  useEffect(() => {
    if (scriptPronto) renderizar();
    return () => {
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current);
      widget.current = null;
    };
  }, [renderizar, scriptPronto]);

  if (!SITE_KEY) return null;

  return (
    <div className="min-h-[65px] overflow-hidden rounded-xl" aria-label="Verificação de segurança">
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        strategy="afterInteractive"
        onLoad={() => setScriptPronto(true)}
        onReady={() => setScriptPronto(true)}
      />
      <div ref={recipiente} className="w-full" />
    </div>
  );
}
