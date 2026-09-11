"use client";

import { useEffect, useRef, useState } from "react";

import { Botao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

interface Props {
  onEnviar: (arquivos: File[]) => Promise<void> | void;
  enviando?: boolean;
  compacto?: boolean;
}

function chave(arquivo: File): string {
  // `webkitRelativePath` distingue dois "rg.jpg" vindos de subpastas diferentes.
  return `${arquivo.webkitRelativePath || arquivo.name}:${arquivo.size}:${arquivo.lastModified}`;
}

export default function EnvioEmLote({ onEnviar, enviando = false, compacto = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const pastaRef = useRef<HTMLInputElement>(null);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [arrastando, setArrastando] = useState(false);

  // `webkitdirectory` não existe no tipo do input; setar no elemento é o jeito
  // sem brigar com o TypeScript. Com ele, escolher a pasta traz todos os
  // arquivos de dentro (e das subpastas) de uma vez.
  useEffect(() => {
    if (pastaRef.current) {
      pastaRef.current.setAttribute("webkitdirectory", "");
      pastaRef.current.setAttribute("directory", "");
    }
  }, []);

  function acrescentar(novos: File[]) {
    setArquivos((atuais) => {
      const vistos = new Set(atuais.map(chave));
      const unicos = novos.filter((arquivo) => {
        const id = chave(arquivo);
        if (vistos.has(id)) return false;
        vistos.add(id);
        return true;
      });
      // Sem teto aqui: o envio parte em blocos, então toda a pasta é analisada.
      return [...atuais, ...unicos];
    });
  }

  async function confirmar() {
    if (!arquivos.length || enviando) return;
    await onEnviar(arquivos);
    setArquivos([]);
  }

  function limpar() {
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
            Selecione arquivos, uma <strong>pasta inteira</strong> ou um <strong>ZIP</strong> — sem
            escolher o documento de cada um. O ZIP é aberto automaticamente e{" "}
            <strong>todos os arquivos são analisados</strong>, por mais que sejam. Imagens e PDFs
            são lidos na hora; os demais formatos ficam preservados para conferência.
          </p>
        </div>
        <Selo tom="info">todos são analisados</Selo>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 max-[420px]:grid-cols-1">
        <button
          type="button"
          className={`px-4 ${compacto ? "py-5" : "py-7"} border-2 border-dashed rounded-campo bg-papel text-tinta-2 text-sm cursor-pointer transition-colors hover:border-acao hover:text-acao ${
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
          <strong>Escolher arquivos ou ZIP</strong>
          <span className="block mt-1 text-tinta-3">ou arraste para esta área</span>
        </button>
        <button
          type="button"
          className={`px-4 ${compacto ? "py-5" : "py-7"} border-2 border-dashed border-acao-borda rounded-campo bg-papel text-tinta-2 text-sm cursor-pointer transition-colors hover:border-acao hover:text-acao`}
          onClick={() => pastaRef.current?.click()}
          disabled={enviando}
        >
          <strong>Escolher uma pasta</strong>
          <span className="block mt-1 text-tinta-3">envia todos os arquivos dela</span>
        </button>
      </div>
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
      <input
        ref={pastaRef}
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
            <Botao variante="texto" pequeno onClick={limpar} disabled={enviando}>
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
          <BotaoProcesso
            variante="primario"
            bloco
            className="mt-3"
            onClick={confirmar}
            processando={enviando}
            textoProcessando="Recebendo arquivos…"
            dica={`Enviando ${arquivos.length} arquivo(s) — mantenha esta página aberta`}
          >
            Enviar {arquivos.length} arquivo(s)
          </BotaoProcesso>
        </div>
      )}
    </section>
  );
}
