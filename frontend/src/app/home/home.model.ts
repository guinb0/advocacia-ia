"use client";

import { useEffect, useRef, useState } from "react";

import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useSessao } from "@/lib/auth";

/** A carteira é a porta de entrada; as outras telas são destinos dela. */
export type Tela =
  | "carteira"
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
  const [casoAberto, setCasoAberto] = useState<string | null>(null);

  const categorias = useCategorias();
  const listaCasos = useCasos();
  const situacaoCaso = useSituacao(casoAberto);

  /* Quem é da Documentação CAI na tela da Documentação — uma vez, ao entrar.
   *
   * Este efeito prendia. `sessao.papeis` é montado como `[loggedUser.perfil]`
   * em `lib/auth.tsx`: um array literal novo a cada render, então a dependência
   * mudava de identidade sempre, o efeito redisparava sempre, e qualquer clique
   * em outro item do menu era desfeito antes de a tela aparecer. Na prática o
   * perfil ficava trancado na própria tela, sem alcançar carteira, casos ou
   * documentos — que ele tem todo direito de ver.
   *
   * O `useRef` faz o que o `useEffect` prometia: leva para lá na primeira carga
   * e não interfere mais. É atalho de conveniência, nunca permissão — quem
   * decide o que cada perfil acessa é `app/perfis.py`, no servidor. */
  const jaDirecionado = useRef(false);
  useEffect(() => {
    if (jaDirecionado.current) return;
    if (sessao.papeis.includes("documentacao")) {
      jaDirecionado.current = true;
      setTela("documentacao");
    }
  }, [sessao.papeis]);

  function abrirCaso(casoId: string) {
    setCasoAberto(casoId);
    setTela("caso");
  }

  function voltarParaCarteira() {
    setCasoAberto(null);
    setTela("carteira");
    void listaCasos.recarregar();
  }

  return {
    tela,
    setTela,
    casoAberto,
    categorias,
    listaCasos,
    situacaoCaso,
    abrirCaso,
    voltarParaCarteira,
  };
};
