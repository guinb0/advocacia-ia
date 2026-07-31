"use client";

import PainelEnvio from "@/components/PainelEnvio";
import Resultado from "@/components/Resultado";
import ui from "@/components/ui.module.css";
import { useExtracao, useModelo, useTipos } from "@/lib/useExtracao";
import type { EstadoModelo } from "@/lib/useExtracao";
import estilos from "./page.module.css";

const TEXTO_STATUS: Record<EstadoModelo, string> = {
  verificando: "verificando modelo…",
  carregando: "carregando modelo…",
  pronto: "modelo pronto",
  indisponivel: "modelo carrega no 1º envio",
};

export default function Home() {
  const estadoModelo = useModelo();
  const tipos = useTipos();
  const { arquivo, previewUrl, resultado, processando, erro, escolher, limpar, processar } =
    useExtracao();

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
        <h1 className={estilos.titulo}>Extrator de Documentos</h1>
        <div className={estilos.status}>
          <span className={`${estilos.bolinha} ${classeBolinha}`} />
          <span>{TEXTO_STATUS[estadoModelo]}</span>
        </div>
      </header>

      <p className={estilos.subtitulo}>
        OCR com PaddleOCR + validação de dígitos verificadores (CPF, PIS, CNH, título, CNS) e
        análise de legibilidade da foto.
      </p>

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
    </div>
  );
}
