"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Tema = "light" | "dark";

function aplicar(tema: Tema) {
  document.documentElement.dataset.theme = tema;
  document.documentElement.style.colorScheme = tema;
}

export default function AlternadorTema({ flutuante = true }: { flutuante?: boolean }) {
  const [tema, setTema] = useState<Tema>("light");

  useEffect(() => {
    const atualizar = () => setTema(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    atualizar();
    window.addEventListener("forense:tema", atualizar);
    return () => window.removeEventListener("forense:tema", atualizar);
  }, []);

  function alternar() {
    const proximo: Tema = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTema(proximo);
    aplicar(proximo);
    window.dispatchEvent(new Event("forense:tema"));
    try { localStorage.setItem("tema", proximo); } catch { /* A troca funciona sem armazenamento. */ }
  }

  return (
    <button
      type="button"
      onClick={alternar}
      className={`flex min-h-10 min-w-10 items-center justify-center gap-2 rounded-campo border border-borda-forte bg-papel px-3 py-2 text-xs font-semibold text-tinta transition-colors hover:border-acao hover:bg-papel-3 ${flutuante ? "tema-flutuante fixed bottom-4 left-4 z-[70] shadow-cartao-forte" : "shrink-0"}`}
      aria-label={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
      title={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
    >
      {tema === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
      {flutuante && (tema === "dark" ? "Tema claro" : "Tema escuro")}
    </button>
  );
}
