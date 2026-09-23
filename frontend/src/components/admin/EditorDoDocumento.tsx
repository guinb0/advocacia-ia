"use client";

/**
 * O documento da petição, editável como no Word.
 *
 * Era um `<textarea>` por seção: dava para escrever, não para formatar. Quem
 * revisa uma peça precisa grifar um trecho, pôr um título no meio da página,
 * destacar um valor em vermelho — e fazia isso baixando o .docx, editando no
 * Word e perdendo o vínculo com o caso. Agora a barra de ferramentas aplica
 * negrito, itálico, sublinhado e alinhamento direto na peça.
 *
 * COMO A FORMATAÇÃO SOBREVIVE
 *
 * O estado continua sendo o texto da seção (ver `lib/formatacaoPeticao.ts`):
 * a formatação vira marcação dentro dele. Nada mais mudou de caminho — salvar,
 * revisar por prompt, comparar versões e baixar .docx/PDF seguem lendo texto.
 *
 * POR QUE `contentEditable` E NÃO UMA BIBLIOTECA
 *
 * O que se formata aqui cabe em `document.execCommand`: negrito, itálico,
 * sublinhado e alinhamento. Trazer um editor inteiro (TipTap e afins)
 * custaria o dobro do peso da tela para ganhar tabela e lista, que a peça já
 * resolve por outro caminho. `execCommand` está obsoleto no papel e implementado
 * em todos os navegadores — inclusive porque é ele que dá o Ctrl+B de graça.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, Underline } from "lucide-react";

import { paraHtml, paraTexto } from "@/lib/formatacaoPeticao";

export type EstadoDaSelecao = {
  negrito: boolean;
  italico: boolean;
  sublinhado: boolean;
};

function comandoPossivel(): boolean {
  return typeof document !== "undefined" && typeof document.execCommand === "function";
}

export function BarraDeFormatacao({
  ativo,
  aoAplicar,
}: {
  ativo: EstadoDaSelecao | null;
  /** Roda a ação sobre o campo em foco e avisa a tela do que mudou. */
  aoAplicar: (acao: (raiz: HTMLElement) => void) => void;
}) {
  const desabilitado = !ativo;
  const classe = (ligado?: boolean) =>
    `inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-campo border border-borda-campo px-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
      ligado ? "bg-acao text-nav-texto" : "bg-papel text-tinta hover:bg-papel-2"
    }`;

  return (
    /* `sticky`: a barra acompanha quem rola o documento. Sem isto, formatar um
       trecho do fim da peça obrigaria a subir até o topo a cada clique. */
    <div
      className="sticky top-0 z-10 -mx-1 mb-2 flex flex-wrap items-center gap-1 border-b border-borda bg-papel px-1 py-2"
      role="toolbar"
      aria-label="Formatação do texto"
      /* A barra não pode roubar o cursor: sem isto, clicar em "negrito" tira o
         foco do documento e a seleção que se queria formatar deixa de existir. */
      onMouseDown={(evento) => evento.preventDefault()}
    >
      <button
        type="button"
        className={classe(ativo?.negrito)}
        disabled={desabilitado}
        aria-pressed={ativo?.negrito ?? false}
        title="Negrito (Ctrl+B)"
        onClick={() => aoAplicar(() => document.execCommand("bold"))}
      >
        <Bold size={15} aria-hidden />
        <span className="sr-only">Negrito</span>
      </button>
      <button
        type="button"
        className={classe(ativo?.italico)}
        disabled={desabilitado}
        aria-pressed={ativo?.italico ?? false}
        title="Itálico (Ctrl+I)"
        onClick={() => aoAplicar(() => document.execCommand("italic"))}
      >
        <Italic size={15} aria-hidden />
        <span className="sr-only">Itálico</span>
      </button>
      <button
        type="button"
        className={classe(ativo?.sublinhado)}
        disabled={desabilitado}
        aria-pressed={ativo?.sublinhado ?? false}
        title="Sublinhado (Ctrl+U)"
        onClick={() => aoAplicar(() => document.execCommand("underline"))}
      >
        <Underline size={15} aria-hidden />
        <span className="sr-only">Sublinhado</span>
      </button>

      <span className="mx-1 h-5 w-px bg-borda" aria-hidden />

      {([
        ["justifyLeft", AlignLeft, "Alinhar à esquerda"],
        ["justifyCenter", AlignCenter, "Centralizar"],
        ["justifyRight", AlignRight, "Alinhar à direita"],
        ["justifyFull", AlignJustify, "Justificar"],
      ] as const).map(([comando, Icone, rotulo]) => (
        <button
          key={comando}
          type="button"
          className={classe()}
          disabled={desabilitado}
          title={rotulo}
          onClick={() => aoAplicar(() => document.execCommand(comando))}
        >
          <Icone size={15} aria-hidden />
          <span className="sr-only">{rotulo}</span>
        </button>
      ))}
    </div>
  );
}

/** Uma seção do documento, editável e formatável.
 *
 * A altura acompanha o conteúdo por natureza — é um `div`, não uma caixa com
 * rolagem própria. Caixa que rola dentro de página que também rola era o que
 * tornava a revisão penosa: dois scrolls concorrentes, e a pessoa perdia o
 * lugar entre eles.
 */
export function CampoDoDocumento({
  valor,
  rotulo,
  formato = "corpo",
  onEditar,
  onFoco,
}: {
  valor: string;
  rotulo: string;
  formato?: "corpo" | "fechamento" | "enderecamento";
  onEditar: (valor: string) => void;
  /** Avisa qual campo está sob o cursor, para a barra saber onde aplicar. */
  onFoco?: (campo: HTMLDivElement | null) => void;
}) {
  const campo = useRef<HTMLDivElement>(null);
  /** O último texto que ESTE campo produziu. Serve para distinguir a mudança que
   *  veio de quem digita (o HTML já está certo, mexer nele mataria o cursor) da
   *  que veio de fora — revisão por prompt, chat, desfazer — que precisa
   *  redesenhar o documento inteiro. */
  const ultimoEmitido = useRef<string | null>(null);

  useEffect(() => {
    const elemento = campo.current;
    if (!elemento || valor === ultimoEmitido.current) return;
    elemento.innerHTML = paraHtml(valor);
    ultimoEmitido.current = valor;
  }, [valor]);

  const emitir = useCallback(() => {
    const elemento = campo.current;
    if (!elemento) return;
    const texto = paraTexto(elemento);
    ultimoEmitido.current = texto;
    onEditar(texto);
  }, [onEditar]);

  return (
    <div
      ref={campo}
      role="textbox"
      aria-multiline="true"
      aria-label={rotulo}
      contentEditable
      suppressContentEditableWarning
      onInput={emitir}
      onFocus={() => onFoco?.(campo.current)}
      onBlur={() => {
        // Emitir no blur também: o `execCommand` da barra muda o DOM sem
        // disparar `input` em todos os navegadores, e uma formatação aplicada e
        // não emitida se perderia ao recarregar.
        emitir();
        onFoco?.(null);
      }}
      /* Colar de um .docx traz fonte, cor de fundo e tabela da origem: entra só
         o texto, e a formatação é a que se aplica aqui. */
      onPaste={(evento) => {
        evento.preventDefault();
        const texto = evento.clipboardData.getData("text/plain");
        document.execCommand("insertText", false, texto);
      }}
      /* `break-spaces`: no `pre-wrap` os espaços do fim da linha ficam
         pendurados para fora da caixa em vez de quebrar — era o texto saindo do
         quadro ao segurar a barra de espaço. */
      className={`w-full border-0 bg-transparent p-0 font-titulo text-[15px] leading-[1.75] text-tinta focus:outline-none [white-space:break-spaces] [overflow-wrap:anywhere] ${
        formato === "fechamento" || formato === "enderecamento"
          ? "text-center"
          : "text-justify [text-indent:1.25cm]"
      }`}
    />
  );
}

/** Acompanha o que está selecionado para a barra mostrar o que já está ligado. */
export function useSelecaoFormatada(campoAtivo: HTMLDivElement | null): EstadoDaSelecao | null {
  const [estado, setEstado] = useState<EstadoDaSelecao | null>(null);

  useEffect(() => {
    if (!campoAtivo || !comandoPossivel()) {
      setEstado(null);
      return;
    }
    const conferir = () => {
      setEstado({
        negrito: document.queryCommandState("bold"),
        italico: document.queryCommandState("italic"),
        sublinhado: document.queryCommandState("underline"),
      });
    };
    conferir();
    document.addEventListener("selectionchange", conferir);
    return () => document.removeEventListener("selectionchange", conferir);
  }, [campoAtivo]);

  return estado;
}
