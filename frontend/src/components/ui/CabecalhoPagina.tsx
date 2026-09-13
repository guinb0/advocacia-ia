import type { ReactNode } from "react";

/** Hierarquia comum aos módulos; ações e dados continuam com a tela. */
export default function CabecalhoPagina({
  titulo, descricao, contexto, acoes, children,
}: {
  titulo: string;
  descricao?: string;
  contexto?: string;
  acoes?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex min-w-0 flex-wrap items-start justify-between gap-4 border-b border-borda pb-6">
      <div className="min-w-0 flex-1 basis-[280px]">
        {contexto && <p className="mb-2 text-xs font-semibold text-tinta-3">{contexto}</p>}
        <h1 className="text-xl font-semibold tracking-[-0.025em] text-tinta [overflow-wrap:anywhere]">{titulo}</h1>
        {descricao && <p className="mt-2 max-w-[72ch] text-sm leading-relaxed text-tinta-2">{descricao}</p>}
        {children && <div className="mt-3 text-xs text-tinta-3">{children}</div>}
      </div>
      {acoes && <div className="flex flex-wrap items-center gap-2">{acoes}</div>}
    </header>
  );
}
