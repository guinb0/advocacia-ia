"use client";

import { useState } from "react";

import { baixarDocumentosDoCaso } from "@/lib/api";
import { Aviso } from "@/components/ui/Basicos";

/* Tudo que o cliente enviou, num pacote só.
 *
 * Antes disto o escritório baixava documento por documento, clicando linha por
 * linha do checklist: trinta arquivos, trinta cliques, e a certeza de esquecer
 * um. O pacote sai na ordem do checklist e com o nome do item em cada arquivo,
 * porque do outro lado alguém confere contra a mesma lista.
 *
 * O download vai por `fetch` e não por um link direto: o link cru não manda o
 * Bearer, e o que desceria seria um 401 salvo em disco com nome de .zip — o
 * atendente só descobriria ao tentar abrir. */

interface Props {
  casoId: string;
  /** Quantos documentos distintos o caso já tem. Zero: não há o que baixar. */
  total: number;
  /** O checklist fechou — é quando o escritório vem buscar o pacote. */
  pronto: boolean;
}

const BASE_BOTAO =
  "border border-tinta px-[14px] py-[10px] bg-transparent text-tinta text-[10px] font-semibold leading-none " +
  "font-ui tracking-[0.06em] uppercase cursor-pointer disabled:cursor-not-allowed " +
  "disabled:border-borda-forte disabled:bg-papel-3 disabled:text-tinta-desabilitada";

export default function BaixarDocumentos({ casoId, total, pronto }: Props) {
  const [baixando, setBaixando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [faltando, setFaltando] = useState(0);

  if (total === 0) return null;

  async function baixar() {
    setBaixando(true);
    setErro(null);
    setFaltando(0);
    try {
      const pacote = await baixarDocumentosDoCaso(casoId);
      setFaltando(pacote.faltando);

      /* O clique programático é o que faz o navegador salvar um blob que veio
       * por `fetch`. Sem revogar a URL depois, cada download deixa o ZIP
       * inteiro preso na memória da aba até alguém recarregar a página — e
       * aqui são centenas de megabytes de digitalização. */
      const url = URL.createObjectURL(pacote.arquivo);
      const link = document.createElement("a");
      link.href = url;
      link.download = pacote.nome;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível montar o pacote.");
    } finally {
      setBaixando(false);
    }
  }

  return (
    <section className="mt-4">
      <div className="flex items-center flex-wrap gap-3 max-[640px]:items-stretch max-[640px]:flex-col">
        <button
          type="button"
          className={pronto ? `${BASE_BOTAO} bg-tinta text-papel` : `${BASE_BOTAO} enabled:hover:bg-papel-2`}
          onClick={() => void baixar()}
          disabled={baixando}
        >
          {baixando ? "Montando o pacote…" : `Baixar os ${total} documentos (.zip)`}
        </button>
        <span className="italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
          {pronto
            ? "O checklist fechou — este é o pacote para a inicial."
            : "O que já chegou, na ordem do checklist."}
        </span>
      </div>

      {/* Pacote incompleto que desce calado é pior que erro: ninguém confere o
        * que não sabe que faltou. */}
      {faltando > 0 && (
        <div className="mt-3">
          <Aviso tom="atencao" titulo="O pacote saiu incompleto">
            {faltando} {faltando === 1 ? "arquivo constava" : "arquivos constavam"} no caso
            mas não {faltando === 1 ? "está" : "estão"} mais no disco. Confira o checklist
            antes de protocolar.
          </Aviso>
        </div>
      )}

      {erro && (
        <div className="mt-3">
          <Aviso tom="critico" titulo="Não foi possível baixar">
            {erro}
          </Aviso>
        </div>
      )}
    </section>
  );
}
