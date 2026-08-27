"use client";

import { useState } from "react";

import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import AppShell from "@/components/layout/AppShell";
import ModuleFrame from "@/components/layout/ModuleFrame";
import AgenteGeral from "@/components/AgenteGeral";
import Carteira from "@/components/carteira/Carteira";
import Checklist from "@/components/caso/Checklist";
import Dados from "@/components/caso/Dados";
import Dossie, { PainelAnaliseDocumentos } from "@/components/admin/Dossie";
import Investigacao from "@/components/carteira/Investigacao";
import Jurimetria from "@/components/admin/Jurimetria";
import ListaCasos from "@/components/carteira/ListaCasos";
import PainelCaso from "@/components/caso/PainelCaso";
import Panorama from "@/components/Panorama";
import PainelEnvio from "@/components/caso/PainelEnvio";
import ProgressoOcr from "@/components/ui/ProgressoOcr";
import ChamadaDoAtendimento from "@/components/chamada/ChamadaDoAtendimento";
import TriagemEntrevista from "@/components/entrevista/TriagemEntrevista";
import Supervisao from "@/components/admin/Supervisao";
import SaudeAgente from "@/components/SaudeAgente";
import ModelosDePeticao from "@/components/ModelosDePeticao";
import Usuarios from "@/components/admin/Usuarios";
import Resultado from "@/components/caso/Resultado";
import CentralDocumentacao from "@/components/documentacao/CentralDocumentacao";
import CatalogoRoteiros from "@/components/admin/CatalogoRoteiros";
import { useCasos, useCategorias } from "@/lib/useCasos";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";
import { useSessao } from "@/lib/auth";


import { CABECALHO, useHomeModel } from "./home.model";

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
  <AppShell tela={props.tela} onNavegar={props.setTela}>
    <Telas {...props} />
  </AppShell>
);

const Telas = (props: HomeViewProps) => {
  const sessao = useSessao();
  const {
    tela,
    setTela,
    casoAberto,
    categorias,
    listaCasos,
    situacaoCaso,
    abrirCaso,
    abrirDossie,
    abrirAnalises,
    voltarParaCarteira,
  } = props;

  if (tela === "carteira") {
    return (
      <ModuleFrame variant="wide">
        <Carteira
          onAbrir={abrirCaso}
          onNovoCaso={() => setTela("casos")}
          onAnalisarAvulso={() => setTela("avulso")}
          onInvestigar={() => setTela("investigacao")}
          onUsuarios={() => setTela("usuarios")}
          onEntrevista={() => setTela("entrevista")}
          onSupervisao={() => setTela("supervisao")}
          onDados={() => setTela("dados")}
          onPanorama={() => setTela("panorama")}
          onSaudeAgente={() => setTela("saudeAgente")}
          onModelosDePeticao={() => setTela("modelosDePeticao")}
        />
      </ModuleFrame>
    );
  }

  /* O agente geral não pede caso aberto: ele é justamente a conversa de quem ainda não
   * sabe qual caso abrir. Da resposta se salta para o dossiê do caso citado. */
  if (tela === "agente") {
    return (
      <ModuleFrame variant="wide">
        <AgenteGeral onVoltar={voltarParaCarteira} onAbrirCaso={abrirCaso} />
      </ModuleFrame>
    );
  }

  if (tela === "dossie") {
    // Sem caso aberto não há dossiê: voltar é mais honesto que renderizar vazio.
    if (!casoAberto) {
      voltarParaCarteira();
      return null;
    }
    return (
      <ModuleFrame variant="wide">
        <Dossie
          casoId={casoAberto}
          onVoltar={voltarParaCarteira}
          onAbrirPainel={() => setTela("painel")}
          onAbrirJurimetria={() => setTela("jurimetria")}
        />
      </ModuleFrame>
    );
  }

  if (tela === "jurimetria") {
    // Mesma regra das demais: sem caso aberto não há recorte comparável.
    if (!casoAberto) {
      voltarParaCarteira();
      return null;
    }
    return (
      <ModuleFrame variant="wide">
        <Jurimetria
          casoId={casoAberto}
          onVoltar={voltarParaCarteira}
          onAbrirDossie={() => setTela("dossie")}
          onAbrirPainel={() => setTela("painel")}
        />
      </ModuleFrame>
    );
  }

  if (tela === "painel") {
    // Mesma regra do dossiê: painel sem caso aberto não existe.
    if (!casoAberto) {
      voltarParaCarteira();
      return null;
    }
    return (
      <ModuleFrame variant="wide">
        <PainelCaso
          casoId={casoAberto}
          onVoltar={voltarParaCarteira}
          onAbrirChecklist={() => setTela("caso")}
          onAbrirDossie={() => setTela("dossie")}
          onAbrirJurimetria={() => setTela("jurimetria")}
        />
      </ModuleFrame>
    );
  }

  if (tela === "investigacao") {
    return (
      <ModuleFrame variant="compact">
        <Investigacao onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "usuarios") {
    return (
      <ModuleFrame variant="compact">
        <Usuarios onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "documentacao") {
    return (
      <ModuleFrame variant="wide">
        <CentralDocumentacao
          onVoltar={voltarParaCarteira}
          onAbrirDocumentos={abrirCaso}
        />
      </ModuleFrame>
    );
  }

  if (tela === "supervisao") {
    return (
      <ModuleFrame variant="wide">
        <Supervisao onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  /* O panorama não pede caso aberto — é justamente a tela de quem não quer abrir
   * caso nenhum. Da lista de parados ele salta direto para o caso citado. */
  if (tela === "panorama") {
    return (
      <ModuleFrame variant="wide">
        <Panorama onVoltar={voltarParaCarteira} onAbrirCaso={abrirCaso} />
      </ModuleFrame>
    );
  }

  if (tela === "saudeAgente") {
    return (
      <ModuleFrame variant="wide">
        <SaudeAgente onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "modelosDePeticao") {
    return (
      <ModuleFrame variant="compact">
        <ModelosDePeticao onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "catalogoRoteiros") {
    return (
      <ModuleFrame variant="compact">
        <CatalogoRoteiros onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "dados") {
    return (
      <ModuleFrame variant="wide">
        <Dados onVoltar={voltarParaCarteira} />
      </ModuleFrame>
    );
  }

  if (tela === "caso") {
    return (
      <ModuleFrame variant="wide">
      <div className="space-y-5">
        {/* O checklist responde "o que falta chegar"; o dossiê, "o que o caso já
          * é". São perguntas diferentes e telas diferentes — juntá-las numa só
          * faria a mais longa esconder a mais usada. */}
        <div className="flex flex-wrap items-center gap-2">
          <Botao variante="secundario" pequeno disabled>
            Checklist de documentos
          </Botao>
          <Botao variante="texto" pequeno onClick={() => setTela("dossie")}>
            Dossiê do caso →
          </Botao>
          {/* O painel é a leitura no tempo: quanto cada etapa levou, como o caso se
            * compara com os anteriores e há quantos dias nada acontece. */}
          <Botao variante="texto" pequeno onClick={() => setTela("painel")}>
            Painel analítico →
          </Botao>
          {/* A jurimetria é a única leitura que olha para fora do escritório: como o
            * foro decidiu casos comparáveis, e onde este cai dentro disso. */}
          <Botao variante="texto" pequeno onClick={() => setTela("jurimetria")}>
            Jurisprudência e jurimetria →
          </Botao>
        </div>
        {sessao.modulos.includes("documentacao") && <ChamadaDoAtendimento modo="documentacao" />}
        {situacaoCaso.situacao ? (
          <>
            <Checklist
              mostrarPrazos
              situacao={situacaoCaso.situacao}
              enviando={situacaoCaso.enviando}
              erro={situacaoCaso.erro}
              onVoltar={voltarParaCarteira}
              onEnviar={situacaoCaso.enviar}
              onEnviarLote={situacaoCaso.enviarLote}
              onRemover={situacaoCaso.removerEntrega}
              onVincularIdentidade={situacaoCaso.vincularIdentidade}
              onReatribuir={situacaoCaso.reatribuir}
            />
            {casoAberto && <PainelAnaliseDocumentos casoId={casoAberto} />}
          </>
        ) : situacaoCaso.erro ? (
          <>
            <Botao variante="secundario" className="mb-4" onClick={voltarParaCarteira}>
              ← Voltar para a carteira
            </Botao>
            <Aviso tom="critico" titulo="Não foi possível abrir o caso">
              {situacaoCaso.erro}
            </Aviso>
          </>
        ) : (
          <Vazio>Carregando o caso…</Vazio>
        )}
      </div>
      </ModuleFrame>
    );
  }

  const cabecalho = CABECALHO[tela];

  return (
    <ModuleFrame variant={tela === "casos" ? "compact" : "wide"}>
    <div>
      <div className="flex justify-between items-end gap-5 mb-[22px] flex-wrap">
        <div>
          <Botao variante="secundario" pequeno onClick={voltarParaCarteira}>
            ← Voltar para a carteira
          </Botao>
          <h1 className="mt-[6px] mb-0 text-xl tracking-[-0.01em]">{cabecalho.titulo}</h1>
          <p className="mt-[5px] mb-0 max-w-[66ch] text-tinta-2 text-base">{cabecalho.subtitulo}</p>
        </div>
      </div>

      {tela === "casos" ? (
        <ListaCasos
          casos={listaCasos.casos}
          categorias={categorias}
          carregando={listaCasos.carregando}
          erro={listaCasos.erro}
          onAbrir={abrirCaso}
          onCriar={listaCasos.criar}
          onExcluir={listaCasos.excluir}
        />
      ) : tela === "entrevista" ? (
        <EntrevistaGuiada
          categorias={categorias}
          onCriar={listaCasos.criar}
          onAbrirDossie={abrirDossie}
          onAbrirAnalises={abrirAnalises}
        />
      ) : (
        <AnaliseAvulsa />
      )}
    </div>
    </ModuleFrame>
  );
};

export default HomeView;

/* A entrevista na aba dela.
 *
 * Numa aba própria não há lista para esconder nem formulário ao lado para
 * preencher — os dois só existiam por ela morar dentro de "Casos". O que veio
 * junto foi a CHAMADA do pós-entrevista: a etapa seguinte manda permanecer na
 * videoconferência enquanto o cliente avalia, e sem este painel a instrução
 * ficaria sem o vídeo ao lado. */
function EntrevistaGuiada({
  categorias,
  onCriar,
  onAbrirDossie,
  onAbrirAnalises,
}: {
  categorias: ReturnType<typeof useCategorias>;
  onCriar: ReturnType<typeof useCasos>["criar"];
  onAbrirDossie: (casoId: string) => void;
  onAbrirAnalises: (casoId: string) => void;
}) {
  const [fase, setFase] = useState<"nenhum" | "entrevista" | "pos-entrevista">("nenhum");
  return (
    <>
      <TriagemEntrevista
        categorias={categorias}
        onCriarCaso={onCriar}
        onAtendimento={setFase}
        onEscolher={() => {}}
        onAbrirDossie={onAbrirDossie}
        onAbrirAnalises={onAbrirAnalises}
      />
      {/* Só no pós-entrevista: durante a entrevista a chamada já está na coluna
        * da direita, e desenhá-la aqui também decodificaria o mesmo vídeo em
        * dois lugares. Sem chamada de pé o painel não desenha nada — metade dos
        * atendimentos é presencial. */}
      {fase === "pos-entrevista" && <ChamadaDoAtendimento />}
    </>
  );
}

/** A ferramenta original: lê um documento solto, sem vincular a nenhum caso. */
function AnaliseAvulsa() {
  const tipos = useTipos();
  const estadoModelo = useModelo();
  const { arquivo, previewUrl, resultado, processando, erro, escolher, limpar, processar } =
    useExtracao();

  return (
    <div className="grid min-w-0 grid-cols-[minmax(min(100%,320px),420px)_minmax(0,1fr)] items-start gap-5 max-[900px]:grid-cols-1">
      <PainelEnvio
        arquivo={arquivo}
        previewUrl={previewUrl}
        processando={processando}
        erro={erro}
        tipos={tipos}
        onEscolher={escolher}
        onExtrair={processar}
        onLimpar={limpar}
      />

      <Cartao titulo="Dados lidos">
        {processando ? (
          <ProgressoOcr modeloPronto={estadoModelo === "pronto"} />
        ) : resultado ? (
          <Resultado doc={resultado} />
        ) : (
          <Vazio>
            Escolha um documento ao lado para começar.
            <div className="flex gap-[6px] justify-center flex-wrap mt-3">
              {["CPF", "RG", "CIN", "CNH", "CTPS", "Título de eleitor", "Cartão SUS", "Comprovante de residência"].map(
                (tipo) => (
                  <Selo key={tipo} tom="neutro">
                    {tipo}
                  </Selo>
                ),
              )}
            </div>
          </Vazio>
        )}
      </Cartao>
    </div>
  );
}
