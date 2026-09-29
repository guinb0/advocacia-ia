/* O registro único das telas.
 *
 * Tudo o que se sabe de uma tela sem desenhá-la mora aqui: o nome no cabeçalho,
 * o rótulo no menu, o ícone, o módulo que a libera, a largura e se ela depende de
 * um caso aberto. Antes cada um desses fatos vivia num mapa diferente (modelo da
 * home, casca, barra lateral, carteira, abas do caso) e uma tela nova exigia
 * lembrar de todos. Agora é uma entrada aqui e uma linha no mapa de desenho
 * (`app/home/telas.render.tsx`), que o TypeScript cobra.
 *
 * Este arquivo não importa componente nenhum de propósito: menu, casca e modelo
 * leem daqui sem puxar a árvore de telas junto.
 */

import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  ClipboardCheck,
  Database,
  FileCheck2,
  FileSearch,
  FileSignature,
  FileText,
  FolderKanban,
  HeartPulse,
  LayoutDashboard,
  Layers,
  LibraryBig,
  MessageSquareText,
  PenLine,
  PhoneCall,
  Scale,
  Search,
  Sparkles,
  Tags,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import type { ModuleFrameVariant } from "@/components/layout/ModuleFrame";

export interface DefinicaoTela {
  /** Nome da área no cabeçalho da casca ("Área atual"). */
  rotulo: string;
  /** Rótulo no menu lateral e nos atalhos da carteira, quando difere do `rotulo`. */
  menu?: string;
  /** Linha de apoio do atalho na carteira. */
  apoio?: string;
  icone?: LucideIcon;
  /** Módulo que libera a tela. Sem módulo a tela é LIVRE — ver `podeAbrirTela`. */
  modulo?: string;
  variante: ModuleFrameVariant;
  /** Sem caso aberto a tela volta para a carteira em vez de renderizar vazia. */
  precisaCaso?: boolean;
  /** Aba na navegação do caso aberto (`CasoWorkspaceTabs`). */
  aba?: { titulo: string; apoio: string; icone: LucideIcon };
  /** Título e explicação das telas que não têm cabeçalho próprio. */
  cabecalho?: { titulo: string; subtitulo: string };
}

/* A ORDEM IMPORTA para as telas com módulo: quando a tela atual não é permitida,
 * o perfil cai na PRIMEIRA desta lista que ele alcança (ver `useHomeModel`). */
const DEFINICOES = {
  carteira: {
    rotulo: "Carteira",
    apoio: "mesa do dia",
    icone: LayoutDashboard,
    modulo: "casos",
    variante: "wide",
  },
  caso: {
    rotulo: "Checklist do caso",
    icone: ClipboardCheck,
    modulo: "casos",
    variante: "wide",
    aba: { titulo: "Checklist", apoio: "Documentos", icone: ClipboardCheck },
  },
  dossie: {
    rotulo: "Dossiê do caso",
    icone: FolderKanban,
    modulo: "casos",
    variante: "wide",
    precisaCaso: true,
    aba: { titulo: "Dossiê", apoio: "Fatos e peças", icone: FileText },
  },
  /* São leituras do caso aberto. O backend pode depender de cálculos do agente,
   * mas a navegação aqui não pode exigir o módulo "agente", senão a aba aparece
   * no bloco do caso e o clique é ignorado para quem tem acesso à carteira. */
  painel: {
    rotulo: "Painel analítico",
    icone: BarChart3,
    modulo: "casos",
    variante: "wide",
    precisaCaso: true,
    aba: { titulo: "Painel", apoio: "Andamento", icone: BarChart3 },
  },
  jurimetria: {
    rotulo: "Jurimetria",
    icone: FileText,
    modulo: "casos",
    variante: "wide",
    precisaCaso: true,
    aba: { titulo: "Jurimetria", apoio: "Acervo", icone: Scale },
  },
  casos: {
    rotulo: "Casos",
    apoio: "cadastro e lista",
    icone: BriefcaseBusiness,
    modulo: "casos",
    variante: "compact",
    cabecalho: {
      titulo: "Casos",
      subtitulo:
        "Cadastre um caso para montar o checklist de documentos do cliente, ou abra um caso existente.",
    },
  },
  avulso: {
    rotulo: "Ler documento",
    menu: "Ler um documento",
    apoio: "análise avulsa",
    icone: FileSearch,
    modulo: "documentos",
    variante: "wide",
    cabecalho: {
      titulo: "Ler um documento",
      subtitulo:
        "Leitura solta, para conferir os dados de um documento na hora. Nada aqui é guardado em nenhum caso.",
    },
  },
  investigacao: {
    rotulo: "Investigação",
    menu: "Investigar",
    apoio: "fontes e indícios",
    icone: Search,
    modulo: "investigacao",
    variante: "compact",
  },
  usuarios: {
    rotulo: "Administração",
    apoio: "acessos",
    icone: Users,
    modulo: "usuarios",
    variante: "compact",
  },
  panorama: {
    rotulo: "Panorama",
    apoio: "visão analítica",
    icone: BarChart3,
    modulo: "metricas",
    variante: "wide",
  },
  operacao: {
    rotulo: "Operação",
    icone: Activity,
    modulo: "operacao",
    variante: "wide",
  },
  /* A entrevista saiu de dentro de "Casos" e virou aba própria: são dois
   * trabalhos diferentes. Um é conduzir a conversa com o cliente na linha; o
   * outro é abrir ou reabrir caso — e cada clique na lista, durante um
   * atendimento, era uma chance de sair dele sem querer. */
  entrevista: {
    rotulo: "Entrevista guiada",
    apoio: "iniciar atendimento",
    icone: MessageSquareText,
    modulo: "entrevista",
    variante: "wide",
    cabecalho: {
      titulo: "Entrevista guiada",
      subtitulo:
        "Conduza o atendimento pelo roteiro, com a conversa sendo transcrita. O caso nasce daqui, já com o tipo de ação escolhido.",
    },
  },
  supervisao: {
    rotulo: "Supervisão",
    apoio: "entrevistas",
    icone: Activity,
    modulo: "supervisao",
    variante: "wide",
  },
  dados: {
    rotulo: "Dados",
    apoio: "acervo indexado",
    icone: Database,
    modulo: "metricas",
    variante: "wide",
  },
  saudeAgente: {
    rotulo: "Saúde do agente",
    apoio: "integrações",
    icone: HeartPulse,
    modulo: "agente",
    variante: "wide",
  },
  revisao: {
    rotulo: "Revisão do roteiro",
    icone: FileCheck2,
    modulo: "revisao",
    variante: "wide",
  },
  followup: {
    rotulo: "Follow-up",
    icone: PhoneCall,
    modulo: "casos",
    variante: "wide",
  },
  documentacao: {
    rotulo: "Documentação",
    apoio: "apoio documental",
    icone: LibraryBig,
    modulo: "documentacao",
    variante: "wide",
  },
  /* Sem o módulo a tela seria LIVRE, não restrita: `podeAbrirTela` libera o que
   * não está mapeado. O catálogo de roteiros pertence ao módulo `roteiros`, que o
   * advogado e o secretário têm — ver `app/perfis.py`. */
  catalogoRoteiros: {
    rotulo: "Roteiros",
    apoio: "roteiros guiados",
    icone: BookOpen,
    modulo: "roteiros",
    variante: "compact",
  },
  /* Guarda o token de Clicksign/Autentique do escritório — mesmo módulo que já
   * controla os modelos de contrato (`app/rotas/contratos.py`, `PodeManterModelos`). */
  configuracaoAssinatura: {
    rotulo: "Tactiq e assinatura eletrônica",
    menu: "Tactiq",
    icone: FileSignature,
    modulo: "contratos",
    variante: "compact",
  },
  /* A TELA de manutenção pede o módulo; consultar o glossário não pede — a
   * reclassificação, dentro do caso, lê a lista sem passar por aqui. */
  glossarioDocumentos: {
    rotulo: "Glossário de documentos",
    apoio: "tipos de documento",
    icone: Tags,
    modulo: "glossario_documentos",
    variante: "compact",
  },
  /* Mesma regra do glossário: manter o catálogo pede o módulo, consultá-lo não —
   * a criação do caso lê a lista de ações sem passar por aqui. */
  tiposDeCaso: {
    rotulo: "Tipos de caso",
    apoio: "tipos de caso",
    icone: Layers,
    modulo: "tipos_caso",
    variante: "wide",
  },
  skills: {
    rotulo: "Skills",
    icone: Sparkles,
    modulo: "skills",
    variante: "wide",
  },
  gastosApi: {
    rotulo: "Gastos das APIs",
    icone: Wallet,
    modulo: "gastos_api",
    variante: "wide",
  },
  /* O `chat` de propósito NÃO tem módulo — como `modelosDePeticao`.
   *
   * Ele é a porta única de perguntas, e quem limita o que cada pessoa vê são os
   * destinos, no servidor: o caso só responde sobre caso do acervo, os documentos
   * passam pela mesma rota autenticada do dossiê. Exigir um módulo aqui esconderia a
   * tela inteira de quem pode perguntar sobre metade do que ela alcança.
   *
   * `workspace` (largura cheia) porque o desenho dele já contém a própria largura de
   * leitura: o miolo tem 780px no meio de uma casca que usa a tela toda. */
  chat: {
    rotulo: "Chat",
    variante: "workspace",
  },
  agente: {
    rotulo: "Agente",
    apoio: "assistente geral",
    icone: Bot,
    variante: "wide",
  },
  /* `modelosDePeticao` de propósito NÃO tem módulo.
   *
   * Na barra horizontal antiga o item aparecia para todo mundo (filtro de perfil
   * retirado enquanto o produto está em construção). Ao migrar para a barra
   * lateral, o mapeamento para o módulo `agente` escondeu a entrada de quem não
   * tinha esse módulo na sessão — e a modelagem de petições "sumiu" do menu. Sem
   * mapeamento, `podeAbrirTela` libera a tela; o backend segue autenticando as APIs
   * do agente. */
  modelosDePeticao: {
    rotulo: "Modelos de petição",
    apoio: "petições",
    icone: PenLine,
    variante: "compact",
  },
} as const satisfies Record<string, DefinicaoTela>;

/** A carteira é a porta de entrada; as outras telas são destinos dela. */
export type Tela = keyof typeof DEFINICOES;

export const DEFINICAO_TELA: Record<Tela, DefinicaoTela> = DEFINICOES;

/** Toda tela que a URL aceita. Existe em runtime porque `Tela` é só um tipo:
 * sem esta lista não há como conferir o que veio do endereço, e um `?tela=`
 * inventado viraria um estado que nenhuma tela sabe renderizar. */
export const TELAS = Object.keys(DEFINICOES) as Tela[];

export function ehTela(valor: string | null | undefined): valor is Tela {
  return typeof valor === "string" && (TELAS as string[]).includes(valor);
}

/** Telas guardadas por módulo, na ordem do registro. */
export const MODULO_DA_TELA: Partial<Record<Tela, string>> = Object.fromEntries(
  TELAS.flatMap((tela) => {
    const modulo = DEFINICAO_TELA[tela].modulo;
    return modulo ? [[tela, modulo]] : [];
  }),
);

export function podeAbrirTela(tela: Tela, modulos: string[]): boolean {
  const modulo = MODULO_DA_TELA[tela];
  return !modulo || modulos.includes(modulo);
}

export function rotuloDaTela(tela: Tela): string {
  return DEFINICAO_TELA[tela].rotulo;
}

export function rotuloNoMenu(tela: Tela): string {
  const definicao = DEFINICAO_TELA[tela];
  return definicao.menu ?? definicao.rotulo;
}

export function iconeDaTela(tela: Tela): LucideIcon | undefined {
  return DEFINICAO_TELA[tela].icone;
}

/** As abas do caso aberto, na ordem do registro. */
export const ABAS_DO_CASO = TELAS.flatMap((tela) => {
  const aba = DEFINICAO_TELA[tela].aba;
  return aba ? [{ tela, ...aba }] : [];
});
