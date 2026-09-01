"use client";

import type { ReactNode } from "react";
import { LogOut } from "lucide-react";

import type { Tela } from "@/app/home/home.model";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";

import BarraLateral from "./BarraLateral";

const ROTULO_TELA: Record<Tela, string> = {
  carteira: "Carteira",
  agente: "Agente",
  caso: "Checklist do caso",
  dossie: "Dossiê do caso",
  painel: "Painel analítico",
  jurimetria: "Jurimetria",
  casos: "Casos",
  avulso: "Ler documento",
  investigacao: "Investigação",
  usuarios: "Usuários",
  panorama: "Panorama",
  entrevista: "Entrevista guiada",
  supervisao: "Supervisão",
  dados: "Dados",
  saudeAgente: "Saúde do agente",
  modelosDePeticao: "Modelos de petição",
  catalogoRoteiros: "Roteiros",
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
    <div className="min-h-dvh bg-fundo lg:grid lg:h-dvh lg:min-h-0 lg:overflow-hidden lg:grid-cols-[236px_minmax(0,1fr)]">
      <BarraLateral tela={tela} onNavegar={onNavegar} />
      <main className="flex min-w-0 flex-col lg:min-h-0 lg:overflow-hidden">
        <div className="hidden shrink-0 border-b border-borda bg-papel/[0.88] px-6 py-3 shadow-[0_1px_0_rgba(16,32,51,0.03)] backdrop-blur lg:block">
          <div className="mx-auto flex max-w-[1440px] min-w-0 items-center justify-between gap-6">
            <div className="min-w-0">
              <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
                Área atual
              </span>
              <strong className="mt-0.5 block truncate text-sm text-tinta">{ROTULO_TELA[tela]}</strong>
            </div>
            <div className="flex min-w-0 shrink-0 items-center gap-3">
              <span className="hidden h-8 w-px bg-borda sm:block" aria-hidden />
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-acao-clara text-xs font-bold uppercase text-acao ring-1 ring-acao-borda">
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
                  className="inline-flex min-h-9 items-center justify-center gap-2 rounded-[10px] border border-borda-campo bg-papel px-3 text-sm font-semibold text-acao transition-colors hover:border-acao hover:bg-acao-clara"
                >
                  <LogOut size={16} aria-hidden />
                  Sair
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="min-w-0 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overflow-x-hidden">
          <div className="mx-auto w-full max-w-[1440px] min-w-0 px-4 pb-16 pt-5 sm:px-6 lg:px-7 [&>*]:min-w-0">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
