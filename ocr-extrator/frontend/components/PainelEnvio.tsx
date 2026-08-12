"use client";

import { useEffect, useRef, useState } from "react";

import { tamanhoLegivel } from "@/lib/formato";
import type { TipoDocumento } from "@/lib/types";
import { Aviso } from "./Basicos";
import estilos from "./PainelEnvio.module.css";

interface Props {
  arquivo: File | null;
  previewUrl: string | null;
  processando: boolean;
  erro: string | null;
  tipos: TipoDocumento[];
  onEscolher: (arquivo: File | null) => void;
  onExtrair: (idioma: string, tipo: string) => void;
  onLimpar: () => void;
}

export default function PainelEnvio({
  arquivo,
  previewUrl,
  processando,
  erro,
  tipos,
  onEscolher,
  onExtrair,
  onLimpar,
}: Props) {
  const [tipo, setTipo] = useState("auto");
  const [idioma, setIdioma] = useState("pt");
  const [arrastando, setArrastando] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pdfSelecionado = arquivo?.type === "application/pdf" || arquivo?.name.toLowerCase().endsWith(".pdf");

  // Colar print da tela (Ctrl+V) é o caminho mais rápido para testar.
  useEffect(() => {
    function aoColar(evento: ClipboardEvent) {
      const item = Array.from(evento.clipboardData?.items ?? []).find((i) =>
        i.type.startsWith("image/"),
      );
      if (item) onEscolher(item.getAsFile());
    }
    window.addEventListener("paste", aoColar);
    return () => window.removeEventListener("paste", aoColar);
  }, [onEscolher]);

  function selecionarArquivo() {
    inputRef.current?.click();
  }

  return (
    <div className="cartao">
      <h2 className="tituloCartao">1. Escolha o documento</h2>
      <p className="subtituloCartao">
        Uma foto ou um PDF do documento. Nada aqui fica vinculado a um caso — é só para ler e
        conferir os dados.
      </p>

      <div
        className={`${estilos.zona} ${arrastando ? estilos.zonaAtiva : ""}`}
        onClick={selecionarArquivo}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            selecionarArquivo();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastando(false);
          onEscolher(e.dataTransfer.files[0] ?? null);
        }}
        role="button"
        tabIndex={0}
        aria-label="Selecionar imagem ou PDF do documento"
      >
        <div className={estilos.icone} aria-hidden>
          📄
        </div>
        <p className={estilos.chamada}>Clique aqui para escolher o arquivo</p>
        <small className={estilos.dica}>
          Também é possível arrastar o arquivo até aqui ou colar uma imagem com Ctrl+V. Aceita JPG,
          PNG, WEBP, TIFF e PDF, até 20 MB.
        </small>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*,application/pdf,.pdf"
        hidden
        onChange={(e) => onEscolher(e.target.files?.[0] ?? null)}
      />

      {previewUrl && (
        <div className={estilos.preview}>
          {/* <img> comum em vez de next/image: é um blob local, sem otimização a fazer. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={previewUrl} alt="Pré-visualização do documento enviado" />
        </div>
      )}

      {arquivo && pdfSelecionado && (
        <div className={estilos.previewPdf}>
          PDF selecionado — as páginas serão convertidas antes da leitura.
        </div>
      )}

      {arquivo && (
        <div className={estilos.infoArquivo}>
          {arquivo.name} · {tamanhoLegivel(arquivo.size)}
        </div>
      )}

      {erro && (
        <div style={{ marginTop: 14 }}>
          <Aviso tom="critico" titulo="Não foi possível usar este arquivo">
            {erro}
          </Aviso>
        </div>
      )}

      <div className={estilos.grupoCampo}>
        <label className="rotuloCampo" htmlFor="tipo">
          Tipo do documento
        </label>
        <select
          id="tipo"
          className="campo campo--seletor"
          value={tipo}
          onChange={(e) => setTipo(e.target.value)}
        >
          <option value="auto">Descobrir automaticamente (recomendado)</option>
          {tipos.map((t) => (
            <option key={t.codigo} value={t.codigo}>
              {t.descricao}
            </option>
          ))}
        </select>
        <p className="ajudaCampo">
          Só escolha o tipo à mão se a leitura automática estiver identificando errado.
        </p>
      </div>

      <div className={estilos.grupoCampo}>
        <label className="rotuloCampo" htmlFor="idioma">
          Idioma do documento
        </label>
        <select
          id="idioma"
          className="campo campo--seletor"
          value={idioma}
          onChange={(e) => setIdioma(e.target.value)}
        >
          <option value="pt">Português</option>
          <option value="latin">Outro idioma com alfabeto latino</option>
          <option value="en">Inglês</option>
        </select>
      </div>

      <div className={estilos.botoes}>
        <button
          type="button"
          className="botao botao--primario"
          disabled={!arquivo || processando}
          onClick={() => onExtrair(idioma, tipo)}
        >
          {processando ? "Lendo o documento…" : "2. Ler o documento"}
        </button>
        <button
          type="button"
          className="botao botao--discreto"
          onClick={onLimpar}
          disabled={processando}
        >
          Limpar
        </button>
      </div>
    </div>
  );
}
