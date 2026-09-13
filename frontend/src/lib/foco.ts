"use client";

import { useEffect } from "react";
import type { RefObject } from "react";

/* `[tabindex='0']` entra porque a aplicação usa alguns contêineres focáveis
 * (o `<main>` do AppShell, por exemplo). `[tabindex='-1']` fica de fora de
 * propósito: é focável por código, não pelo Tab. */
const FOCAVEL = "button, a[href], input, select, textarea, [tabindex='0']";

function controlesVisiveis(painel: HTMLElement): HTMLElement[] {
  return Array.from(painel.querySelectorAll<HTMLElement>(FOCAVEL)).filter(
    (elemento) => elemento.getClientRects().length > 0 && !elemento.hasAttribute("disabled"),
  );
}

/**
 * Prende o Tab dentro de `painelRef` enquanto `ativo` for verdadeiro, e devolve
 * o foco a quem o tinha quando fecha.
 *
 * Sem isto, `aria-modal` avisa o leitor de tela mas o Tab continua passeando
 * pela página atrás do diálogo: quem navega por teclado sai do modal sem
 * perceber, digita num formulário que não está vendo e volta achando que o
 * modal travou.
 *
 * O foco inicial só se move se ainda não houver nada focado dentro — assim um
 * `autoFocus` no campo certo continua mandando, em vez de ser sobrescrito pelo
 * primeiro botão do cabeçalho.
 */
export function useFocoContido(painelRef: RefObject<HTMLElement | null>, ativo: boolean): void {
  useEffect(() => {
    if (!ativo) return;
    const painel = painelRef.current;
    if (!painel) return;

    const anterior = document.activeElement as HTMLElement | null;
    if (!painel.contains(document.activeElement)) {
      controlesVisiveis(painel)[0]?.focus();
    }

    const conterFoco = (evento: KeyboardEvent) => {
      if (evento.key !== "Tab") return;
      const controles = controlesVisiveis(painel);
      const primeiro = controles[0];
      const ultimo = controles[controles.length - 1];
      if (!primeiro) return;
      /* Foco que escapou (clique no fundo, elemento removido) volta para dentro
       * na próxima tabulação, em vez de seguir pela página. */
      if (!painel.contains(document.activeElement)) {
        evento.preventDefault();
        (evento.shiftKey ? ultimo : primeiro)?.focus();
        return;
      }
      if (evento.shiftKey && document.activeElement === primeiro) {
        evento.preventDefault();
        ultimo?.focus();
      } else if (!evento.shiftKey && document.activeElement === ultimo) {
        evento.preventDefault();
        primeiro?.focus();
      }
    };

    document.addEventListener("keydown", conterFoco);
    return () => {
      document.removeEventListener("keydown", conterFoco);
      anterior?.focus();
    };
  }, [painelRef, ativo]);
}
