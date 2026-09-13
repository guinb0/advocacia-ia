"use client";

import AlternadorTema from "@/components/ui/AlternadorTema";

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

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  BriefcaseBusiness,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileCheck2,
  FileSearch,
  FileSignature,
  FileText,
  FolderKanban,
  LayoutDashboard,
  LibraryBig,
  LogOut,
  Menu,
  MessageSquareText,
  PenLine,
  PhoneCall,
  Search,
  Tags,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { podeAbrirTela } from "@/app/home/home.model";
import type { Tela } from "@/app/home/home.model";
import { useFocoContido } from "@/lib/foco";
import MarcaForense from "@/components/ui/MarcaForense";
import { AUTH_ATIVA, useSessao } from "@/lib/auth";

export interface ModuloNavegacao {
  tela: Tela;
  rotulo: string;
  /** Telas internas que devem acender o mesmo item de navegação. */
  relacionadas?: Tela[];
  /* Telas que só existem DENTRO deste item — ver o comentário do grupo
   * "Escritório" sobre a Administração. Quando há subitens, o item vira
   * expansível: a lista só ocupa espaço na coluna de quem a abriu. */
  subitens?: ModuloNavegacao[];
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
  { titulo: "Visão geral", itens: [{ tela: "carteira", rotulo: "Mesa do dia" }] },
  { titulo: "Atendimento", itens: [
    { tela: "entrevista", rotulo: "Entrevista guiada" },
    { tela: "followup", rotulo: "Acompanhamento" },
  ] },
  { titulo: "Jurídico", itens: [
    { tela: "casos", rotulo: "Casos e clientes", relacionadas: ["caso", "dossie", "painel", "jurimetria"] },
    { tela: "documentacao", rotulo: "Documentos" },
    { tela: "modelosDePeticao", rotulo: "Modelos de petição" },
    { tela: "revisao", rotulo: "Revisão de petições" },
  ] },
  { titulo: "Inteligência", itens: [
    { tela: "avulso", rotulo: "Leitura de documentos" },
    { tela: "investigacao", rotulo: "Investigação" },
    { tela: "dados", rotulo: "Dados" },
    { tela: "panorama", rotulo: "Panorama" },
  ] },
  { titulo: "Gestão", itens: [
    { tela: "operacao", rotulo: "Operação" },
    { tela: "supervisao", rotulo: "Supervisão" },
  ] },
  { titulo: "Sistema", itens: [
    { tela: "catalogoRoteiros", rotulo: "Roteiros" },
    { tela: "glossarioDocumentos", rotulo: "Glossário de documentos" },
    { tela: "usuarios", rotulo: "Administração", subitens: [
      { tela: "configuracaoAssinatura", rotulo: "Assinatura" },
    ] },
    { tela: "saudeAgente", rotulo: "Saúde do agente" },
  ] },
];

const ITEM =
  "group relative flex w-full items-center gap-3 rounded-campo border border-transparent px-3 py-2.5 " +
  "text-left text-sm font-semibold text-nav-texto-2 cursor-pointer transition-colors duration-[120ms] " +
  "hover:bg-nav-fundo-hover hover:text-nav-texto";
const ITEM_ATIVO =
  "relative flex w-full items-center gap-3 rounded-[10px] border border-white/10 bg-nav-fundo-ativo px-3 py-2.5 " +
  "text-left text-sm font-semibold text-nav-texto shadow-[inset_3px_0_0_var(--marca-ouro)] cursor-pointer";
/* O subitem é o mesmo item, recuado e menor: recuo e traço à esquerda dizem
 * "isto pertence ao de cima" sem repetir o nome do pai em cada linha. */
const SUBITEM =
  "group relative flex w-full items-center gap-2.5 rounded-[10px] border border-transparent py-2 pl-9 pr-3 " +
  "text-left text-[13px] font-semibold text-nav-texto-3 cursor-pointer transition-colors duration-[120ms] " +
  "hover:bg-nav-fundo-hover hover:text-nav-texto";
const SUBITEM_ATIVO =
  "relative flex w-full items-center gap-2.5 rounded-[10px] border border-white/10 bg-nav-fundo-ativo py-2 pl-9 pr-3 " +
  "text-left text-[13px] font-semibold text-nav-texto cursor-pointer";
const GRUPO_TITULO =
  "px-3 mt-5 mb-2 text-xs font-semibold tracking-[0.04em] text-nav-texto-3 first:mt-0";

export const ICONE_POR_TELA: Partial<Record<Tela, LucideIcon>> = {
  entrevista: MessageSquareText,
  carteira: LayoutDashboard,
  casos: BriefcaseBusiness,
  documentacao: LibraryBig,
  avulso: FileSearch,
  dados: Database,
  panorama: BarChart3,
  operacao: Activity,
  supervisao: Activity,
  revisao: FileCheck2,
  followup: PhoneCall,
  catalogoRoteiros: BookOpen,
  glossarioDocumentos: Tags,
  usuarios: Users,
  modelosDePeticao: PenLine,
  configuracaoAssinatura: FileSignature,
  caso: ClipboardCheck,
  dossie: FolderKanban,
  painel: BarChart3,
  jurimetria: FileText,
};

function ativa(modulo: ModuloNavegacao, tela: Tela): boolean {
  return modulo.tela === tela || (modulo.relacionadas?.includes(tela) ?? false);
}

/** O item está aceso porque um FILHO dele é a tela atual? Se sim, já abre expandido. */
export function filhoAtivo(item: ModuloNavegacao, tela: Tela): boolean {
  return (item.subitens ?? []).some((sub) => ativa(sub, tela));
}

function indiceDoModulo(item: ModuloNavegacao, modulos: string[]): number {
  const indice = modulos.findIndex((modulo) => podeAbrirTela(item.tela, [modulo]));
  const proprio = indice === -1 ? Number.MAX_SAFE_INTEGER : indice;
  /* Um pai que a pessoa não pode abrir mas cujo filho ela pode (tem `contratos`
   * e não tem `usuarios`) ordena pelo filho — senão ele iria para o fim da lista
   * por um módulo que nem é o motivo de ele estar ali. */
  return Math.min(proprio, ...(item.subitens ?? []).map((sub) => indiceDoModulo(sub, modulos)));
}

export function gruposPermitidos(modulos: string[]): GrupoNavegacao[] {
  return [...GRUPOS_NAVEGACAO]
    .map((grupo, indiceGrupo) => {
      const itens = grupo.itens
        .map((item) => {
          const subitens = (item.subitens ?? []).filter((sub) => podeAbrirTela(sub.tela, modulos));
          return subitens.length > 0 ? { ...item, subitens } : { ...item, subitens: undefined };
        })
        /* O pai FICA quando só o filho é permitido: ali ele é apenas o rótulo que
         * abre a lista, sem navegar para lugar nenhum (ver `navegarNoPai`). Some
         * de vez só quando nem ele nem nenhum filho sobrou. */
        .filter((item) => podeAbrirTela(item.tela, modulos) || (item.subitens?.length ?? 0) > 0)
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
  const [buscaModulo, setBuscaModulo] = useState("");
  const painelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const fecharNoDesktop = () => { if (media.matches) setAberta(false); };
    media.addEventListener("change", fecharNoDesktop);
    return () => media.removeEventListener("change", fecharNoDesktop);
  }, []);

  /* A contenção saiu daqui para `useFocoContido`: era a única do sistema, e
   * todo diálogo precisa da mesma coisa (ver `ChangePasswordModal`). */
  useFocoContido(painelRef, aberta);
  /* Quais itens com filhos estão expandidos. Vive aqui, e não no item, porque é
   * estado de quem está olhando a coluna — não da definição do menu. */
  const [expandidos, setExpandidos] = useState<Tela[]>([]);
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

  const grupos = useMemo(() => gruposPermitidos(modulos), [modulos]);

  const gruposVisiveis = useMemo(() => {
    const normalizar = (texto: string) => texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const termo = normalizar(buscaModulo.trim());
    if (!termo) return grupos;
    return grupos.map((grupo) => ({ ...grupo, itens: grupo.itens.filter((item) =>
      normalizar(`${grupo.titulo} ${item.rotulo} ${(item.subitens ?? []).map((sub) => sub.rotulo).join(" ")}`).includes(termo),
    ) })).filter((grupo) => grupo.itens.length > 0);
  }, [buscaModulo, grupos]);

  /* Estar numa tela-filha e ver o pai fechado seria a barra dizendo que o item
   * aberto não está em lugar nenhum. Abre o pai da tela atual — e deixa aberto,
   * sem fechar o que a pessoa expandiu à mão. */
  useEffect(() => {
    const pais = grupos
      .flatMap((grupo) => grupo.itens)
      .filter((item) => filhoAtivo(item, tela))
      .map((item) => item.tela);
    if (pais.length === 0) return;
    setExpandidos((atuais) => {
      const faltando = pais.filter((pai) => !atuais.includes(pai));
      return faltando.length === 0 ? atuais : [...atuais, ...faltando];
    });
  }, [grupos, tela]);

  function navegar(destino: Tela) {
    onNavegar(destino);
    setAberta(false);
    setBuscaModulo("");
  }

  function alternar(pai: Tela) {
    setExpandidos((atuais) =>
      atuais.includes(pai) ? atuais.filter((t) => t !== pai) : [...atuais, pai],
    );
  }

  const lista = (
    <nav className="flex flex-col gap-[2px] px-3 pb-20 pt-2" aria-label="Módulos do sistema">
      {gruposVisiveis.map((grupo) => {
        const itens = grupo.itens;
        if (itens.length === 0) return null;
        return (
          <div key={grupo.titulo}>
            <div className={GRUPO_TITULO}>{grupo.titulo}</div>
            {itens.map((item) => {
              const subitens = item.subitens ?? [];
              const temFilhos = subitens.length > 0;
              const expandido = temFilhos && expandidos.includes(item.tela);
              /* Pai com filho aberto também fica aceso: o recuo diz onde a pessoa
               * está, mas só dentro de uma lista que ela consegue ver. */
              const acesa = ativa(item, tela) || (temFilhos && !expandido && filhoAtivo(item, tela));
              const podeAbrirPai = podeAbrirTela(item.tela, modulos);
              const Icone = ICONE_POR_TELA[item.tela] ?? FileText;
              const Seta = expandido ? ChevronDown : ChevronRight;
              return (
                <div key={item.tela}>
                  <button
                    type="button"
                    className={acesa ? ITEM_ATIVO : ITEM}
                    title={item.rotulo}
                    aria-current={acesa ? "page" : undefined}
                    aria-expanded={temFilhos ? expandido : undefined}
                    onClick={() => {
                      /* Um clique faz as duas coisas: abre a lista e vai para a tela
                       * do pai. Separar em dois alvos (seta e rótulo) numa coluna
                       * estreita — e no toque do celular — só produz clique errado. */
                      if (temFilhos) alternar(item.tela);
                      if (podeAbrirPai) navegar(item.tela);
                    }}
                  >
                    <Icone
                      size={17}
                      className={acesa ? "shrink-0 text-marca-ouro" : "shrink-0 text-nav-icone group-hover:text-nav-texto"}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate">{item.rotulo}</span>
                    {temFilhos && (
                      <Seta
                        size={15}
                        className={acesa ? "shrink-0 text-marca-ouro" : "shrink-0 text-nav-icone group-hover:text-nav-texto"}
                        aria-hidden
                      />
                    )}
                  </button>
                  {expandido &&
                    subitens.map((sub) => {
                      const subAcesa = ativa(sub, tela);
                      const IconeSub = ICONE_POR_TELA[sub.tela] ?? FileText;
                      return (
                        <button
                          key={sub.tela}
                          type="button"
                          className={subAcesa ? SUBITEM_ATIVO : SUBITEM}
                          aria-current={subAcesa ? "page" : undefined}
                          onClick={() => navegar(sub.tela)}
                        >
                          <IconeSub
                            size={15}
                            className={subAcesa ? "shrink-0 text-marca-ouro" : "shrink-0 text-nav-icone group-hover:text-nav-texto"}
                            aria-hidden
                          />
                          <span className="min-w-0 truncate">{sub.rotulo}</span>
                        </button>
                      );
                    })}
                </div>
              );
            })}
          </div>
        );
      })}
      {gruposVisiveis.length === 0 && <p className="px-3 py-4 text-sm text-nav-texto-3" role="status">
        {sessao.carregando ? "Carregando módulos…" : "Nenhum módulo encontrado."}
      </p>}
    </nav>
  );

  return (
    <>
      {/* ------------------------------------------------- topo só do celular */}
      <div className="sticky top-0 z-30 flex h-[68px] shrink-0 items-center gap-3 border-b border-nav-borda bg-nav-fundo/95 px-4 py-3 text-nav-texto shadow-[0_12px_30px_rgba(0,42,71,0.18)] backdrop-blur-xl lg:hidden">
        <button
          type="button"
          className="inline-flex min-h-10 min-w-10 cursor-pointer items-center justify-center rounded-[10px] border border-white/[0.16] bg-white/[0.08] text-nav-texto transition-colors hover:bg-white/[0.14]"
          aria-expanded={aberta}
          aria-controls="barra-lateral"
          aria-label={aberta ? "Fechar menu" : "Abrir menu"}
          onClick={() => setAberta((v) => !v)}
        >
          {aberta ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
        </button>
        <div className="min-w-0 flex-1">
          <span className="block truncate font-titulo text-lg font-bold leading-none">Forense</span>
          <span className="mt-1 block truncate text-xs font-medium text-nav-texto-3">
            {GRUPOS_NAVEGACAO.flatMap((grupo) => grupo.itens).find((item) => ativa(item, tela))?.rotulo ?? "Escritório jurídico"}
          </span>
        </div>
        <div className="ml-auto flex min-w-0 items-center gap-2">
          <AlternadorTema flutuante={false} />
          <span className="hidden min-w-0 text-right min-[430px]:block">
            <strong className="block max-w-[130px] truncate text-xs text-nav-texto">{nome}</strong>
            <span className="block max-w-[130px] truncate text-xs text-nav-texto-3">{perfil}</span>
          </span>
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.10] text-xs font-bold uppercase text-nav-texto ring-1 ring-white/[0.16]">
            {nome.slice(0, 2)}
          </span>
          {AUTH_ATIVA && (
            <button
              type="button"
              onClick={sessao.sair}
              className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-[10px] border border-white/[0.16] bg-white/[0.08] text-nav-texto transition-colors hover:bg-white/[0.14]"
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
        ref={painelRef}
        role={aberta ? "dialog" : undefined}
        aria-modal={aberta || undefined}
        aria-label="Navegação principal"
        className={
          "border-nav-borda bg-nav-fundo " +
          // Celular: gaveta fixa que desliza. `translate-x` em vez de `display`
          // para a transição existir e para o conteúdo continuar no DOM — um menu
          // que some do DOM perde o foco do teclado no meio da navegação.
          "fixed inset-y-0 left-0 z-50 w-[264px] max-w-[82vw] overflow-y-auto border-r " +
          "transition-transform duration-200 ease-out " +
          (aberta ? "visible translate-x-0" : "invisible -translate-x-full") +
          // Desktop: coluna do fluxo, sempre visível, acompanhando a rolagem.
          " lg:visible lg:translate-x-0 lg:static lg:z-auto lg:h-dvh lg:w-full lg:max-w-none " +
          "lg:shrink-0"
        }
      >
        <div className="flex items-center justify-between border-b border-nav-borda px-5 py-4 lg:hidden">
          <span className="text-lg font-semibold text-nav-texto">Forense</span>
          <button type="button" onClick={() => setAberta(false)} aria-label="Fechar menu" className="flex size-11 items-center justify-center rounded-campo text-nav-texto hover:bg-nav-fundo-hover">
            <X size={20} aria-hidden />
          </button>
        </div>
        <div className="hidden px-5 pb-4 pt-5 lg:block">
          <MarcaForense superficie="navy" />
        </div>
        <div className="mx-4 mb-3 flex items-center gap-2 rounded-campo border border-nav-borda bg-nav-fundo-hover px-3">
          <Search size={16} className="shrink-0 text-nav-texto-3" aria-hidden />
          <input aria-label="Buscar módulo" placeholder="Buscar módulo" value={buscaModulo}
            onChange={(evento) => setBuscaModulo(evento.target.value)}
            className="min-h-10 w-full min-w-0 bg-transparent text-sm text-nav-texto placeholder:text-nav-texto-3" />
          {buscaModulo && <button type="button" onClick={() => setBuscaModulo("")} aria-label="Limpar busca de módulos"
            className="flex min-h-10 min-w-8 items-center justify-center text-nav-texto"><X size={15} aria-hidden /></button>}
        </div>
        {lista}
      </aside>
    </>
  );
}
