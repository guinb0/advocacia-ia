"use client";

/* O desenho de cada tela: o que vai DENTRO da moldura.
 *
 * Moldura (largura), navegação do caso e cabeçalho vêm do registro
 * (`lib/telas.ts`) e são aplicados em `home.view.tsx`. Aqui fica só o componente
 * e as props que ele recebe. `Record<Tela, …>` faz o TypeScript cobrar a entrada
 * de toda tela nova.
 */

import { useState, type ReactNode } from "react";

import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import AgenteGeral from "@/components/AgenteGeral";
import Carteira from "@/components/carteira/Carteira";
import Chat from "@/components/chat/Chat";
import Dados from "@/components/caso/Dados";
import DocumentacaoGuiada from "@/components/caso/DocumentacaoGuiada";
import Dossie from "@/components/admin/Dossie";
import Investigacao from "@/components/carteira/Investigacao";
import Jurimetria from "@/components/admin/Jurimetria";
import ListaCasos from "@/components/carteira/ListaCasos";
import NovoCaso from "@/components/carteira/NovoCaso";
import PainelCaso from "@/components/caso/PainelCaso";
import Panorama from "@/components/Panorama";
import Operacao from "@/components/operacao/Operacao";
import PainelEnvio from "@/components/caso/PainelEnvio";
import ProgressoOcr from "@/components/ui/ProgressoOcr";
import ChamadaDoAtendimento from "@/components/chamada/ChamadaDoAtendimento";
import TriagemEntrevista from "@/components/entrevista/TriagemEntrevista";
import Supervisao from "@/components/admin/Supervisao";
import SaudeAgente from "@/components/SaudeAgente";
import PainelGastosApi from "@/components/admin/PainelGastosApi";
import ModelosDePeticao from "@/components/ModelosDePeticao";
import ConfiguracaoAssinatura from "@/components/admin/ConfiguracaoAssinatura";
import FollowUp from "@/components/admin/FollowUp";
import Usuarios from "@/components/admin/Usuarios";
import Resultado from "@/components/caso/Resultado";
import CentralDocumentacao from "@/components/documentacao/CentralDocumentacao";
import CatalogoRoteiros from "@/components/admin/CatalogoRoteiros";
import GlossarioDocumentos from "@/components/admin/GlossarioDocumentos";
import TiposDeCaso from "@/components/admin/TiposDeCaso";
import PainelSkills from "@/components/skills/PainelSkills";
import type { useSessao } from "@/lib/auth";
import { ehTela, type Tela } from "@/lib/telas";
import type { useCasos, useCategorias } from "@/lib/useCasos";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";

import type { useHomeModel } from "./home.model";

export type ContextoTela = ReturnType<typeof useHomeModel> & {
  sessao: ReturnType<typeof useSessao>;
  /** O caso em foco. Telas com `precisaCaso` só são desenhadas com ele preenchido. */
  casoId: string;
};

type DesenhoTela = (contexto: ContextoTela) => ReactNode;

export const DESENHO_DA_TELA: Record<Tela, DesenhoTela> = {
  carteira: (c) => (
    <Carteira onAbrir={c.abrirCaso} onNovoCaso={c.novoCaso} onNavegar={c.setTela} />
  ),

  /* O chat não pede caso aberto — e é a única tela que não pede NADA: ele existe para
   * a pergunta que se faz antes de saber onde procurar. Os atalhos da resposta é que
   * levam ao caso, ao checklist ou ao painel. */
  chat: (c) => (
    <Chat
      onAbrirCaso={c.abrirDossie}
      onNavegar={(destino, casoId) => {
        if (casoId) {
          if (destino === "dossie") c.abrirDossie(casoId);
          else c.abrirCaso(casoId);
          return;
        }
        if (ehTela(destino)) c.setTela(destino);
      }}
    />
  ),

  /* O agente geral não pede caso aberto: ele é justamente a conversa de quem ainda não
   * sabe qual caso abrir. Da resposta se salta para o dossiê do caso citado. */
  agente: (c) => <AgenteGeral onVoltar={c.voltarParaCarteira} onAbrirCaso={c.abrirCaso} />,

  /* `key` no caso: o dossiê inteiro (minuta, histórico de versões e o chat da
   * petição) é estado de UM caso. Trocar de caso sem sair da tela — que é o que o
   * voltar/avançar do navegador faz, já que a navegação aqui é por estado — só
   * trocava a prop, e a árvore seguia mostrando o caso anterior até cada pedaço
   * recarregar. Remontar é o que garante tela limpa. */
  dossie: (c) => <Dossie key={c.casoId} casoId={c.casoId} onVoltar={c.voltarParaCarteira} />,
  jurimetria: (c) => <Jurimetria casoId={c.casoId} onVoltar={c.voltarParaCarteira} />,
  painel: (c) => <PainelCaso casoId={c.casoId} onVoltar={c.voltarParaCarteira} />,

  caso: (c) => <ChecklistDoCaso {...c} />,

  investigacao: (c) => <Investigacao onVoltar={c.voltarParaCarteira} />,
  usuarios: (c) => <Usuarios onVoltar={c.voltarParaCarteira} />,
  documentacao: (c) => (
    <CentralDocumentacao onVoltar={c.voltarParaCarteira} onAbrirDocumentos={c.abrirCaso} />
  ),
  supervisao: (c) => <Supervisao onVoltar={c.voltarParaCarteira} />,
  /* O panorama não pede caso aberto — é justamente a tela de quem não quer abrir
   * caso nenhum. Da lista de parados ele salta direto para o caso citado. */
  panorama: (c) => <Panorama onVoltar={c.voltarParaCarteira} onAbrirCaso={c.abrirCaso} />,
  operacao: () => <Operacao />,
  saudeAgente: (c) => <SaudeAgente onVoltar={c.voltarParaCarteira} />,
  gastosApi: (c) => <PainelGastosApi onVoltar={c.voltarParaCarteira} />,
  revisao: (c) => <Supervisao onVoltar={c.voltarParaCarteira} />,
  followup: () => <FollowUp />,
  modelosDePeticao: (c) => <ModelosDePeticao onVoltar={c.voltarParaCarteira} />,
  configuracaoAssinatura: () => <ConfiguracaoAssinatura />,
  catalogoRoteiros: (c) => <CatalogoRoteiros onVoltar={c.voltarParaCarteira} />,
  glossarioDocumentos: (c) => <GlossarioDocumentos onVoltar={c.voltarParaCarteira} />,
  tiposDeCaso: (c) => <TiposDeCaso onVoltar={c.voltarParaCarteira} />,
  skills: (c) => (
    <PainelSkills skillId={c.skillAberta} onAbrir={c.abrirSkill} onVoltar={c.voltarParaCarteira} />
  ),
  dados: (c) => <Dados onVoltar={c.voltarParaCarteira} />,

  casos: (c) =>
    c.criandoCaso ? (
      <NovoCaso
        categorias={c.categorias}
        onCriar={c.listaCasos.criar}
        onImportarZip={c.listaCasos.importarZip}
        onAbrir={c.abrirCaso}
        onAbrirDossie={c.abrirDossie}
        onCancelar={c.fecharNovoCaso}
      />
    ) : (
      <ListaCasos
        casos={c.listaCasos.casos}
        categorias={c.categorias}
        carregando={c.listaCasos.carregando}
        erro={c.listaCasos.erro}
        onAbrir={c.abrirCaso}
        onNovoCaso={c.novoCaso}
        onExcluir={c.listaCasos.excluir}
      />
    ),
  entrevista: (c) => (
    <EntrevistaGuiada
      categorias={c.categorias}
      onCriar={c.listaCasos.criar}
      onAbrirDossie={c.abrirDossie}
      onAbrirAnalises={c.abrirAnalises}
    />
  ),
  avulso: () => <AnaliseAvulsa />,
};

function ChecklistDoCaso({
  sessao,
  situacaoCaso,
  categorias,
  voltarParaCarteira,
}: ContextoTela) {
  const situacao = situacaoCaso.situacao;
  return (
    <>
      {sessao.modulos.includes("documentacao") && <ChamadaDoAtendimento modo="documentacao" />}
      {situacao ? (
        <>
          <DocumentacaoGuiada
            situacao={situacao}
            enviando={situacaoCaso.enviando}
            erro={situacaoCaso.erro}
            onVoltar={voltarParaCarteira}
            onEnviar={situacaoCaso.enviar}
            onEnviarLote={situacaoCaso.enviarLote}
            onRemover={situacaoCaso.removerEntrega}
            onVincularIdentidade={situacaoCaso.vincularIdentidade}
            onReatribuir={situacaoCaso.reatribuir}
            categorias={categorias}
            onTrocarCategoria={situacaoCaso.trocarCategoria}
          />
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
    </>
  );
}

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
