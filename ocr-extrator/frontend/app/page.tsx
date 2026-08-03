"use client";

import { useState } from "react";

import Checklist from "@/components/Checklist";
import ListaCasos from "@/components/ListaCasos";
import PainelEnvio from "@/components/PainelEnvio";
import Resultado from "@/components/Resultado";
import ui from "@/components/ui.module.css";
import { useCasos, useCategorias, useSituacao } from "@/lib/useCasos";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";
import type { EstadoModelo } from "@/lib/useExtracao";
import estilos from "./page.module.css";

const TEXTO_STATUS: Record<EstadoModelo, string> = {
  verificando: "verificando modelo…",
  carregando: "carregando modelo…",
  pronto: "modelo pronto",
  indisponivel: "modelo carrega no 1º envio",
};

type Aba = "casos" | "avulso";

export default function Home() {
  const [aba, setAba] = useState<Aba>("casos");
  const [casoAberto, setCasoAberto] = useState<string | null>(null);

  const estadoModelo = useModelo();
  const categorias = useCategorias();
  const listaCasos = useCasos();
  const situacaoCaso = useSituacao(casoAberto);

  const classeBolinha =
    estadoModelo === "pronto"
      ? estilos.bolinhaOk
      : estadoModelo === "indisponivel"
        ? estilos.bolinhaErro
        : estilos.bolinhaCarregando;

  return (
    <div className={estilos.container}>
      <header className={estilos.cabecalho}>
        <div className={estilos.logo}>📄</div>
        <h1 className={estilos.titulo}>Documentos do Cliente</h1>
        <div className={estilos.status}>
          <span className={`${estilos.bolinha} ${classeBolinha}`} />
          <span>{TEXTO_STATUS[estadoModelo]}</span>
        </div>
      </header>

      <p className={estilos.subtitulo}>
        Controle o que cada cliente já entregou, gere o pedido do que ainda falta e confira a
        legibilidade de cada documento na hora em que ele chega.
      </p>

      <div className={ui.abas} role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={aba === "casos"}
          className={`${ui.aba} ${aba === "casos" ? ui.abaAtiva : ""}`}
          onClick={() => setAba("casos")}
        >
          Casos
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={aba === "avulso"}
          className={`${ui.aba} ${aba === "avulso" ? ui.abaAtiva : ""}`}
          onClick={() => setAba("avulso")}
        >
          Analisar documento avulso
        </button>
      </div>

      {aba === "avulso" ? (
        <AnaliseAvulsa />
      ) : casoAberto && situacaoCaso.situacao ? (
        <Checklist
          situacao={situacaoCaso.situacao}
          enviando={situacaoCaso.enviando}
          erro={situacaoCaso.erro}
          onVoltar={() => {
            setCasoAberto(null);
            void listaCasos.recarregar();
          }}
          onEnviar={situacaoCaso.enviar}
          onRemover={situacaoCaso.removerEntrega}
        />
      ) : casoAberto ? (
        <div className={ui.card}>
          <div className={ui.vazio}>
            {situacaoCaso.erro ? (
              <span style={{ color: "var(--err)" }}>{situacaoCaso.erro}</span>
            ) : (
              "Carregando o caso…"
            )}
          </div>
        </div>
      ) : (
        <ListaCasos
          casos={listaCasos.casos}
          categorias={categorias}
          carregando={listaCasos.carregando}
          erro={listaCasos.erro}
          onAbrir={setCasoAberto}
          onCriar={listaCasos.criar}
          onExcluir={listaCasos.excluir}
        />
      )}
    </div>
  );
}

/** A ferramenta original: lê um documento solto, sem vincular a nenhum caso. */
function AnaliseAvulsa() {
  const tipos = useTipos();
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
          <div className={estilos.carregando}>
            <div className={estilos.spinner} />
            <div>Processando…</div>
            <small>a primeira execução carrega os modelos e pode demorar</small>
          </div>
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
