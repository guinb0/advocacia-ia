"use client";

/**
 * Anexar o documento do escritório e receber o roteiro montado a partir dele.
 *
 * O roteiro de empregado público veio de um `.docx` transcrito à mão para
 * `app/roteiros.py`. Deu certo uma vez e não escala: cada categoria de causa tem
 * o seu documento, e transcrever 86 perguntas em código leva um dia.
 *
 * Aqui o advogado anexa o arquivo — `.docx`, PDF, ou a foto de uma folha
 * impressa — e recebe a PROPOSTA de roteiro. Proposta, e não roteiro pronto: o
 * modelo lê bem e erra de vez em quando, e o que sai daqui vai reger uma
 * entrevista inteira. Por isso a única saída deste painel é o editor.
 *
 * A leitura pode levar dois minutos (OCR, depois uma chamada ao modelo por
 * bloco), então a barra mostra a etapa em que está — "Perguntas de 'Assalto'
 * (4 de 9)" diz que está andando; um spinner não diz nada.
 */

import { useRef, useState } from "react";

import { importarRoteiro } from "@/lib/api";
import type { RoteiroImportado } from "@/lib/types";

const T_BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const T_SECUNDARIO =
  "border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.08em] uppercase px-3 py-[9px] cursor-pointer enabled:hover:bg-papel-2";
const T_ERRO =
  "border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui";

/** O que o backend aceita — ver `roteiro_ia.EXTENSOES_ROTEIRO`. */
const ACEITOS = ".txt,.md,.docx,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";

interface Props {
  /** Chamado com a proposta pronta. Quem recebe abre o editor. */
  aoImportar: (importado: RoteiroImportado) => void;
  aoFechar: () => void;
}

export default function ImportarRoteiro({ aoImportar, aoFechar }: Props) {
  const entrada = useRef<HTMLInputElement>(null);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [lendo, setLendo] = useState(false);
  const [pct, setPct] = useState(0);
  const [etapa, setEtapa] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  async function importar() {
    if (!arquivo) return;
    setLendo(true);
    setErro(null);
    setPct(0);
    setEtapa("Enviando o arquivo");
    try {
      const importado = await importarRoteiro(arquivo, (p, e) => {
        setPct(p);
        setEtapa(e);
      });
      aoImportar(importado);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setLendo(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-tinta/40 flex items-start justify-center overflow-y-auto p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Importar roteiro de um documento"
    >
      <div className="w-full max-w-[620px] bg-papel border border-borda-forte my-8">
        <div className="flex justify-between items-center gap-4 px-4 py-3 border-b border-borda-forte">
          <h2 className="m-0 font-semibold text-[19px] leading-[1.15] font-titulo">
            Roteiro a partir de um documento
          </h2>
          <button type="button" className={T_SECUNDARIO} onClick={aoFechar} disabled={lendo}>
            Fechar
          </button>
        </div>

        <div className="px-4 py-4">
          <p className="m-0 mb-4 text-[13px] leading-[1.55] font-ui text-tinta">
            Anexe o roteiro de entrevista do escritório. Arquivo com texto (
            <code>.docx</code>, PDF) é lido direto; PDF digitalizado e foto passam pelo
            OCR. O que sai é uma <strong>proposta</strong>, que abre no editor para você
            conferir antes de salvar.
          </p>

          <input
            ref={entrada}
            type="file"
            accept={ACEITOS}
            className="hidden"
            onChange={(e) => {
              setArquivo(e.target.files?.[0] ?? null);
              setErro(null);
            }}
          />

          <div className="flex gap-[10px] items-center flex-wrap">
            <button
              type="button"
              className={T_SECUNDARIO}
              onClick={() => entrada.current?.click()}
              disabled={lendo}
            >
              Escolher arquivo
            </button>
            <span className="text-[12px] font-ui text-tinta-3">
              {arquivo ? arquivo.name : "nenhum arquivo escolhido"}
            </span>
          </div>

          {lendo && (
            <div className="mt-4">
              <div className="h-[6px] bg-papel-2 border border-borda">
                <div
                  className="h-full bg-tinta transition-[width] duration-500"
                  style={{ width: `${Math.max(pct, 4)}%` }}
                />
              </div>
              <p className="m-0 mt-2 text-[11.5px] leading-[1.4] font-ui text-tinta-3">
                {etapa}
                {pct > 0 ? ` · ${pct}%` : ""}
              </p>
            </div>
          )}

          {erro && <div className={`${T_ERRO} mt-4`}>{erro}</div>}

          <div className="flex justify-end mt-5">
            <button
              type="button"
              className={T_BOTAO}
              onClick={() => void importar()}
              disabled={!arquivo || lendo}
            >
              {lendo ? "Montando o roteiro…" : "Montar roteiro"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
