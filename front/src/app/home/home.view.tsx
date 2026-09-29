"use client";

import { Botao } from "@/components/ui/Basicos";
import AppShell from "@/components/layout/AppShell";
import ModuleFrame from "@/components/layout/ModuleFrame";
import CasoWorkspaceTabs from "@/components/caso/CasoWorkspaceTabs";
import LimiteDeErro from "@/components/ui/LimiteDeErro";
import { useSessao } from "@/lib/auth";
import { DEFINICAO_TELA } from "@/lib/telas";

import type { useHomeModel } from "./home.model";
import { DESENHO_DA_TELA } from "./telas.render";

type HomeViewProps = ReturnType<typeof useHomeModel>;

/* A casca: barra lateral + conteúdo, em volta de QUALQUER tela.
 *
 * Fica aqui, e não dentro de cada tela, porque menu montado por tela é o que havia
 * antes — a faixa horizontal vivia dentro da `Carteira` e por isso sumia nas outras
 * dez. Envolvendo o miolo, a barra existe em todas e cada uma continua sem saber
 * que ela existe.
 *
 * `min-w-0` no `<main>` não é enfeite: sem ele, um filho largo (tabela, `<pre>` de
 * transcrição, grade de cartões) força o item de grid a crescer e a página inteira
 * ganha rolagem horizontal — com a barra lateral empurrada para fora da tela. */
const HomeView = (props: HomeViewProps) => (
  <AppShell tela={props.tela} skillAberta={props.skillAberta} onNavegar={props.setTela} onAbrirSkill={props.abrirSkill}>
    {/* O limite fica AQUI, e não dentro de cada tela: um erro de desenho não pode levar a
     * casca e o menu embora. Antes disso, uma exceção em qualquer tela deixava a janela em
     * branco — sem mensagem, sem menu e sem nada para rolar —, e a única saída era o F5.
     * `chave={props.tela}` faz a navegação valer como nova tentativa. */}
    <LimiteDeErro chave={`${props.tela}:${props.skillAberta ?? ""}`}>
      <Telas {...props} />
    </LimiteDeErro>
  </AppShell>
);

/* A moldura comum: largura, navegação do caso e cabeçalho saem do registro de
 * telas; o miolo sai de `DESENHO_DA_TELA`. */
const Telas = (props: HomeViewProps) => {
  const sessao = useSessao();
  const { tela, casoAberto, situacaoCaso, voltarParaCarteira } = props;
  const definicao = DEFINICAO_TELA[tela];

  // Sem caso aberto não há dossiê, painel nem jurimetria: voltar é mais honesto que
  // renderizar vazio.
  if (definicao.precisaCaso && !casoAberto) {
    voltarParaCarteira();
    return null;
  }

  const miolo = DESENHO_DA_TELA[tela]({ ...props, sessao, casoId: casoAberto ?? "" });
  const dadosDoCasoAberto = situacaoCaso.situacao;

  if (definicao.aba) {
    return (
      <ModuleFrame variant={definicao.variante}>
        <div className="min-w-0 space-y-5">
          <CasoWorkspaceTabs
            tela={tela}
            onNavegar={props.setTela}
            cliente={dadosDoCasoAberto?.caso.cliente}
            categoria={dadosDoCasoAberto?.categoria?.nome}
            abertoEm={dadosDoCasoAberto?.caso.criado_em}
          />
          {miolo}
        </div>
      </ModuleFrame>
    );
  }

  /* Título e explicação das telas sem cabeçalho próprio. Ter isso escrito na tela
   * é o que responde "onde eu estou" sem depender de memória. */
  if (definicao.cabecalho) {
    return (
      <ModuleFrame variant={definicao.variante}>
        <div>
          <div className="flex justify-between items-end gap-5 mb-[22px] flex-wrap">
            <div>
              <Botao variante="secundario" pequeno onClick={voltarParaCarteira}>
                ← Voltar para a carteira
              </Botao>
              <h1 className="mt-[6px] mb-0 text-xl tracking-[-0.01em]">{definicao.cabecalho.titulo}</h1>
              <p className="mt-[5px] mb-0 max-w-[66ch] text-tinta-2 text-base">{definicao.cabecalho.subtitulo}</p>
            </div>
          </div>
          {miolo}
        </div>
      </ModuleFrame>
    );
  }

  return <ModuleFrame variant={definicao.variante}>{miolo}</ModuleFrame>;
};

export default HomeView;
