"use client";

import { useEffect, useRef, useState } from "react";

import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useSessao } from "@/lib/auth";
import { useChamada } from "@/lib/ChamadaContexto";
import { ehTela, MODULO_DA_TELA, podeAbrirTela, type Tela } from "@/lib/telas";

/** O que o endereço atual diz: qual tela, e qual caso em foco. */
function lerEndereco(): { tela: Tela | null; caso: string | null; skill: string | null } {
  if (typeof window === "undefined") return { tela: null, caso: null, skill: null };
  const busca = new URLSearchParams(window.location.search);
  const tela = busca.get("tela");
  return { tela: ehTela(tela) ? tela : null, caso: busca.get("caso"), skill: busca.get("skill") };
}

/** Espelha o estado no endereço.
 *
 * `history.pushState` direto, e não o roteador do Next, de propósito: trocar de
 * rota desmontaria a árvore e derrubaria a chamada de vídeo em andamento — que é
 * a razão de a navegação ser por estado (ver `useHomeModel`). Mexer só na query
 * dá endereço próprio, F5, voltar/avançar e link para mandar a alguém, sem
 * remontar nada. */
function escreverEndereco(tela: Tela, caso: string | null, skill: string | null, modo: "push" | "replace"): void {
  if (typeof window === "undefined") return;
  const busca = new URLSearchParams(window.location.search);
  busca.set("tela", tela);
  if (caso) busca.set("caso", caso);
  else busca.delete("caso");
  if (tela === "skills" && skill) busca.set("skill", skill);
  else busca.delete("skill");
  const query = busca.toString();
  if (window.location.search === `?${query}`) return;
  const endereco = `${window.location.pathname}?${query}`;
  if (modo === "push") window.history.pushState(null, "", endereco);
  else window.history.replaceState(null, "", endereco);
}

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
  const [skillAberta, setSkillAberta] = useState<string | null>(null);
  /* A tela Casos mostra o assistente de criação em vez da lista. Não vai para o
   * endereço: um F5 no meio do assistente perderia o que foi digitado de qualquer
   * jeito, e cair na lista é o recomeço menos confuso. */
  const [criandoCaso, setCriandoCaso] = useState(false);

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

  /* O endereço manda na primeira carga. Recarregar a página numa tela e cair na
   * de entrada perdia o contexto inteiro — e era o que acontecia enquanto a tela
   * só existia em estado. Marcar `jaDirecionado` aqui impede que o atalho de
   * conveniência logo abaixo desfaça o que a pessoa pediu no endereço. */
  const enderecoRestaurado = useRef(false);
  useEffect(() => {
    const endereco = lerEndereco();
    if (endereco.caso) setCasoAberto(endereco.caso);
    if (endereco.skill) setSkillAberta(endereco.skill);
    if (endereco.tela) {
      jaDirecionado.current = true;
      setTela(endereco.tela);
    }
    enderecoRestaurado.current = true;
  }, []);

  /* Voltar e avançar do navegador. Sem isto o botão de voltar sairia do sistema
   * inteiro em vez de desfazer a última troca de tela. */
  useEffect(() => {
    function aoVoltar() {
      const endereco = lerEndereco();
      setCasoAberto(endereco.caso);
      setSkillAberta(endereco.tela === "skills" ? endereco.skill : null);
      if (endereco.tela) setTela(endereco.tela);
    }
    window.addEventListener("popstate", aoVoltar);
    return () => window.removeEventListener("popstate", aoVoltar);
  }, []);

  /* Estado → endereço. Empilha no histórico só o que a PESSOA pediu: o atalho de
   * entrada e a guarda de permissão também trocam de tela, e se empilhassem, o
   * botão de voltar devolveria a uma tela que ninguém escolheu — e que a guarda
   * desfaria de novo na hora. */
  const navegacaoDoUsuario = useRef(false);
  useEffect(() => {
    /* Enquanto a restauração acima não rodou, `tela` ainda é o padrão do
     * `useState` — gravá-lo apagaria da URL a tela que a pessoa pediu. */
    if (sessao.carregando || !enderecoRestaurado.current) return;
    escreverEndereco(tela, casoAberto, skillAberta, navegacaoDoUsuario.current ? "push" : "replace");
    navegacaoDoUsuario.current = false;
  }, [tela, casoAberto, skillAberta, sessao.carregando]);

  useEffect(() => {
    if (sessao.carregando) return;
    /* O atalho de entrada, UMA vez. Sem o `jaDirecionado`, `tela` está nas
     * dependências e este ramo redispara a cada navegação: a pessoa clica em
     * Casos, o efeito roda porque `tela` mudou, e ela volta para a tela de
     * entrada antes de a tela aparecer.
     *
     * A tela de entrada varia com o trabalho da pessoa, decidida por MÓDULO (e
     * não por nome de perfil, que o escritório edita — ver `app/perfis.py`):
     *   - Documentação → a central da documentação (fila + status dos clientes);
     *   - perfil de escritório (secretário/analista): tem visão geral mas NÃO
     *     conduz atendimento → o painel de andamento do escritório;
     *   - advogado/entrevistador e os demais → a entrevista guiada (padrão).
     * É só atalho de conveniência: `podeAbrirTela` é quem de fato autoriza. */
    if (!jaDirecionado.current) {
      jaDirecionado.current = true;
      if (
        sessao.papeis.includes("documentacao") &&
        podeAbrirTela("documentacao", modulos)
      ) {
        setTela("documentacao");
        return;
      }
      if (!modulos.includes("entrevista") && podeAbrirTela("panorama", modulos)) {
        setTela("panorama");
        return;
      }
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
    if (!podeAbrirTela(telaNova, modulos)) return;
    navegacaoDoUsuario.current = true;
    setSkillAberta(null);
    setCriandoCaso(false);
    setTela(telaNova);
  }

  function novoCaso() {
    if (!podeAbrirTela("casos", modulos)) return;
    navegar("casos");
    setCriandoCaso(true);
  }

  function abrirSkill(skillId: string) {
    if (!podeAbrirTela("skills", modulos)) return;
    navegacaoDoUsuario.current = true;
    setSkillAberta(skillId);
    setTela("skills");
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
    abrirSkill,
    skillAberta,
    voltarParaCarteira,
    criandoCaso,
    novoCaso,
    fecharNovoCaso: () => setCriandoCaso(false),
  };
};
