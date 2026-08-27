"use client";

/* A navegação entre módulos, agora em coluna e em toda tela.
 *
 * POR QUE SAIU DO TOPO
 *
 * Eram onze módulos numa faixa horizontal com `flex-wrap`, e o resultado dependia
 * da largura da janela: em tela cheia cabia numa linha; num notebook quebrava em
 * duas e empurrava a "Mesa do dia" para baixo da dobra; num celular virava um
 * bloco de onze botões que ocupava a tela inteira antes de qualquer conteúdo.
 * Menu que muda de altura conforme a janela também muda o lugar de tudo que vem
 * depois — e o usuário perde a referência a cada redimensionamento.
 *
 * Em coluna, a lista cresce para baixo num espaço que é dela, e caber deixa de
 * ser função da largura.
 *
 * POR QUE ELA É GLOBAL E O MENU ANTIGO NÃO ERA
 *
 * A faixa vivia DENTRO da `Carteira`, então só existia lá: de qualquer outra tela
 * o caminho para um módulo era voltar para a carteira e sair de novo. A barra é
 * montada uma vez, em volta de todas as telas (ver `home.view.tsx`), e por isso
 * responde "onde eu estou" também nas telas que antes não tinham menu nenhum.
 *
 * NO CELULAR ELA SOME, E ISSO É O PONTO
 *
 * Abaixo de `lg` a coluna sairia de graça com metade da largura útil. Ali ela vira
 * gaveta: fechada por padrão, aberta pelo botão do topo, e fechando sozinha ao
 * navegar — quem tocou num módulo quer o módulo, não o menu ainda aberto por cima
 * dele.
 */

import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  ClipboardCheck,
  Database,
  FileSearch,
  FileText,
  FolderKanban,
  HeartPulse,
  LayoutDashboard,
  LibraryBig,
  LogOut,
  Menu,
  MessageSquareText,
  PenLine,
  Search,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { podeAbrirTela } from "@/app/home/home.model";
import type { Tela } from "@/app/home/home.model";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";

export interface ModuloNavegacao {
  tela: Tela;
  rotulo: string;
  /** Telas internas que devem acender o mesmo item de navegação. */
  relacionadas?: Tela[];
}

export interface GrupoNavegacao {
  titulo: string;
  itens: ModuloNavegacao[];
}

/* Os três grupos são os três trabalhos do escritório, e a ordem dentro deles é a
 * do dia: conduzir a entrevista é o que se faz toda manhã; abrir caso antigo é a
 * exceção. Era a mesma ordem da faixa horizontal — o que ela não tinha era o
 * rótulo do grupo, que numa lista vertical é o que impede onze itens de virarem
 * uma parede indistinta. */
export const GRUPOS_NAVEGACAO: GrupoNavegacao[] = [
  {
    titulo: "Atendimento",
    itens: [
      { tela: "entrevista", rotulo: "Entrevista guiada" },
      // O dossiê, o painel, a jurimetria e o checklist são leituras de UM caso.
      // Acendem a carteira para a barra não ficar sem resposta quando o advogado
      // está dentro de um caso.
      { tela: "carteira", rotulo: "Carteira", relacionadas: ["caso", "dossie", "painel", "jurimetria"] },
      // Fica em Atendimento, e não em Análise, porque a pergunta que ele responde é a de
      // ANTES de saber qual caso abrir — o vizinho certo dela é a carteira, não o painel
      // de dados.
      { tela: "agente", rotulo: "Agente" },
      { tela: "casos", rotulo: "Casos" },
      { tela: "documentacao", rotulo: "Documentação" },
    ],
  },
  {
    titulo: "Análise",
    itens: [
      { tela: "avulso", rotulo: "Ler um documento" },
      { tela: "investigacao", rotulo: "Investigar" },
      { tela: "dados", rotulo: "Dados" },
      { tela: "panorama", rotulo: "Panorama" },
    ],
  },
  {
    titulo: "Escritório",
    itens: [
      { tela: "supervisao", rotulo: "Supervisão" },
      // No grupo "Escritório", e não em "Atendimento": manter o catálogo é
      // trabalho de bastidor. Quem conduz entrevista já tem o botão de editar
      // dentro do roteiro; esta entrada é para quem vem consertar depois.
      { tela: "catalogoRoteiros", rotulo: "Roteiros" },
      { tela: "usuarios", rotulo: "Usuários" },
      { tela: "saudeAgente", rotulo: "Saúde do agente" },
      { tela: "modelosDePeticao", rotulo: "Modelos de petição" },
    ],
  },
];

const ITEM =
  "group relative flex w-full items-center gap-3 rounded-[10px] border border-transparent px-3 py-2.5 " +
  "text-left text-sm font-semibold text-[#c8d7e8] cursor-pointer transition-colors duration-[120ms] " +
  "hover:bg-white/[0.08] hover:text-white";
const ITEM_ATIVO =
  "relative flex w-full items-center gap-3 rounded-[10px] border border-white/10 bg-[#123d66] px-3 py-2.5 " +
  "text-left text-sm font-semibold text-white shadow-[inset_3px_0_0_var(--marca-ouro)] cursor-pointer";
const GRUPO_TITULO =
  "px-3 mt-5 mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-[#83a0bd] first:mt-0";

export const ICONE_POR_TELA: Partial<Record<Tela, LucideIcon>> = {
  entrevista: MessageSquareText,
  carteira: LayoutDashboard,
  agente: Bot,
  casos: BriefcaseBusiness,
  documentacao: LibraryBig,
  avulso: FileSearch,
  investigacao: Search,
  dados: Database,
  panorama: BarChart3,
  supervisao: Activity,
  catalogoRoteiros: BookOpen,
  usuarios: Users,
  saudeAgente: HeartPulse,
  modelosDePeticao: PenLine,
  caso: ClipboardCheck,
  dossie: FolderKanban,
  painel: BarChart3,
  jurimetria: FileText,
};

function ativa(modulo: ModuloNavegacao, tela: Tela): boolean {
  return modulo.tela === tela || (modulo.relacionadas?.includes(tela) ?? false);
}

function indiceDoModulo(item: ModuloNavegacao, modulos: string[]): number {
  const indice = modulos.findIndex((modulo) => podeAbrirTela(item.tela, [modulo]));
  return indice === -1 ? Number.MAX_SAFE_INTEGER : indice;
}

export function gruposPermitidos(modulos: string[]): GrupoNavegacao[] {
  return [...GRUPOS_NAVEGACAO]
    .map((grupo, indiceGrupo) => {
      const itens = grupo.itens
        .filter((item) => podeAbrirTela(item.tela, modulos))
        .sort((a, b) => indiceDoModulo(a, modulos) - indiceDoModulo(b, modulos));
      return { ...grupo, itens, indiceGrupo };
    })
    .filter((grupo) => grupo.itens.length > 0)
    .sort((a, b) => {
      const ordemA = Math.min(...a.itens.map((item) => indiceDoModulo(item, modulos)));
      const ordemB = Math.min(...b.itens.map((item) => indiceDoModulo(item, modulos)));
      return ordemA - ordemB || a.indiceGrupo - b.indiceGrupo;
    })
    .map(({ indiceGrupo: _indiceGrupo, ...grupo }) => grupo);
}

interface Props {
  tela: Tela;
  onNavegar: (tela: Tela) => void;
}

export default function BarraLateral({ tela, onNavegar }: Props) {
  const [aberta, setAberta] = useState(false);
  const sessao = useSessao();
  const modulos = sessao.carregando ? [] : sessao.modulos;
  const nome = sessao.nome || sessao.usuario || "Usuário";
  const perfil = sessao.papeis[0] || "Perfil ativo";

  // Esc fecha a gaveta. Sem isto, no celular, o único jeito de desistir do menu é
  // acertar o backdrop — e ele é justamente o que fica atrás do dedo.
  useEffect(() => {
    if (!aberta) return;
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAberta(false);
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberta]);

  // Gaveta aberta trava a rolagem do corpo: sem isso, arrastar sobre o backdrop
  // rola a página atrás e o usuário perde o lugar onde estava.
  useEffect(() => {
    if (!aberta) return;
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = anterior;
    };
  }, [aberta]);

  function navegar(destino: Tela) {
    onNavegar(destino);
    setAberta(false);
  }

  const lista = (
    <nav className="flex flex-col gap-[2px] px-3 pb-5 pt-2" aria-label="Módulos do sistema">
      {gruposPermitidos(modulos)
        .map((grupo) => {
          const itens = grupo.itens;
          if (itens.length === 0) return null;
          return (
            <div key={grupo.titulo}>
              <div className={GRUPO_TITULO}>{grupo.titulo}</div>
              {itens.map((item) => {
                const acesa = ativa(item, tela);
                const Icone = ICONE_POR_TELA[item.tela] ?? FileText;
                return (
                  <button
                    key={item.tela}
                    type="button"
                    className={acesa ? ITEM_ATIVO : ITEM}
                    aria-current={acesa ? "page" : undefined}
                    onClick={() => navegar(item.tela)}
                  >
                    <Icone
                      size={17}
                      className={acesa ? "shrink-0 text-[#f4c879]" : "shrink-0 text-[#8fb2d4] group-hover:text-white"}
                      aria-hidden
                    />
                    <span className="min-w-0 truncate">{item.rotulo}</span>
                  </button>
                );
              })}
            </div>
          );
        })}
    </nav>
  );

  return (
    <>
      {/* ------------------------------------------------- topo só do celular */}
      <div className="sticky top-0 z-30 flex h-[65px] shrink-0 items-center gap-3 border-b border-[#143a5d] bg-[#002a47] px-4 py-3 text-white shadow-[0_12px_30px_rgba(0,42,71,0.18)] lg:hidden">
        <button
          type="button"
          className="inline-flex min-h-10 min-w-10 cursor-pointer items-center justify-center rounded-[10px] border border-white/[0.16] bg-white/[0.08] text-white transition-colors hover:bg-white/[0.14]"
          aria-expanded={aberta}
          aria-controls="barra-lateral"
          aria-label={aberta ? "Fechar menu" : "Abrir menu"}
          onClick={() => setAberta((v) => !v)}
        >
          {aberta ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
        </button>
        <div className="min-w-0 flex-1">
          <span className="block truncate font-titulo text-lg font-bold leading-none">Acervo</span>
          <span className="mt-1 block truncate text-[11px] font-semibold uppercase tracking-[0.14em] text-[#b8d0e8]">
            Escritório jurídico
          </span>
        </div>
        <div className="ml-auto flex min-w-0 items-center gap-2">
          <span className="hidden min-w-0 text-right min-[430px]:block">
            <strong className="block max-w-[130px] truncate text-xs text-white">{nome}</strong>
            <span className="block max-w-[130px] truncate text-[11px] text-[#b8d0e8]">{perfil}</span>
          </span>
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.10] text-xs font-bold uppercase text-white ring-1 ring-white/[0.16]">
            {nome.slice(0, 2)}
          </span>
          {AUTH_ATIVA && (
            <button
              type="button"
              onClick={sessao.sair}
              className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-[10px] border border-white/[0.16] bg-white/[0.08] text-white transition-colors hover:bg-white/[0.14]"
              aria-label="Sair"
              title="Sair"
            >
              <LogOut size={17} aria-hidden />
            </button>
          )}
        </div>
      </div>

      {/* O fundo escuro só existe com a gaveta aberta, e só no celular. */}
      {aberta && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-tinta/40"
          aria-hidden
          onClick={() => setAberta(false)}
        />
      )}

      {/* --------------------------------------------------------- a coluna */}
      <aside
        id="barra-lateral"
        className={
          "border-[#143a5d] bg-[#002a47] " +
          // Celular: gaveta fixa que desliza. `translate-x` em vez de `display`
          // para a transição existir e para o conteúdo continuar no DOM — um menu
          // que some do DOM perde o foco do teclado no meio da navegação.
          "fixed inset-y-0 left-0 z-50 w-[264px] max-w-[82vw] overflow-y-auto border-r " +
          "transition-transform duration-200 ease-out " +
          (aberta ? "translate-x-0" : "-translate-x-full") +
          // Desktop: coluna do fluxo, sempre visível, acompanhando a rolagem.
          " lg:translate-x-0 lg:static lg:z-auto lg:h-dvh lg:w-full lg:max-w-none " +
          "lg:shrink-0"
        }
      >
        <div className="hidden px-5 pb-4 pt-5 lg:block">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-[12px] bg-white/[0.10] text-[#f4c879] ring-1 ring-white/[0.12]">
              <FileText size={20} aria-hidden />
            </span>
            <div className="min-w-0">
              <span className="block truncate font-titulo text-xl font-bold leading-none text-white">Acervo</span>
              <span className="mt-1 block truncate text-[11px] font-semibold uppercase tracking-[0.14em] text-[#9db8d2]">
                Escritório jurídico
              </span>
            </div>
          </div>
        </div>
        {lista}
      </aside>
    </>
  );
}
