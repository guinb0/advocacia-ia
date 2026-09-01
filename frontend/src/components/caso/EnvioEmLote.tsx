"use client";

import { useRef, useState } from "react";

import { Botao, Selo } from "@/components/ui/Basicos";

const LIMITE = 30;

interface Props {
  onEnviar: (arquivos: File[]) => Promise<void> | void;
  enviando?: boolean;
  compacto?: boolean;
}

function chave(arquivo: File): string {
  return `${arquivo.name}:${arquivo.size}:${arquivo.lastModified}`;
}

export default function EnvioEmLote({ onEnviar, enviando = false, compacto = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [arrastando, setArrastando] = useState(false);

  function acrescentar(novos: File[]) {
    setArquivos((atuais) => {
      const vistos = new Set(atuais.map(chave));
      const unicos = novos.filter((arquivo) => {
        const id = chave(arquivo);
        if (vistos.has(id)) return false;
        vistos.add(id);
        return true;
      });
      return [...atuais, ...unicos].slice(0, LIMITE);
    });
  }

  async function confirmar() {
    if (!arquivos.length || enviando) return;
    await onEnviar(arquivos);
    setArquivos([]);
  }

  return (
    <section
      className={`${compacto ? "p-4" : "p-5"} border border-acao-borda rounded-cartao bg-acao-clara`}
      aria-labelledby="titulo-envio-lote"
    >
      <div className="flex justify-between gap-3 items-start flex-wrap">
        <div>
          <h2 id="titulo-envio-lote" className="m-0 text-tinta font-titulo text-lg font-semibold">
            Enviar vários documentos de uma vez
          </h2>
          <p className="mt-1 mb-0 max-w-[70ch] text-tinta-2 text-sm leading-[1.55]">
            Selecione arquivos de qualquer tipo sem escolher o documento. Imagens e PDFs serão
            lidos automaticamente; os demais formatos serão preservados para conferência.
          </p>
        </div>
        <Selo tom="info">até {LIMITE} arquivos</Selo>
      </div>

      <button
        type="button"
        className={`w-full mt-4 px-4 ${compacto ? "py-5" : "py-7"} border-2 border-dashed rounded-campo bg-papel text-tinta-2 text-sm cursor-pointer transition-colors hover:border-acao hover:text-acao ${
          arrastando ? "border-acao text-acao bg-papel-2" : "border-acao-borda"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(evento) => { evento.preventDefault(); setArrastando(true); }}
        onDragOver={(evento) => evento.preventDefault()}
        onDragLeave={() => setArrastando(false)}
        onDrop={(evento) => {
          evento.preventDefault();
          setArrastando(false);
          acrescentar(Array.from(evento.dataTransfer.files));
        }}
        disabled={enviando}
      >
        <strong>Escolher arquivos</strong>
        <span className="block mt-1 text-tinta-3">ou arraste os arquivos para esta área</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(evento) => {
          acrescentar(Array.from(evento.target.files ?? []));
          evento.target.value = "";
        }}
      />

      {arquivos.length > 0 && (
        <div className="mt-3">
          <div className="flex justify-between gap-3 items-center flex-wrap">
            <span className="text-tinta text-sm font-medium">
              {arquivos.length} {arquivos.length === 1 ? "arquivo selecionado" : "arquivos selecionados"}
            </span>
            <Botao variante="texto" pequeno onClick={() => setArquivos([])} disabled={enviando}>
              Limpar seleção
            </Botao>
          </div>
          <ul className="max-h-32 overflow-y-auto mt-2 mb-0 p-0 list-none border border-borda rounded-campo bg-papel">
            {arquivos.map((arquivo) => (
              <li key={chave(arquivo)} className="px-3 py-2 border-b border-borda last:border-b-0 text-xs text-tinta-2 [overflow-wrap:anywhere]">
                {arquivo.name}
              </li>
            ))}
          </ul>
          <Botao variante="primario" bloco className="mt-3" onClick={() => void confirmar()} disabled={enviando}>
            {enviando ? "Recebendo arquivos…" : `Enviar ${arquivos.length} arquivo(s)`}
          </Botao>
        </div>
      )}
    </section>
  );
}
