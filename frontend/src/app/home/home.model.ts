"use client";

import { useEffect, useRef, useState } from "react";

import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useSessao } from "@/lib/auth";
import { useChamada } from "@/lib/ChamadaContexto";

/** A carteira é a porta de entrada; as outras telas são destinos dela. */
export type Tela =
  | "carteira"
  | "agente"
  | "caso"
  | "dossie"
  | "painel"
  | "jurimetria"
  | "casos"
  | "avulso"
  | "investigacao"
  | "usuarios"
  | "panorama"
  | "entrevista"
  | "supervisao"
  | "dados"
  | "saudeAgente"
  | "modelosDePeticao"
  | "catalogoRoteiros"
  | "documentacao";

export const MODULO_DA_TELA: Partial<Record<Tela, string>> = {
  carteira: "casos",
  caso: "casos",
  dossie: "casos",
  /* São leituras do caso aberto. O backend pode depender de cálculos do agente,
   * mas a navegação aqui não pode exigir o módulo "agente", senão a aba aparece
   * no bloco do caso e o clique é ignorado para quem tem acesso à carteira. */
  painel: "casos",
  jurimetria: "casos",
  casos: "casos",
  avulso: "documentos",
  investigacao: "investigacao",
  usuarios: "usuarios",
  panorama: "metricas",
  entrevista: "entrevista",
  supervisao: "supervisao",
  dados: "metricas",
  saudeAgente: "agente",
  documentacao: "documentacao",
  /* Sem esta linha a tela seria LIVRE, não restrita: `podeAbrirTela` libera o
   * que não está mapeado. O catálogo de roteiros pertence ao módulo `roteiros`,
   * que o advogado e o secretário têm — ver `app/perfis.py`. */
  catalogoRoteiros: "roteiros",
  /* `modelosDePeticao` de propósito NÃO está aqui.
   *
   * Na barra horizontal antiga o item aparecia para todo mundo (filtro de
   * perfil retirado enquanto o produto está em construção). Ao migrar para a
   * barra lateral, o mapeamento para o módulo `agente` escondeu a entrada de
   * quem não tinha esse módulo na sessão — e a modelagem de petições "sumiu"
   * do menu. Sem mapeamento, `podeAbrirTela` libera a tela; o backend segue
   * autenticando as APIs do agente. */
};

export function podeAbrirTela(tela: Tela, modulos: string[]): boolean {
  const modulo = MODULO_DA_TELA[tela];
  return !modulo || modulos.includes(modulo);
}

/* Título e explicação de cada tela secundária. Ter isso escrito na tela é o
 * que responde "onde eu estou" sem depender de memória. */
export const CABECALHO: Record<
  "casos" | "avulso" | "entrevista",
  { titulo: string; subtitulo: string }
> = {
  casos: {
    titulo: "Casos",
    subtitulo:
      "Cadastre um caso para montar o checklist de documentos do cliente, ou abra um caso existente.",
  },
  /* A entrevista saiu de dentro de "Casos" e virou aba própria: são dois
   * trabalhos diferentes. Um é conduzir a conversa com o cliente na linha; o
   * outro é abrir ou reabrir caso — e cada clique na lista, durante um
   * atendimento, era uma chance de sair dele sem querer. */
  entrevista: {
    titulo: "Entrevista guiada",
    subtitulo:
      "Conduza o atendimento pelo roteiro, com a conversa sendo transcrita. O caso nasce daqui, já com o tipo de ação escolhido.",
  },
  avulso: {
    titulo: "Ler um documento",
    subtitulo:
      "Leitura solta, para conferir os dados de um documento na hora. Nada aqui é guardado em nenhum caso.",
  },
};

/**
 * O ViewModel da tela principal: qual tela está aberta, qual caso está em foco e
 * os dados que as duas coisas exigem.
 *
 * A navegação continua por estado, e não por rota do Next — de propósito. Trocar
 * de "tela" aqui não recarrega a página, e é isso que permite a chamada de vídeo
 * seguir de pé enquanto o advogado passa do checklist para o dossiê. Rotas de
 * verdade desmontariam a árvore e derrubariam a ligação com o cliente no meio do
 * atendimento.
 */
export const useHomeModel = () => {
  const [tela, setTela] = useState<Tela>("entrevista");
  const sessao = useSessao();
  const chamada = useChamada();
  const [casoAberto, setCasoAberto] = useState<string | null>(null);

  const categorias = useCategorias();
  const listaCasos = useCasos();
  const documentadorEmChamada =
    sessao.modulos.includes("documentacao") &&
    chamada.estado !== "fora" &&
    chamada.estado !== "encerrada";
  const situacaoCaso = useSituacao(casoAberto, documentadorEmChamada);
  const modulos = sessao.modulos;

  /* Quem é da Documentação CAI na tela da Documentação — uma vez, ao entrar.
   *
   * Este efeito prendia, e por dois caminhos. `sessao.papeis` é montado como
   * `[loggedUser.perfil]` em `lib/auth.tsx` — array literal novo a cada render,
   * então a dependência muda de identidade sempre e o efeito redispara sempre.
   * E `tela` também está nas dependências: a pessoa clica em Casos, `tela` muda,
   * o efeito roda e a devolve para a Documentação antes de a tela aparecer.
   *
   * Nos dois casos o resultado era o mesmo: o perfil ficava trancado na própria
   * tela, sem alcançar carteira, casos ou documentos — que ele tem todo direito
   * de ver, e que o `podeAbrirTela` abaixo já confere de verdade.
   *
   * O `useRef` faz o que este ramo prometia: leva para lá na primeira carga e
   * não interfere mais. É atalho de conveniência, nunca permissão — quem decide
   * o que cada perfil acessa é `app/perfis.py`, no servidor. */
  const jaDirecionado = useRef(false);
  useEffect(() => {
    if (sessao.carregando) return;
    /* O atalho de entrada, UMA vez. Sem o `jaDirecionado`, `tela` está nas
     * dependências e este ramo redispara a cada navegação: a pessoa clica em
     * Casos, o efeito roda porque `tela` mudou, e ela volta para a Documentação
     * antes de a tela aparecer. */
    if (
      !jaDirecionado.current &&
      sessao.papeis.includes("documentacao") &&
      podeAbrirTela("documentacao", modulos)
    ) {
      jaDirecionado.current = true;
      setTela("documentacao");
      return;
    }
    /* Esta parte SEGUE valendo sempre, e é a que de fato guarda: tela que o
     * perfil não alcança devolve para a primeira que ele alcança. */
    if (!podeAbrirTela(tela, modulos)) {
      const primeira = (Object.keys(MODULO_DA_TELA) as Tela[]).find((candidata) =>
        podeAbrirTela(candidata, modulos),
      );
      setTela(primeira ?? "carteira");
    }
  }, [modulos, sessao.carregando, sessao.papeis, tela]);

  function navegar(telaNova: Tela) {
    if (podeAbrirTela(telaNova, modulos)) setTela(telaNova);
  }

  function abrirCaso(casoId: string) {
    setCasoAberto(casoId);
    navegar("caso");
  }

  function abrirDossie(casoId: string) {
    setCasoAberto(casoId);
    navegar("dossie");
  }

  function abrirAnalises(casoId: string) {
    setCasoAberto(casoId);
    navegar("painel");
  }

  function voltarParaCarteira() {
    setCasoAberto(null);
    navegar("carteira");
    void listaCasos.recarregar();
  }

  return {
    tela,
    setTela: navegar,
    casoAberto,
    categorias,
    listaCasos,
    situacaoCaso,
    abrirCaso,
    abrirDossie,
    abrirAnalises,
    voltarParaCarteira,
  };
};
