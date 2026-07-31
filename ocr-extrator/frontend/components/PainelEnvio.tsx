"use client";

import { useEffect, useRef, useState } from "react";

import { tamanhoLegivel } from "@/lib/formato";
import type { TipoDocumento } from "@/lib/types";
import estilos from "./PainelEnvio.module.css";
import ui from "./ui.module.css";

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
    <div className={ui.card}>
      <h2 className={ui.tituloCard}>Documento</h2>

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
        aria-label="Selecionar imagem do documento"
      >
        <div className={estilos.icone}>📤</div>
        <p className={estilos.chamada}>Arraste a imagem aqui</p>
        <small className={estilos.dica}>
          ou clique para escolher · cole com Ctrl+V · JPG, PNG, WEBP, TIFF · até 20MB
        </small>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
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

      {arquivo && (
        <div className={estilos.infoArquivo}>
          {arquivo.name} · {tamanhoLegivel(arquivo.size)}
        </div>
      )}

      {erro && <div className={estilos.erro}>{erro}</div>}

      <label className={estilos.rotulo} htmlFor="tipo">
        Tipo do documento
      </label>
      <select
        id="tipo"
        className={estilos.select}
        value={tipo}
        onChange={(e) => setTipo(e.target.value)}
      >
        <option value="auto">Detectar automaticamente</option>
        {tipos.map((t) => (
          <option key={t.codigo} value={t.codigo}>
            {t.descricao}
          </option>
        ))}
      </select>

      <label className={estilos.rotulo} htmlFor="idioma">
        Idioma do OCR
      </label>
      <select
        id="idioma"
        className={estilos.select}
        value={idioma}
        onChange={(e) => setIdioma(e.target.value)}
      >
        <option value="pt">Português</option>
        <option value="latin">Latin (genérico)</option>
        <option value="en">Inglês</option>
      </select>

      <div className={estilos.botoes}>
        <button
          type="button"
          className={estilos.primario}
          disabled={!arquivo || processando}
          onClick={() => onExtrair(idioma, tipo)}
        >
          {processando ? "Processando…" : "Extrair dados"}
        </button>
        <button
          type="button"
          className={estilos.secundario}
          onClick={onLimpar}
          disabled={processando}
        >
          Limpar
        </button>
      </div>
    </div>
  );
}
