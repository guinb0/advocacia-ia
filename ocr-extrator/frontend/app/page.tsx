"use client";

import { useState } from "react";

import Carteira from "@/components/Carteira";
import Checklist from "@/components/Checklist";
import ListaCasos from "@/components/ListaCasos";
import PainelEnvio from "@/components/PainelEnvio";
import ProgressoOcr from "@/components/ProgressoOcr";
import Resultado from "@/components/Resultado";
import ui from "@/components/ui.module.css";
import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";
import estilos from "./page.module.css";

/** A carteira é a porta de entrada; as outras telas são destinos dela. */
type Tela = "carteira" | "caso" | "casos" | "avulso";

export default function Home() {
  const [tela, setTela] = useState<Tela>("carteira");
  const [casoAberto, setCasoAberto] = useState<string | null>(null);

  const categorias = useCategorias();
  const listaCasos = useCasos();
  const situacaoCaso = useSituacao(casoAberto);

  function abrirCaso(casoId: string) {
    setCasoAberto(casoId);
    setTela("caso");
  }

  function voltarParaCarteira() {
    setCasoAberto(null);
    setTela("carteira");
    void listaCasos.recarregar();
  }

  if (tela === "carteira") {
    return (
      <Carteira
        onAbrir={abrirCaso}
        onNovoCaso={() => setTela("casos")}
        onAnalisarAvulso={() => setTela("avulso")}
      />
    );
  }

  if (tela === "caso") {
    return (
      <div className={estilos.container}>
        {situacaoCaso.situacao ? (
          <Checklist
            situacao={situacaoCaso.situacao}
            enviando={situacaoCaso.enviando}
            erro={situacaoCaso.erro}
            onVoltar={voltarParaCarteira}
            onEnviar={situacaoCaso.enviar}
            onRemover={situacaoCaso.removerEntrega}
            onVincularIdentidade={situacaoCaso.vincularIdentidade}
          />
        ) : (
          <div className={ui.vazio}>
            {situacaoCaso.erro ? (
              <span style={{ color: "var(--accent)" }}>{situacaoCaso.erro}</span>
            ) : (
              "Carregando o caso…"
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={estilos.container}>
      <button type="button" className={estilos.voltar} onClick={voltarParaCarteira}>
        ← Carteira
      </button>

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
      ) : (
        <AnaliseAvulsa />
      )}
    </div>
  );
}

/** A ferramenta original: lê um documento solto, sem vincular a nenhum caso. */
function AnaliseAvulsa() {
  const tipos = useTipos();
  const estadoModelo = useModelo();
  const { arquivo, previewUrl, resultado, processando, erro, escolher, limpar, processar } =
    useExtracao();

  return (
    <div className={estilos.grade}>
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

      <div className={ui.card}>
        <h2 className={ui.tituloCard}>Resultado</h2>

        {processando ? (
          <ProgressoOcr modeloPronto={estadoModelo === "pronto"} />
        ) : resultado ? (
          <Resultado doc={resultado} />
        ) : (
          <div className={ui.vazio}>
            Envie a foto de um documento para começar.
            <br />
            <small>
              CPF · RG · CIN · CNH · CTPS · Título de eleitor · Cartão SUS · Comprovante de
              residência
            </small>
          </div>
        )}
      </div>
    </div>
  );
}
