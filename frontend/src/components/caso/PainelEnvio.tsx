"use client";

import { useEffect, useRef, useState } from "react";

import { tamanhoLegivel } from "@/lib/formato";
import type { TipoDocumento } from "@/lib/types";
import { AjudaCampo, Aviso, Botao, CampoSeletor, Cartao, RotuloCampo } from "@/components/ui/Basicos";

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

const ZONA_BASE =
  "p-[28px_18px] border-2 border-dashed rounded-campo text-center cursor-pointer " +
  "transition-[border-color,background-color] duration-[120ms] ease-[ease]";
const ZONA_RESTING = "border-borda-campo bg-papel-2 hover:border-acao hover:bg-acao-clara";
const ZONA_ATIVA = "border-acao bg-acao-clara";

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
    <Cartao
      titulo="1. Escolha o documento"
      subtitulo="Uma foto ou um PDF do documento. Nada aqui fica vinculado a um caso — é só para ler e conferir os dados."
    >
      <div
        className={`${ZONA_BASE} ${arrastando ? ZONA_ATIVA : ZONA_RESTING}`}
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
        <div className="text-[30px] leading-none" aria-hidden>
          📄
        </div>
        <p className="mt-[10px] mb-[3px] text-tinta text-base font-semibold">
          Clique aqui para escolher o arquivo
        </p>
        <small className="block max-w-[44ch] mx-auto text-tinta-3 text-xs leading-[1.5]">
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
        <div className="mt-[14px]">
          {/* <img> comum em vez de next/image: é um blob local, sem otimização a fazer. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="block w-full border border-borda rounded-campo"
            src={previewUrl}
            alt="Pré-visualização do documento enviado"
          />
        </div>
      )}

      {arquivo && pdfSelecionado && (
        <div className="mt-[14px] p-[13px] border border-borda rounded-campo bg-papel-2 text-tinta-2 text-xs text-center">
          PDF selecionado — as páginas serão convertidas antes da leitura.
        </div>
      )}

      {arquivo && (
        <div className="mt-[9px] text-tinta-3 text-xs [overflow-wrap:anywhere] text-center">
          {arquivo.name} · {tamanhoLegivel(arquivo.size)}
        </div>
      )}

      {erro && (
        <div className="mt-[14px]">
          <Aviso tom="critico" titulo="Não foi possível usar este arquivo">
            {erro}
          </Aviso>
        </div>
      )}

      <div className="mt-4">
        <RotuloCampo htmlFor="tipo">Tipo do documento</RotuloCampo>
        <CampoSeletor id="tipo" value={tipo} onChange={(e) => setTipo(e.target.value)}>
          <option value="auto">Descobrir automaticamente (recomendado)</option>
          {tipos.map((t) => (
            <option key={t.codigo} value={t.codigo}>
              {t.descricao}
            </option>
          ))}
        </CampoSeletor>
        <AjudaCampo>
          Só escolha o tipo à mão se a leitura automática estiver identificando errado.
        </AjudaCampo>
      </div>

      <div className="mt-4">
        <RotuloCampo htmlFor="idioma">Idioma do documento</RotuloCampo>
        <CampoSeletor id="idioma" value={idioma} onChange={(e) => setIdioma(e.target.value)}>
          <option value="pt">Português</option>
          <option value="latin">Outro idioma com alfabeto latino</option>
          <option value="en">Inglês</option>
        </CampoSeletor>
      </div>

      <div className="flex gap-[10px] mt-5">
        <Botao
          variante="primario"
          className="flex-1"
          disabled={!arquivo || processando}
          onClick={() => onExtrair(idioma, tipo)}
        >
          {processando ? "Lendo o documento…" : "2. Ler o documento"}
        </Botao>
        <Botao variante="discreto" onClick={onLimpar} disabled={processando}>
          Limpar
        </Botao>
      </div>
    </Cartao>
  );
}
