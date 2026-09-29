"use client";

import { useEffect, useState } from "react";

import type { CampoOuvido, Pergunta } from "@/lib/types";

/* Quem conduz a entrevista é o roteiro, não a conversa.
 *
 * O escritório fechou a questão assim: "não é o que o cliente quer ou nós
 * entendemos — tem que ser o que o advogado determina". A escuta continua
 * preenchendo o que o cliente adianta fora de ordem, e é ela que encurta a
 * entrevista; mas a pergunta que o entrevistador FAZ é sempre a próxima ainda
 * aberta na ordem do documento. Esta barra é essa pergunta, e só ela.
 *
 * Por isso ela mostra UMA. O painel do lado lista o que falta e o que já
 * entrou — informação para conferir de relance. Aqui não é para escolher: é
 * para ler em voz alta.
 *
 * O relógio existe pelo mesmo motivo. O cliente fala do filho, da vizinha, da
 * cirurgia que não é a do processo, e a entrevista se perde sem que ninguém
 * perceba — porque a tela, enquanto isso, está preenchendo campos e parecendo
 * produtiva. Passados dez segundos sem a pergunta ATUAL respondida, a tela
 * cobra a condução.
 *
 * Falar de outro assunto NÃO zera o relógio, e isso é a regra, não um descuido:
 * o que conta é a sequência do roteiro. O que ele disser de fora de ordem a
 * escuta aproveita de qualquer jeito. */

/** Passado disto sem a pergunta atual respondida, a tela cobra a condução. */
const SEGUNDOS_PARA_COBRAR = 10;

/* Quando trocar a frase de retomada, em segundos na mesma pergunta.
 *
 * Um entrevistador experiente não sobe o tom de uma vez, e também não repete a
 * mesma frase gentil enquanto a entrevista escorre pelo ralo. Cada degrau
 * troca por uma retomada mais firme — as frases estão em `roteiros.RETOMADAS`,
 * na ordem, e o primeiro degrau é o próprio instante da cobrança.
 *
 * Se um dia o escritório escrever mais retomadas do que degraus, a última vale
 * daí em diante; se escrever menos, os degraus extras não têm o que mostrar. */
const DEGRAUS_S = [SEGUNDOS_PARA_COBRAR, 25, 45, 70];

interface Props {
  /** A próxima pergunta em aberto, na ordem do roteiro. `null` = acabou. */
  pergunta: Pergunta | null;
  /** Título do bloco a que ela pertence — o entrevistador precisa saber onde está. */
  bloco: string;
  /** Posição dela na sequência, contando a partir de 1. */
  posicao: number;
  total: number;
  /** Quantas foram deixadas para depois. Ficam à vista para não sumirem. */
  puladas: number;
  /* O que a escuta ouviu e depende de um clique — nome e CPF.
   *
   * Não aparece durante a conversa, e isso é decisão do escritório: parar a
   * entrevista para conferir um campo é travar o processo. Fica tudo para o
   * fim, numa conferência só, quando o roteiro acabou e o cliente já não está
   * esperando a próxima pergunta. */
  sugestoes: CampoOuvido[];
  onAceitar: (perguntaId: string, valor: string) => void;
  onDescartar: (perguntaId: string) => void;
  /** As frases de retomada do roteiro, da mais gentil à mais firme. */
  retomadas: string[];
  /** Complemento por tipo de resposta ("basta sim ou não"), do roteiro. */
  fechosPorTipo: Record<string, string>;
  /** A entrevista está correndo (microfone aberto e não pausado). */
  ativo: boolean;
  /** O cliente está desenvolvendo a resposta DESTA pergunta agora. A barra não
   *  anda e o relógio não corre — cobrar quem está respondendo é atropelar. */
  respondendo: boolean;
  /** Caiu resposta em ALGUMA pergunta há pouco: a entrevista anda, ainda que
   *  fora de ordem. A cobrança continua, mas sem a placa — ver `pare`. */
  fluindo: boolean;
  onIrPara: (perguntaId: string) => void;
  onPular: (perguntaId: string) => void;
  onRetomarPuladas: () => void;
}

const ACAO =
  "border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.06em] uppercase px-[11px] py-2 cursor-pointer hover:bg-papel-2";
const ACAO_DISCRETA =
  "border-none bg-transparent p-0 text-tinta-3 font-normal text-[11px] leading-none font-ui " +
  "underline underline-offset-[3px] cursor-pointer hover:text-tinta";

export default function Conducao({
  pergunta,
  bloco,
  posicao,
  total,
  puladas,
  sugestoes,
  retomadas,
  fechosPorTipo,
  ativo,
  respondendo,
  fluindo,
  onIrPara,
  onPular,
  onRetomarPuladas,
  onAceitar,
  onDescartar,
}: Props) {
  /* Segundos na pergunta ATUAL.
   *
   * Zera quando a pergunta muda — e ela só muda quando a anterior foi
   * respondida ou pulada. É essa amarração que faz o relógio medir a condução,
   * e não o tempo de tela. */
  const [segundos, setSegundos] = useState(0);
  const id = pergunta?.id ?? "";

  useEffect(() => {
    setSegundos(0);
    if (!ativo || !id) return;
    const inicio = Date.now();
    const t = setInterval(() => setSegundos(Math.floor((Date.now() - inicio) / 1000)), 1000);
    return () => clearInterval(t);
  }, [id, ativo]);

  if (!pergunta) {
    return (
      <section
        className="sticky top-0 z-[5] mt-4 mb-1 py-3 px-4 border border-l-4 bg-papel"
        style={{ borderColor: "var(--borda-forte)", borderLeftColor: "var(--tinta)" }}
      >
        <span className="text-[10px] font-semibold leading-[1.4] font-ui tracking-[0.14em] text-tinta-3">
          ROTEIRO PERCORRIDO
        </span>
        <p className="mt-2 mb-0 max-w-[62ch] font-normal text-[13px] leading-[1.6] font-ui text-tinta-3">
          As {total} perguntas do roteiro foram respondidas ou deixadas para depois.
          Leia o encerramento e conclua a entrevista.
          {puladas > 0 && (
            <>
              {" "}
              Ainda há{" "}
              <button
                type="button"
                className="border-none bg-transparent p-0 text-tinta font-normal text-[13px] leading-[1.6] font-ui underline underline-offset-[3px] cursor-pointer"
                onClick={onRetomarPuladas}
              >
                {puladas} pergunta(s) pulada(s)
              </button>{" "}
              — o roteiro não fecha sem elas.
            </>
          )}
        </p>

        {/* A CONFERÊNCIA, toda de uma vez, e só aqui.
          *
          * Durante a conversa ela não aparece: parar a entrevista para conferir
          * a grafia de um nome é travar o processo, e era o que acontecia. No
          * fim o cliente não está esperando a próxima pergunta, e conferir dois
          * campos de enfiada leva segundos.
          *
          * Descartar devolve a pergunta à condução — a barra sai deste estado e
          * volta a apontá-la, porque descartar significa perguntar de novo. */}
        {sugestoes.length > 0 && (
          <div className="mt-[14px] border-t-[3px] border-double border-borda-forte pt-3">
            <span className="text-[10px] font-semibold leading-[1.4] font-ui tracking-[0.14em] text-atencao">
              CONFIRA O QUE EU OUVI ({sugestoes.length})
            </span>
            <p className="mt-[6px] mb-0 max-w-[68ch] italic font-normal text-[12px] leading-[1.55] font-titulo text-tinta-3">
              Nome e CPF não entram sozinhos — número ditado a transcrição erra, e
              ninguém confere dígito de ouvido. É a última parada antes do contrato:
              em branco, eles atravessam a procuração e a petição.
            </p>

            {sugestoes.map((s) => (
              <div key={s.pergunta_id} className="mt-3 border-l-[3px] border-atencao px-3 py-[9px] bg-papel-2">
                <span className="block text-[10px] font-semibold leading-[1.4] font-ui tracking-[0.1em] uppercase text-tinta-3">
                  {s.pergunta}
                </span>
                <strong className="block mt-[3px] font-semibold text-[16px] leading-[1.3] font-codigo tabular-nums text-tinta">
                  {s.valor}
                </strong>
                {s.trecho && (
                  <em className="block mt-1 max-w-[62ch] italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
                    “{s.trecho}”
                  </em>
                )}
                <div className="flex items-center flex-wrap gap-[10px] mt-[9px]">
                  <button type="button" className={ACAO} onClick={() => onAceitar(s.pergunta_id, s.valor)}>
                    Está certo
                  </button>
                  <button
                    type="button"
                    className={ACAO_DISCRETA}
                    onClick={() => onDescartar(s.pergunta_id)}
                    title="Volta a pergunta para a condução — é para perguntar de novo"
                  >
                    descartar e perguntar de novo
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    );
  }

  const cobrando = ativo && segundos >= SEGUNDOS_PARA_COBRAR;

  /* A frase da vez e o fecho — o script do corte, pronto para ler.
   *
   * Cortar um cliente que está desabafando é constrangedor, e por isso ninguém
   * corta: a entrevista de vinte minutos vira uma de cinquenta e as perguntas
   * do fim ficam sem resposta. Com a frase escrita na tela, cortar deixa de
   * depender de o entrevistador achar as palavras com o cliente falando.
   *
   * As três peças ficam na ordem em que se fala: a retomada emenda no enunciado
   * (por isso ela acaba em dois-pontos), e o fecho vem depois dele. */
  const degrau = Math.max(DEGRAUS_S.filter((s) => segundos >= s).length - 1, 0);
  const retomada = cobrando ? (retomadas[Math.min(degrau, retomadas.length - 1)] ?? "") : "";
  const fecho = cobrando ? (fechosPorTipo[pergunta.tipo] ?? "") : "";

  return (
    <section
      className="sticky top-0 z-[5] mt-4 mb-1 py-3 px-4 border border-l-4"
      style={
        cobrando
          ? {
              background: "color-mix(in srgb, var(--critico) 5%, var(--papel))",
              borderColor: "var(--critico)",
              borderLeftColor: "var(--critico)",
            }
          : { background: "var(--papel)", borderColor: "var(--borda-forte)", borderLeftColor: "var(--tinta)" }
      }
    >
      {/* A placa de PARE.
        *
        * Vem ANTES de tudo e atravessa a barra de ponta a ponta porque não é
        * informação, é ordem: o entrevistador está olhando o cliente, e o que
        * ele precisa captar pelo canto do olho é "corta e volta ao roteiro" —
        * não um texto para ler. Some quando a pergunta for respondida, que é a
        * única saída que interessa.
        *
        * Não pisca. Movimento na periferia da visão sequestra a atenção de quem
        * deveria estar ouvindo o cliente — e quem apaga o alarme é a resposta,
        * não o entrevistador olhar para cá. */}
      {cobrando &&
        (fluindo ? (
          /* A entrevista está andando — o cliente respondeu OUTRA pergunta há
           * pouco. A cobrança continua (o relógio não parou, a pergunta segue
           * aberta), mas recolhida a uma linha: gritar PARE por cima de uma
           * conversa produtiva faz o alarme virar paisagem, e aí ele não serve
           * para o caso em que importa. */
          <p
            className="mt-[10px] mb-0 border-l-[3px] border-atencao px-[11px] py-[7px] bg-papel-2 max-w-[68ch] font-normal text-[12px] leading-[1.5] font-ui text-tinta-2 [&_strong]:text-atencao"
            aria-live="polite"
          >
            <strong>{segundos}s sem responder esta.</strong> Ele está respondendo outras —
            encaixe esta quando ele terminar a frase.
          </p>
        ) : (
          <p
            className="flex items-center gap-[14px] -mx-4 -mt-3 mb-3 bg-critico px-4 py-[11px] text-white max-[720px]:items-start max-[720px]:flex-col max-[720px]:gap-[9px]"
            aria-live="polite"
          >
            <strong className="flex-none border-2 border-white px-[11px] py-[6px] font-bold text-[20px] leading-none font-ui tracking-[0.14em]">
              PARE
            </strong>
            <span className="font-bold text-[13px] leading-[1.3] font-ui tracking-[0.05em]">
              DIRECIONE A PERGUNTA — NÃO PERCA TEMPO
              <em className="block mt-[5px] max-w-[62ch] font-normal text-[12px] leading-[1.5] font-ui not-italic tracking-normal text-white/90">
                {segundos}s nesta pergunta e nada entrando em campo nenhum. Corte com
                educação e traga o cliente de volta ao roteiro.
              </em>
            </span>
          </p>
        ))}

      <div className="flex items-baseline justify-between gap-[10px]">
        <span className="text-[10px] font-semibold leading-[1.4] font-ui tracking-[0.14em] text-tinta-3">
          PERGUNTE AGORA · {posicao} de {total}
          {bloco && <span className="font-normal tracking-[0.06em] normal-case"> · {bloco}</span>}
        </span>
        {/* Respondendo ganha do relógio: enquanto o cliente desenvolve, o que
          * o entrevistador precisa saber é "deixe ele terminar", não há quantos
          * segundos a pergunta está aberta. */}
        {respondendo ? (
          <span
            className="flex-none text-[10.5px] font-semibold leading-none font-ui text-ok"
            title="Trechos desta resposta ainda estão chegando."
          >
            respondendo — deixe terminar
          </span>
        ) : (
          ativo && (
            <span
              className={
                cobrando
                  ? "flex-none text-[11px] font-bold leading-none font-codigo tabular-nums text-critico"
                  : "flex-none text-[11px] font-medium leading-none font-codigo tabular-nums text-tinta-3"
              }
              title="Tempo nesta pergunta. Zera quando ela é respondida ou pulada."
            >
              {segundos}s
            </span>
          )
        )}
      </div>

      {/* A frase que traz o cliente de volta, logo ACIMA do enunciado: ela
        * acaba em dois-pontos e emenda nele, de cima para baixo, na ordem em
        * que se fala. Não aparece enquanto a entrevista flui: ali não há o que
        * cortar — ele está respondendo, só que outra pergunta. */}
      {retomada && !fluindo && (
        <p className="mt-[10px] mb-0 border-l-[3px] border-critico px-3 py-2 bg-papel-2 max-w-[68ch] font-normal text-[14px] leading-[1.6] font-titulo text-tinta">
          <span className="block mb-1 text-[9px] font-semibold leading-none font-ui tracking-[0.14em] text-critico">
            LEIA AO CLIENTE
          </span>
          {retomada}
        </p>
      )}

      {/* O enunciado grande, palavra por palavra: é para ser LIDO ao cliente,
        * não interpretado. O roteiro é do escritório e o texto é dele. */}
      <p className="mt-2 mb-0 max-w-[62ch] font-medium text-[19px] leading-[1.35] font-titulo text-tinta">
        {pergunta.texto}
      </p>

      {/* O fecho vem DEPOIS do enunciado porque é o que se diz depois dele.
        * Dizer o tamanho da resposta esperada encurta quem se perde por não
        * saber onde a pergunta termina. */}
      {fecho && (
        <p className="mt-[6px] mb-0 max-w-[62ch] font-normal text-[13px] leading-[1.55] font-titulo text-tinta-2">
          {fecho}
        </p>
      )}

      {/* `dica` é orientação interna — nunca vai ao cliente. Ver `roteiros.py`. */}
      {pergunta.dica && (
        <p className="mt-[6px] mb-0 max-w-[62ch] italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
          {pergunta.dica}
        </p>
      )}

      <div className="flex items-center flex-wrap gap-2 mt-[11px]">
        <button type="button" className={ACAO} onClick={() => onIrPara(pergunta.id)}>
          Ir ao campo
        </button>
        {/* Sem isto, uma pergunta que o cliente não pode responder travaria a
          * sequência e a cobrança tocaria para sempre. Pular é explícito e
          * contado — o roteiro não deixa a pergunta cair no esquecimento. */}
        <button
          type="button"
          className={ACAO_DISCRETA}
          onClick={() => onPular(pergunta.id)}
          title="Sai da vez, mas continua pendente no roteiro"
        >
          Deixar para depois
        </button>
        {puladas > 0 && (
          <button type="button" className={ACAO_DISCRETA} onClick={onRetomarPuladas}>
            retomar {puladas} pulada(s)
          </button>
        )}
      </div>
    </section>
  );
}
