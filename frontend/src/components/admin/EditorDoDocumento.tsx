"use client";

/**
 * O documento da petição, editável como no Word.
 *
 * Era um `<textarea>` por seção: dava para escrever, não para formatar. Quem
 * revisa uma peça precisa grifar um trecho, pôr um título no meio da página,
 * destacar um valor em vermelho — e fazia isso baixando o .docx, editando no
 * Word e perdendo o vínculo com o caso. Agora a barra de ferramentas aplica
 * negrito, itálico, sublinhado, tamanho, cor e alinhamento direto na peça.
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
 * sublinhado, cor e alinhamento. Trazer um editor inteiro (TipTap e afins)
 * custaria o dobro do peso da tela para ganhar tabela e lista, que a peça já
 * resolve por outro caminho. `execCommand` está obsoleto no papel e implementado
 * em todos os navegadores — inclusive porque é ele que dá o Ctrl+B de graça.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, Underline } from "lucide-react";

import { CORES, TAMANHOS_PT, paraHtml, paraTexto } from "@/lib/formatacaoPeticao";

/** Marca de tamanho que o `execCommand` sabe aplicar, e que trocamos depois pelo
 *  tamanho em pontos de verdade. `fontSize` só aceita 1–7 e escreve `<font>`;
 *  o 7 é o menos provável de aparecer por outro motivo. */
const TAMANHO_SENTINELA = "7";

export type EstadoDaSelecao = {
  negrito: boolean;
  italico: boolean;
  sublinhado: boolean;
};

function comandoPossivel(): boolean {
  return typeof document !== "undefined" && typeof document.execCommand === "function";
}

/** Aplica um tamanho em pontos à seleção.
 *
 * `execCommand("fontSize")` só entende a escala 1–7 do HTML antigo. O caminho é
 * marcar a seleção com um valor sentinela e trocar os elementos marcados pelo
 * tamanho real — assim quem quebra a seleção em pedaços continua sendo o
 * navegador, que é a parte difícil. */
function aplicarTamanho(raiz: HTMLElement, pontos: number | null) {
  document.execCommand("fontSize", false, TAMANHO_SENTINELA);
  for (const marcado of Array.from(raiz.querySelectorAll(`font[size="${TAMANHO_SENTINELA}"]`))) {
    if (!pontos) {
      // "Padrão da peça": o trecho perde o tamanho próprio e volta a herdar o
      // do documento, incluindo o que um `<span>` de fora tivesse imposto.
      for (const dentro of Array.from(marcado.querySelectorAll<HTMLElement>("[style*='font-size']"))) {
        dentro.style.removeProperty("font-size");
      }
      marcado.replaceWith(...Array.from(marcado.childNodes));
      continue;
    }
    const span = document.createElement("span");
    span.style.fontSize = `${pontos}pt`;
    while (marcado.firstChild) span.appendChild(marcado.firstChild);
    marcado.replaceWith(span);
  }
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

      <label className="sr-only" htmlFor="editor-tamanho">Tamanho da letra</label>
      <select
        id="editor-tamanho"
        className="h-8 rounded-campo border border-borda-campo bg-papel px-1 text-sm text-tinta disabled:opacity-40"
        disabled={desabilitado}
        value=""
        title="Tamanho da letra"
        onChange={(evento) => {
          const valor = evento.target.value;
          evento.target.value = "";
          aoAplicar((raiz) => aplicarTamanho(raiz, valor ? Number(valor) : null));
        }}
      >
        <option value="">Tamanho</option>
        {TAMANHOS_PT.map((pt) => (
          <option key={pt} value={pt}>{pt} pt</option>
        ))}
        <option value="0">Padrão da peça</option>
      </select>

      <label className="sr-only" htmlFor="editor-cor">Cor do texto</label>
      <select
        id="editor-cor"
        className="h-8 rounded-campo border border-borda-campo bg-papel px-1 text-sm text-tinta disabled:opacity-40"
        disabled={desabilitado}
        value=""
        title="Cor do texto"
        onChange={(evento) => {
          const valor = evento.target.value;
          evento.target.value = "";
          // Sem cor escolhida, volta ao preto da peça: `execCommand` não tem
          // "remover cor", então a cor do corpo é a própria remoção.
          aoAplicar(() => document.execCommand("foreColor", false, valor || "#102033"));
        }}
      >
        <option value="">Cor</option>
        {CORES.map((cor) => (
          <option key={cor.nome} value={cor.valor}>{cor.nome}</option>
        ))}
      </select>

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
