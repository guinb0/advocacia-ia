"use client";

import AlternadorTema from "@/components/ui/AlternadorTema";

import type { ReactNode } from "react";
import { ArrowLeft, LogOut } from "lucide-react";

import type { Tela } from "@/app/home/home.model";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";

import BarraLateral from "./BarraLateral";

const ROTULO_TELA: Record<Tela, string> = {
  carteira: "Carteira",
  caso: "Checklist do caso",
  dossie: "Dossiê do caso",
  painel: "Painel analítico",
  jurimetria: "Jurimetria",
  casos: "Casos",
  avulso: "Ler documento",
  investigacao: "Investigação",
  usuarios: "Administração",
  panorama: "Panorama",
  operacao: "Operação",
  entrevista: "Entrevista guiada",
  supervisao: "Supervisão",
  dados: "Dados",
  saudeAgente: "Saúde do agente",
  modelosDePeticao: "Modelos de petição",
  configuracaoAssinatura: "Assinatura eletrônica",
  catalogoRoteiros: "Roteiros",
  glossarioDocumentos: "Glossário de documentos",
  revisao: "Revisão do roteiro",
  followup: "Follow-up",
  documentacao: "Documentação",
};

interface AppShellProps {
  tela: Tela;
  onNavegar: (tela: Tela) => void;
  children: ReactNode;
}

export default function AppShell({ tela, onNavegar, children }: AppShellProps) {
  const sessao = useSessao();
  const nome = sessao.nome || sessao.usuario || "Usuário";
  const perfil = sessao.papeis[0] || "Perfil ativo";

  return (
    /* Contenção de altura só no layout de painel (lg+): ali a barra lateral é
     * coluna de grade e o conteúdo rola numa área própria de `h-dvh`. Abaixo de
     * `lg` NÃO há esse layout — `h-dvh`+`overflow-hidden` aqui deixava o `<main>`
     * sem altura delimitada, o scroll interno não pegava e a topbar `sticky` não
     * grudava. No celular o fluxo é o do documento: a página rola pelo `<body>`
     * (que já tem `overflow-x:hidden` e `max-width:100vw` em globals.css, o que
     * mata a rolagem horizontal), e a topbar `sticky top-0` gruda de verdade. */
    <div className="app-shell min-h-dvh bg-fundo lg:grid lg:h-dvh lg:min-h-0 lg:overflow-hidden lg:grid-cols-[248px_minmax(0,1fr)]">
      <a href="#conteudo-principal" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[80] focus:rounded-campo focus:bg-papel focus:p-3 focus:text-tinta">Ir para o conteúdo</a>
      <BarraLateral tela={tela} onNavegar={onNavegar} />
      <main id="conteudo-principal" tabIndex={-1} className="flex min-w-0 flex-col lg:min-h-0 lg:overflow-hidden">
        {/* Barra de localização, não de título. O título da tela é o `h1` que
          * cada módulo renderiza (quase sempre via `CabecalhoPagina`); repetir
          * o mesmo nome aqui em 1.35rem dava três camadas dizendo "Casos" —
          * topo, migalha e `h1` — e empurrava o conteúdo para baixo sem
          * informar nada. Aqui fica só onde o operador está e como voltar. */}
        <div className="hidden shrink-0 border-b border-borda bg-papel/[0.82] px-7 py-3 shadow-[0_1px_0_rgba(16,32,51,0.03)] backdrop-blur-xl lg:block">
          <div className="mx-auto flex max-w-[1440px] min-w-0 items-center justify-between gap-8">
            <nav className="flex min-w-0 items-center gap-3" aria-label="Localização e retorno">
              {tela !== "carteira" && (
                <button
                  type="button"
                  onClick={() => onNavegar("carteira")}
                  className="group inline-flex min-h-9 shrink-0 items-center gap-2 rounded-campo border border-borda-campo bg-papel px-3 text-sm font-semibold text-acao-texto transition-colors hover:border-acao hover:bg-acao-clara focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foco"
                  aria-label={`Voltar de ${ROTULO_TELA[tela]} para a Carteira`}
                >
                  <ArrowLeft size={16} className="transition-transform group-hover:-translate-x-0.5" aria-hidden />
                  <span>Voltar</span>
                </button>
              )}
              <p className="m-0 min-w-0 truncate text-sm text-tinta-3">
                {tela !== "carteira" && (
                  <>
                    <span>Carteira</span>
                    <span className="px-1.5" aria-hidden>›</span>
                  </>
                )}
                <span className="font-semibold text-tinta">{ROTULO_TELA[tela]}</span>
              </p>
            </nav>
            <div className="flex min-w-0 shrink-0 items-center gap-3">
              <AlternadorTema flutuante={false} />
              <span className="hidden h-8 w-px bg-borda sm:block" aria-hidden />
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-acao-clara text-xs font-bold uppercase text-acao-texto ring-1 ring-acao-borda">
                {nome.slice(0, 2)}
              </span>
              <span className="min-w-0 text-right">
                <strong className="block max-w-[220px] truncate text-sm text-tinta">{nome}</strong>
                <span className="block max-w-[220px] truncate text-xs text-tinta-3">{perfil}</span>
              </span>
              {AUTH_ATIVA && (
                <button
                  type="button"
                  onClick={sessao.sair}
                  className="inline-flex min-h-9 items-center justify-center gap-2 rounded-[10px] border border-borda-campo bg-papel px-3 text-sm font-semibold text-acao-texto transition-colors hover:border-acao hover:bg-acao-clara"
                >
                  <LogOut size={16} aria-hidden />
                  Sair
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="min-w-0 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overflow-x-hidden">
          <div className="mx-auto w-full max-w-[1440px] min-w-0 px-4 pb-20 pt-5 sm:px-6 sm:pt-7 lg:px-8 lg:pt-8 [&>*]:min-w-0">
            {tela !== "carteira" && (
              <nav className="mb-5 flex min-w-0 items-center gap-2 lg:hidden" aria-label="Navegação de retorno">
                <button
                  type="button"
                  onClick={() => onNavegar("carteira")}
                  className="group inline-flex min-h-10 items-center gap-2 rounded-campo border border-borda-forte bg-papel/90 px-3.5 text-sm font-semibold text-tinta shadow-cartao transition hover:border-acao hover:bg-acao-clara hover:text-acao-texto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-acao"
                  aria-label={`Voltar de ${ROTULO_TELA[tela]} para a Carteira`}
                >
                  <ArrowLeft size={18} className="transition-transform group-hover:-translate-x-0.5" aria-hidden />
                  <span>Voltar</span>
                </button>
                <span className="min-w-0 truncate text-xs text-tinta-3" aria-hidden="true">
                  Carteira <span className="px-1.5">›</span> {ROTULO_TELA[tela]}
                </span>
              </nav>
            )}
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
