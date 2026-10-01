"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Tema = "light" | "dark";

function lido(): Tema {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function aplicar(tema: Tema) {
  document.documentElement.dataset.theme = tema;
  document.documentElement.style.colorScheme = tema;
}

const ESTILO = {
  /* Só nas telas sem barra do escritório (login, portal, chamada): dentro dela o
   * canto inferior esquerdo é a própria barra lateral, e o botão cobria os itens. */
  flutuante:
    "fixed bottom-4 left-4 z-[70] flex items-center gap-2 rounded-pill border border-borda-forte bg-papel px-3 py-2 text-xs font-semibold text-tinta shadow-cartao-forte transition-colors hover:border-acao hover:bg-papel-3 [body:has(.app-shell)_&]:hidden",
  topo:
    "inline-flex min-h-9 items-center justify-center gap-2 rounded-[10px] border border-borda-campo bg-papel px-3 text-sm font-semibold text-tinta-2 transition-colors hover:border-acao hover:bg-acao-clara hover:text-acao",
  celular:
    "inline-flex min-h-9 min-w-9 items-center justify-center rounded-[10px] border border-white/[0.16] bg-white/[0.08] text-nav-texto transition-colors hover:bg-white/[0.14]",
} as const;

export default function AlternadorTema({ variante = "flutuante" }: { variante?: keyof typeof ESTILO }) {
  const [tema, setTema] = useState<Tema>("dark");

  /* Há mais de um botão na tela (topo do computador e do celular): todos
   * acompanham o atributo do <html>, não só o que foi clicado. */
  useEffect(() => {
    setTema(lido());
    const observador = new MutationObserver(() => setTema(lido()));
    observador.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observador.disconnect();
  }, []);

  function alternar() {
    const proximo: Tema = tema === "dark" ? "light" : "dark";
    aplicar(proximo);
    localStorage.setItem("tema", proximo);
  }

  const rotulo = tema === "dark" ? "Usar tema claro" : "Usar tema escuro";
  const Icone = tema === "dark" ? Sun : Moon;

  return (
    <button type="button" onClick={alternar} className={ESTILO[variante]} aria-label={rotulo} title={rotulo}>
      <Icone size={variante === "celular" ? 17 : 15} aria-hidden />
      {variante !== "celular" && (tema === "dark" ? "Tema claro" : "Tema escuro")}
    </button>
  );
}
