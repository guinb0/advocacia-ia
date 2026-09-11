"use client";

import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { Botao, type BotaoProps } from "@/components/ui/Basicos";

/* Botão que DISPARA UM PROCESSO — ler documento, analisar, gerar, enviar.
 *
 * Nasceu de uma reclamação concreta: quase todo botão desses ficava cinza, e o
 * usuário não sabia se estava indisponível, se o clique tinha ido, ou se era
 * para esperar. O cinza respondia três perguntas diferentes com a mesma cor.
 * Aqui cada uma tem resposta própria, sempre em palavra + símbolo, logo abaixo
 * do botão (ver docs/GUIA-VISUAL.md, "Botões que iniciam um processo"):
 *
 *   - FALTA ALGO (`pendencia`): o botão continua com a cor da ação e a linha
 *     diz o que falta ("→ Escolha um arquivo"). Clicar não dispara nada e
 *     realça o aviso em âmbar — o clique vira explicação, não silêncio.
 *   - EM ANDAMENTO (`processando`, ou a Promise devolvida por `onClick`): giro
 *     no botão, rótulo do que está acontecendo e o tempo decorrido. Cliques
 *     repetidos são engolidos por uma trava síncrona, que não depende de o
 *     React já ter redesenhado o botão.
 *   - DEU ERRADO (`erro`): ✕ com a mensagem, junto de onde se clicou.
 *   - TERMINOU (`concluido`): ✓ com o que foi feito.
 *
 * `erro` e `concluido` são do chamador, e não deduzidos da Promise: quase todo
 * handler do projeto já captura a própria falha, então a Promise resolve até
 * quando a ação falhou — e um ✓ dito sem saber é pior do que nenhum. */

type Props = Omit<BotaoProps, "onClick" | "carregando" | "textoCarregando" | "disabled"> & {
  /** Pode devolver uma Promise: o botão fica em andamento até ela terminar. */
  onClick?: (evento: MouseEvent<HTMLButtonElement>) => unknown;
  /** Em andamento, controlado por quem chama (ex.: o estado vem de um hook). */
  processando?: boolean;
  /** Rótulo enquanto processa — o que está acontecendo, não "Aguarde". */
  textoProcessando?: ReactNode;
  /** Texto de apoio durante o processamento ("pode levar até 90 segundos"). */
  dica?: ReactNode;
  /** O que falta para poder começar. Vazio/nulo = pode começar. */
  pendencia?: string | null | false;
  /** Outra ação da mesma tela está em curso; o texto só aparece se clicarem. */
  aguardando?: boolean | string;
  /** Chamado quando clicam com `pendencia` — ex.: levar o foco ao campo que falta. */
  onPendencia?: () => void;
  /** Mostra a pendência só depois do clique — quando a tela já diz o que falta ao lado. */
  pendenciaAoClicar?: boolean;
  erro?: ReactNode;
  concluido?: ReactNode;
  /** Classes do `<button>` em si. `className` vai para o contêiner (que também leva a linha de estado). */
  classeBotao?: string;
};

const ESPERA_PADRAO = "Aguarde: outra ação desta tela ainda está em andamento.";

/** Segundos desde que `ativo` virou verdadeiro; zero quando inativo. */
function useSegundosDecorridos(ativo: boolean): number {
  const [segundos, setSegundos] = useState(0);
  useEffect(() => {
    if (!ativo) return;
    const inicio = Date.now();
    const id = window.setInterval(() => setSegundos(Math.floor((Date.now() - inicio) / 1000)), 1000);
    return () => {
      window.clearInterval(id);
      setSegundos(0);
    };
  }, [ativo]);
  return ativo ? segundos : 0;
}

function mensagemDaFalha(motivo: unknown): string {
  return motivo instanceof Error && motivo.message ? motivo.message : "A ação não foi concluída.";
}

export function BotaoProcesso({
  variante = "primario",
  processando = false,
  textoProcessando,
  dica,
  pendencia,
  aguardando,
  onPendencia,
  pendenciaAoClicar = false,
  erro,
  concluido,
  onClick,
  bloco,
  className,
  classeBotao,
  type = "button",
  children,
  ...resto
}: Props) {
  const [emCurso, setEmCurso] = useState(false);
  const [falha, setFalha] = useState<string | null>(null);
  /* Guarda QUAL motivo foi realçado: se o motivo muda (o usuário resolveu uma
   * pendência e surgiu outra), o realce não passa para a nova sem novo clique. */
  const [realcado, setRealcado] = useState<string | null>(null);
  const trava = useRef(false);
  const montado = useRef(false);
  const idEstado = useId();

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const ocupado = processando || emCurso;
  const segundos = useSegundosDecorridos(ocupado);
  const espera = aguardando ? (typeof aguardando === "string" ? aguardando : ESPERA_PADRAO) : null;
  const bloqueio = ocupado ? null : pendencia || espera || null;
  const erroVisivel = erro || falha;

  function aoClicar(evento: MouseEvent<HTMLButtonElement>) {
    if (ocupado || trava.current) {
      evento.preventDefault();
      return;
    }
    if (bloqueio) {
      evento.preventDefault();
      setRealcado(bloqueio);
      if (pendencia) onPendencia?.();
      return;
    }
    setFalha(null);
    setRealcado(null);
    const retorno = onClick?.(evento);
    if (retorno && typeof (retorno as PromiseLike<unknown>).then === "function") {
      trava.current = true;
      setEmCurso(true);
      Promise.resolve(retorno)
        .catch((motivo: unknown) => {
          console.error(motivo);
          if (montado.current) setFalha(mensagemDaFalha(motivo));
        })
        .finally(() => {
          trava.current = false;
          if (montado.current) setEmCurso(false);
        });
    }
  }

  let linha: { tom: "andamento" | "erro" | "pendencia" | "espera" | "ok"; simbolo: string; texto: ReactNode } | null =
    null;
  if (ocupado) {
    // Só depois de 2 s: ação rápida não precisa piscar uma linha que some logo.
    if (dica || segundos >= 2) {
      linha = {
        tom: "andamento",
        simbolo: "◌",
        texto: (
          <>
            {dica ?? "Em andamento"}
            {segundos >= 2 && <span aria-hidden> · {segundos} s</span>}
          </>
        ),
      };
    }
  } else if (erroVisivel) {
    linha = { tom: "erro", simbolo: "✕", texto: erroVisivel };
  } else if (pendencia && realcado === pendencia) {
    linha = { tom: "pendencia", simbolo: "!", texto: pendencia };
  } else if (espera && realcado === espera) {
    linha = { tom: "espera", simbolo: "!", texto: espera };
  } else if (concluido) {
    /* Antes da pendência passiva: depois de um envio que limpa o campo (a
     * revisão por prompt, por exemplo), a pendência reaparece na hora e
     * esconderia o ✓ antes de alguém lê-lo. */
    linha = { tom: "ok", simbolo: "✓", texto: concluido };
  } else if (pendencia && !pendenciaAoClicar) {
    linha = { tom: "pendencia", simbolo: "→", texto: pendencia };
  }

  const realce = linha && (linha.tom === "espera" || (linha.tom === "pendencia" && realcado === pendencia));
  const corLinha =
    linha?.tom === "erro"
      ? "text-critico"
      : linha?.tom === "ok"
        ? "text-ok"
        : realce
          ? "text-atencao font-semibold"
          : "text-tinta-3";

  return (
    <div
      className={
        bloco
          ? `flex w-full min-w-0 flex-col items-stretch ${className ?? ""}`
          : `inline-flex min-w-0 max-w-full flex-col items-start ${className ?? ""}`
      }
    >
      <Botao
        {...resto}
        type={type}
        variante={variante}
        bloco={bloco}
        carregando={ocupado}
        textoCarregando={textoProcessando}
        aria-disabled={bloqueio ? true : undefined}
        aria-describedby={linha ? idEstado : undefined}
        className={[classeBotao, bloqueio && espera && !pendencia ? "cursor-wait" : ""].filter(Boolean).join(" ") || undefined}
        onClick={aoClicar}
      >
        {children}
      </Botao>
      {/* A região existe sempre: leitor de tela só anuncia mudança num
        * `aria-live` que já estava no DOM antes da mudança. */}
      <p
        id={idEstado}
        role={linha?.tom === "erro" || realce ? "alert" : "status"}
        className={`m-0 max-w-[60ch] text-xs leading-[1.5] ${corLinha} ${linha ? "mt-[6px] flex items-start gap-[6px]" : ""}`}
      >
        {linha && (
          <>
            <span aria-hidden className="flex-none font-bold">
              {linha.simbolo}
            </span>
            <span className="min-w-0 [overflow-wrap:anywhere]">{linha.texto}</span>
          </>
        )}
      </p>
    </div>
  );
}
