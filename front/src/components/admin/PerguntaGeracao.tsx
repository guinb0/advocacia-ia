"use client";

/**
 * A pergunta que abre ao clicar em "Gerar petição": só a peça, ou a peça e o
 * pacote para protocolo. Em portal, porque o botão também mora no cabeçalho do
 * dossiê, longe do cartão da petição.
 */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { FileArchive, FileText, X } from "lucide-react";

import { Aviso, Botao } from "@/components/ui/Basicos";

type Props = {
  /** Versão da minuta que já existe; gerar de novo cria outra por cima. */
  versaoExistente: number | null;
  onEscolher: (comProtocolo: boolean) => void;
  onCancelar: () => void;
};

export default function PerguntaGeracao({ versaoExistente, onEscolher, onCancelar }: Props) {
  const primeiro = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    primeiro.current?.focus();
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape") onCancelar();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onCancelar]);

  const opcao =
    "flex w-full cursor-pointer items-start gap-3 rounded-campo border px-4 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acao";

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-tinta/40 p-3 sm:p-6"
      onMouseDown={(evento) => {
        if (evento.target === evento.currentTarget) onCancelar();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="titulo-pergunta-geracao"
        className="grid w-full max-w-lg gap-4 rounded-cartao border border-borda-forte bg-papel p-5 shadow-cartao"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id="titulo-pergunta-geracao" className="m-0 font-titulo text-lg font-semibold text-tinta">
            Gerar ZIP com os documentos prontos para protocolo também?
          </h2>
          <button
            type="button"
            aria-label="Cancelar"
            onClick={onCancelar}
            className="rounded-campo p-1 text-tinta-3 hover:bg-papel-2 hover:text-tinta"
          >
            <X size={20} />
          </button>
        </div>

        {versaoExistente !== null && (
          <Aviso tom="atencao">
            Já existe uma minuta (versão {versaoExistente}). Gerar de novo usa tokens e cria uma nova versão.
          </Aviso>
        )}

        <div className="grid gap-2">
          <button
            ref={primeiro}
            type="button"
            className={`${opcao} border-acao-borda bg-acao-clara hover:border-acao`}
            onClick={() => onEscolher(true)}
          >
            <FileArchive size={22} className="mt-[2px] flex-none text-acao" aria-hidden />
            <span className="grid gap-1">
              <span className="text-sm font-semibold text-tinta">Sim, preparar para protocolo</span>
              <span className="text-xs leading-relaxed text-tinta-2">
                Depois que a petição ficar pronta, você confere os documentos sugeridos e baixa um .zip com tudo.
              </span>
            </span>
          </button>
          <button
            type="button"
            className={`${opcao} border-borda bg-papel hover:border-acao hover:bg-papel-2`}
            onClick={() => onEscolher(false)}
          >
            <FileText size={22} className="mt-[2px] flex-none text-tinta-3" aria-hidden />
            <span className="grid gap-1">
              <span className="text-sm font-semibold text-tinta">Não, gerar somente a petição</span>
              <span className="text-xs leading-relaxed text-tinta-2">
                Como sempre: a petição é gerada e o .docx é baixado.
              </span>
            </span>
          </button>
        </div>

        <div className="flex justify-end">
          <Botao variante="texto" pequeno onClick={onCancelar}>
            Cancelar
          </Botao>
        </div>
      </div>
    </div>,
    document.body,
  );
}
