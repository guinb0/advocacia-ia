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

import { podeAbrirTela } from "@/app/home/home.model";
import type { Tela } from "@/app/home/home.model";
import { useSessao } from "@/lib/auth";

interface Modulo {
  tela: Tela;
  rotulo: string;
  /** Telas que são FILHAS deste módulo e devem acender o mesmo item. */
  filhas?: Tela[];
}

interface Grupo {
  titulo: string;
  itens: Modulo[];
}

/* Os três grupos são os três trabalhos do escritório, e a ordem dentro deles é a
 * do dia: conduzir a entrevista é o que se faz toda manhã; abrir caso antigo é a
 * exceção. Era a mesma ordem da faixa horizontal — o que ela não tinha era o
 * rótulo do grupo, que numa lista vertical é o que impede onze itens de virarem
 * uma parede indistinta. */
const GRUPOS: Grupo[] = [
  {
    titulo: "Atendimento",
    itens: [
      { tela: "entrevista", rotulo: "Entrevista guiada" },
      // O dossiê, o painel, a jurimetria e o checklist são leituras de UM caso —
      // não são módulos, e sim onde a carteira leva. Acendem a carteira para a
      // barra não ficar sem resposta quando o advogado está dentro de um caso.
      { tela: "carteira", rotulo: "Carteira", filhas: ["caso", "dossie", "painel", "jurimetria"] },
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
  "block w-full text-left px-3 py-[7px] rounded-campo border border-transparent bg-transparent " +
  "text-tinta-2 text-sm font-semibold cursor-pointer transition-colors duration-[120ms] " +
  "hover:bg-papel-3 hover:text-tinta";
const ITEM_ATIVO =
  "block w-full text-left px-3 py-[7px] rounded-campo border border-acao-borda bg-acao-clara " +
  "text-acao text-sm font-semibold cursor-pointer";
const GRUPO_TITULO =
  "px-3 mt-4 mb-1 text-tinta-3 text-xs font-bold uppercase tracking-[0.08em] first:mt-0";

function ativa(modulo: Modulo, tela: Tela): boolean {
  return modulo.tela === tela || (modulo.filhas?.includes(tela) ?? false);
}

function indiceDoModulo(item: Modulo, modulos: string[]): number {
  const indice = modulos.findIndex((modulo) => podeAbrirTela(item.tela, [modulo]));
  return indice === -1 ? Number.MAX_SAFE_INTEGER : indice;
}

interface Props {
  tela: Tela;
  onNavegar: (tela: Tela) => void;
}

export default function BarraLateral({ tela, onNavegar }: Props) {
  const [aberta, setAberta] = useState(false);
  const sessao = useSessao();
  const modulos = sessao.carregando ? [] : sessao.modulos;

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
    <nav className="flex flex-col gap-[2px] p-3" aria-label="Módulos do sistema">
      {[...GRUPOS]
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
        .map((grupo) => {
          const itens = grupo.itens;
          if (itens.length === 0) return null;
          return (
            <div key={grupo.titulo}>
              <div className={GRUPO_TITULO}>{grupo.titulo}</div>
              {itens.map((item) => {
                const acesa = ativa(item, tela);
                return (
                  <button
                    key={item.tela}
                    type="button"
                    className={acesa ? ITEM_ATIVO : ITEM}
                    aria-current={acesa ? "page" : undefined}
                    onClick={() => navegar(item.tela)}
                  >
                    {item.rotulo}
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
      <div className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-2 border-b border-borda bg-papel">
        <button
          type="button"
          className="inline-flex items-center justify-center min-h-10 min-w-10 rounded-campo border border-borda-campo bg-papel text-tinta cursor-pointer hover:bg-papel-3"
          aria-expanded={aberta}
          aria-controls="barra-lateral"
          aria-label={aberta ? "Fechar menu" : "Abrir menu"}
          onClick={() => setAberta((v) => !v)}
        >
          {/* Três traços desenhados, não caractere: "☰" muda de largura e de
            * altura conforme a fonte instalada, e no Windows saía desalinhado. */}
          <svg viewBox="0 0 20 20" className="w-5 h-5" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            {aberta ? (
              <>
                <path d="M5 5l10 10" />
                <path d="M15 5L5 15" />
              </>
            ) : (
              <>
                <path d="M3 6h14" />
                <path d="M3 10h14" />
                <path d="M3 14h14" />
              </>
            )}
          </svg>
        </button>
        <span className="text-tinta font-titulo text-md font-bold tracking-[-0.01em]">Acervo</span>
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
          "bg-papel border-borda " +
          // Celular: gaveta fixa que desliza. `translate-x` em vez de `display`
          // para a transição existir e para o conteúdo continuar no DOM — um menu
          // que some do DOM perde o foco do teclado no meio da navegação.
          "fixed inset-y-0 left-0 z-50 w-[264px] max-w-[82vw] overflow-y-auto border-r " +
          "transition-transform duration-200 ease-out " +
          (aberta ? "translate-x-0" : "-translate-x-full") +
          // Desktop: coluna do fluxo, sempre visível, acompanhando a rolagem.
          " lg:translate-x-0 lg:static lg:z-auto lg:w-[236px] lg:max-w-none lg:shrink-0 " +
          "lg:h-screen lg:sticky lg:top-0"
        }
      >
        <div className="hidden lg:block px-6 pt-5 pb-1">
          <span className="text-tinta font-titulo text-lg font-bold tracking-[-0.01em]">Acervo</span>
        </div>
        {lista}
      </aside>
    </>
  );
}
