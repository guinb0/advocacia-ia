"use client";

import { BarChart3, ClipboardCheck, FileText, Scale } from "lucide-react";

import type { Tela } from "@/app/home/home.model";

const ABAS: Array<{
  tela: Extract<Tela, "caso" | "dossie" | "painel" | "jurimetria">;
  titulo: string;
  apoio: string;
  Icone: typeof ClipboardCheck;
}> = [
  {
    tela: "caso",
    titulo: "Checklist",
    apoio: "Documentos",
    Icone: ClipboardCheck,
  },
  {
    tela: "dossie",
    titulo: "Dossiê",
    apoio: "Fatos e peças",
    Icone: FileText,
  },
  {
    tela: "painel",
    titulo: "Painel",
    apoio: "Andamento",
    Icone: BarChart3,
  },
  {
    tela: "jurimetria",
    titulo: "Jurimetria",
    apoio: "Acervo",
    Icone: Scale,
  },
];

interface CasoWorkspaceTabsProps {
  tela: Tela;
  onNavegar: (tela: Tela) => void;
  cliente?: string;
  categoria?: string;
}

export default function CasoWorkspaceTabs({
  tela,
  onNavegar,
  cliente,
  categoria,
}: CasoWorkspaceTabsProps) {
  return (
    <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
      <div className="flex min-w-0 flex-col gap-3 border-b border-borda bg-papel-2 px-4 py-4 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
            Caso aberto
          </span>
          <h1 className="mt-1 truncate text-xl font-semibold leading-[1.15] text-tinta">
            {cliente || "Checklist do caso"}
          </h1>
          {categoria && (
            <p className="mt-1 truncate text-sm text-tinta-2" title={categoria}>
              {categoria}
            </p>
          )}
        </div>
      </div>

      <div
        className="flex gap-2 overflow-x-auto px-3 py-3 sm:px-4"
        role="tablist"
        aria-label="Áreas do caso"
      >
        {ABAS.map(({ tela: destino, titulo, apoio, Icone }) => {
          const ativa = tela === destino;
          return (
            <button
              key={destino}
              type="button"
              role="tab"
              aria-selected={ativa}
              onClick={() => onNavegar(destino)}
              className={[
                "flex min-w-[156px] items-center gap-3 rounded-campo border px-3 py-2 text-left transition-colors",
                ativa
                  ? "border-acao-borda bg-acao-clara text-acao"
                  : "border-transparent bg-transparent text-tinta-2 hover:border-borda hover:bg-papel-2 hover:text-tinta",
              ].join(" ")}
            >
              <span
                className={[
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border",
                  ativa
                    ? "border-acao-borda bg-papel text-acao"
                    : "border-borda bg-papel-2 text-tinta-3",
                ].join(" ")}
              >
                <Icone size={17} aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">{titulo}</span>
                <span className="block truncate text-xs opacity-75">{apoio}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
