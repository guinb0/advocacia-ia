"use client";

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
  usuarios: "Usuários",
  panorama: "Panorama",
  entrevista: "Entrevista guiada",
  supervisao: "Supervisão",
  dados: "Dados",
  modelosDePeticao: "Identidade visual",
  catalogoRoteiros: "Roteiros",
  documentacao: "Documentação",
};

const DESCRICAO_TELA: Record<Tela, string> = {
  carteira: "Prioridades, pendências e próximos passos do escritório.",
  caso: "Documentos, validações e andamento deste atendimento.",
  dossie: "Visão consolidada dos fatos e materiais do caso.",
  painel: "Indicadores e qualidade da análise documental.",
  jurimetria: "Precedentes e padrões úteis para a estratégia.",
  casos: "Crie, localize e organize os casos do escritório.",
  avulso: "Extraia e confira dados de um documento isolado.",
  usuarios: "Pessoas, perfis e permissões de acesso.",
  panorama: "Leitura geral da operação e dos atendimentos.",
  entrevista: "Conduza a conversa com roteiro e registro assistido.",
  supervisao: "Acompanhe atendimentos e pontos que exigem atenção.",
  dados: "Consulte as informações estruturadas do acervo.",
  modelosDePeticao: "Padronize a apresentação dos documentos jurídicos.",
  catalogoRoteiros: "Organize as perguntas usadas nos atendimentos.",
  documentacao: "Acompanhe pedidos, arquivos e entregas documentais.",
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
    <div className="min-h-dvh bg-transparent lg:grid lg:h-dvh lg:min-h-0 lg:overflow-hidden lg:grid-cols-[252px_minmax(0,1fr)]">
      <BarraLateral tela={tela} onNavegar={onNavegar} />
      <main className="flex min-w-0 flex-col lg:min-h-0 lg:overflow-hidden">
        <div className="hidden shrink-0 border-b border-borda bg-papel/[0.82] px-7 py-3.5 shadow-[0_1px_0_rgba(16,32,51,0.03)] backdrop-blur-xl lg:block">
          <div className="mx-auto flex max-w-[1440px] min-w-0 items-center justify-between gap-8">
            <div className="min-w-0">
              <div className="flex min-w-0 items-baseline gap-3">
                <h1 className="truncate font-titulo text-[1.35rem] font-semibold tracking-[-0.02em] text-tinta">
                  {ROTULO_TELA[tela]}
                </h1>
                <span className="hidden truncate text-xs text-tinta-3 xl:block">{DESCRICAO_TELA[tela]}</span>
              </div>
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
          <div className="mx-auto w-full max-w-[1440px] min-w-0 px-4 pb-20 pt-5 sm:px-6 sm:pt-7 lg:px-8 lg:pt-8 [&>*]:min-w-0">
            {tela !== "carteira" && (
              <nav className="mb-5 flex min-w-0 items-center gap-2" aria-label="Navegação de retorno">
                <button
                  type="button"
                  onClick={() => onNavegar("carteira")}
                  className="group inline-flex min-h-10 items-center gap-2 rounded-campo border border-borda-forte bg-papel/90 px-3.5 text-sm font-semibold text-tinta shadow-cartao transition hover:border-acao hover:bg-acao-clara hover:text-acao focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-acao"
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
