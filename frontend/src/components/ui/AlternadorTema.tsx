"use client";

import { useEffect, useState } from "react";

type Tema = "light" | "dark";

function aplicar(tema: Tema) {
  document.documentElement.dataset.theme = tema;
  document.documentElement.style.colorScheme = tema;
}

export default function AlternadorTema() {
  const [tema, setTema] = useState<Tema>("dark");

  useEffect(() => {
    const atual = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTema(atual);
  }, []);

  function alternar() {
    const proximo: Tema = tema === "dark" ? "light" : "dark";
    setTema(proximo);
    aplicar(proximo);
    localStorage.setItem("tema", proximo);
  }

  return (
    <button
      type="button"
      onClick={alternar}
      className="fixed bottom-4 left-4 z-[70] flex items-center gap-2 rounded-pill border border-borda-forte bg-papel px-3 py-2 text-xs font-semibold text-tinta shadow-cartao-forte transition-colors hover:border-acao hover:bg-papel-3"
      aria-label={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
      title={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
    >
      <span aria-hidden>{tema === "dark" ? "☀" : "☾"}</span>
      {tema === "dark" ? "Tema claro" : "Tema escuro"}
    </button>
  );
}
