"use client";

import { useEffect, useRef } from "react";

import { processarEntrevista, recomendarEntrevista, triarEntrevista } from "@/lib/api";
import type { ProcessamentoEntrevista, RecomendacaoEntrevista, Triagem } from "@/lib/types";

/* A revisão da entrevista, adiantada enquanto a conversa ainda corre.
 *
 * O problema que isto resolve é de relógio, não de qualidade: a leitura final
 * são três chamadas caras sobre a transcrição INTEIRA (consolidação do
 * roteiro, triagem e recomendação por precedentes), e todas começavam do zero
 * no clique — com o cliente na linha esperando.
 *
 * Aqui a mesma leitura roda no fundo, sobre o que já foi transcrito, sem
 * aparecer em lugar nenhum. Quando a entrevistadora aperta "Revisar
 * entrevista", o resultado guardado vai para a tela IMEDIATAMENTE, e só o que
 * a conversa acrescentou depois da última passada é lido na hora.
 *
 * Duas regras que dão sentido ao módulo:
 *
 * - **preliminar não é final, e a tela diz qual é qual.** Se a transcrição
 *   cresceu depois da última passada, o que aparece no clique está marcado
 *   como leitura preliminar e é substituído quando a passada definitiva chega.
 *   Esconder a diferença faria a revisão parecer completa faltando o fim da
 *   conversa — que é justamente onde ficam os valores e a saída;
 * - **pré-análise não mexe no formulário.** A consolidação preliminar carrega
 *   as respostas como elas estavam há alguns minutos; aplicá-las apagaria o
 *   que foi respondido desde então. Quem preenche campo é só a passada
 *   definitiva (ver `aoConsolidar`). */

export interface LeituraDaEntrevista {
  processamento: ProcessamentoEntrevista;
  triagem: Triagem | null;
  recomendacao: RecomendacaoEntrevista | null;
  avisos: string[];
  /** Quantos caracteres de transcrição esta leitura cobriu. É o que separa
   *  preliminar de definitiva: igual ao tamanho atual, nada ficou de fora. */
  cobertura: number;
}

/** De quanto em quanto tempo o relógio da pré-análise acorda. */
const PASSO_MS = 20_000;
/** Nunca duas passadas mais perto que isto — cada uma são três chamadas. */
const INTERVALO_MINIMO_MS = 90_000;
/* Quando vale reler — e por que a conta é uma PROPORÇÃO, não um número de
 * caracteres.
 *
 * Cada passada relê a conversa inteira, do zero, de propósito: triagem e
 * recomendação são juízo sobre o caso, não acúmulo de campo, e uma leitura que
 * herda a própria conclusão anterior tende a encaixar o dado novo na tese velha
 * em vez de trocar de tese. Quem acumula fato aqui é a escuta ao vivo
 * (`/api/entrevista/escuta`); esta releitura é justamente a que a corrige.
 *
 * O preço disso é que a passada custa mais quanto mais longa a conversa. Com um
 * gatilho fixo — "releia a cada 1.200 caracteres" — o número de passadas cresce
 * junto com o texto e o custo da entrevista vira quadrático: umas quinze
 * releituras de algo que só engorda.
 *
 * Com a proporção, a entrevista é relida quando ela cresceu o bastante para
 * poder dizer outra coisa. As passadas caem espaçadas em progressão (~2k, 3k,
 * 4k, 6k, 8k, 12k…): meia dúzia numa entrevista longa, cada uma num ponto em
 * que a conversa de fato virou outra, e o custo total fica em poucas vezes o de
 * uma leitura final — sem abrir mão da leitura limpa. */
const CRESCIMENTO_MINIMO_RELATIVO = 0.4;
/** A primeira passada espera a conversa ter tamanho: sobre duas frases, 40% de
 *  crescimento acontece numa respiração, e a leitura não teria o que dizer. */
const PRIMEIRA_PASSADA = 1_500;
/** `recomendarEntrevista` recusa relato mais curto que isto (`PedidoRecomendacao`). */
const MINIMO_RECOMENDACAO = 40;

/** Lê a entrevista inteira: consolida o roteiro, classifica e recomenda.
 *
 * As três juntas porque é o pacote que a tela mostra de uma vez. Triagem e
 * recomendação são melhor-esforço — o banco de precedentes fica atrás da VPN e
 * já ficou fora do ar; o que não pode é a consolidação do formulário cair
 * junto, porque é a parte que ninguém refaz à mão.
 */
export async function lerEntrevista(
  transcricao: string,
  respostas: Record<string, string | string[]>,
  aoConsolidar?: (processamento: ProcessamentoEntrevista) => void,
): Promise<LeituraDaEntrevista> {
  const cobertura = transcricao.length;
  const processamento = await processarEntrevista(transcricao, respostas);
  aoConsolidar?.(processamento);

  const lacunas = processamento.faltando.filter((p) => p.obrigatoria).map((p) => p.pergunta);
  const avisos: string[] = [];
  const [triagem, recomendacao] = await Promise.all([
    triarEntrevista(transcricao).catch(() => {
      avisos.push("O tipo do caso não pôde ser classificado automaticamente.");
      return null;
    }),
    transcricao.length >= MINIMO_RECOMENDACAO
      ? recomendarEntrevista(transcricao, lacunas).catch(() => {
          avisos.push("A base vetorial não respondeu. Encaminhe para revisão do advogado.");
          return null;
        })
      : Promise.resolve(null),
  ]);
  if (processamento.analise_indisponivel) {
    avisos.push("A análise jurídica detalhada ficou indisponível nesta execução.");
  }
  return { processamento, triagem, recomendacao, avisos, cobertura };
}

interface Opcoes {
  /** A transcrição bruta como ela está agora, já concatenada. */
  lerTranscricao: () => string;
  lerRespostas: () => Record<string, string | string[]>;
  /** Falso enquanto a revisão de verdade corre, e depois do encerramento: as
   *  duas disputariam o mesmo threadpool do servidor, que é o que transcreve
   *  a conversa ao vivo. */
  ativa: boolean;
}

/** Mantém uma leitura recente da entrevista pronta, sem mostrar nada. */
export function usarPreAnalise({ lerTranscricao, lerRespostas, ativa }: Opcoes): {
  obter: () => LeituraDaEntrevista | null;
} {
  const pronta = useRef<LeituraDaEntrevista | null>(null);
  const emCurso = useRef(false);
  const ultimaPassada = useRef(0);
  const entradas = useRef({ lerTranscricao, lerRespostas });
  entradas.current = { lerTranscricao, lerRespostas };

  useEffect(() => {
    if (!ativa) return;
    const id = window.setInterval(() => {
      if (emCurso.current) return;
      if (Date.now() - ultimaPassada.current < INTERVALO_MINIMO_MS) return;
      const transcricao = entradas.current.lerTranscricao();
      const coberto = pronta.current?.cobertura ?? 0;
      if (coberto === 0) {
        if (transcricao.length < PRIMEIRA_PASSADA) return;
      } else if (transcricao.length < coberto * (1 + CRESCIMENTO_MINIMO_RELATIVO)) {
        return;
      }

      emCurso.current = true;
      ultimaPassada.current = Date.now();
      void lerEntrevista(transcricao, entradas.current.lerRespostas())
        .then((leitura) => {
          pronta.current = leitura;
        })
        .catch(() => {
          /* Silêncio de propósito: isto é adiantamento, e falhar aqui não muda
           * nada para quem conduz — o clique refaz a leitura do zero e é lá
           * que o erro aparece, com o cliente ainda na sala. */
        })
        .finally(() => {
          emCurso.current = false;
        });
    }, PASSO_MS);
    return () => window.clearInterval(id);
  }, [ativa]);

  return { obter: () => pronta.current };
}
