"use client";

import { useEffect, useState } from "react";

import type { CampoOuvido, Pergunta } from "@/lib/types";
import estilos from "./Conducao.module.css";

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
  onIrPara: (perguntaId: string) => void;
  onPular: (perguntaId: string) => void;
  onRetomarPuladas: () => void;
}

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
      <section className={estilos.barra}>
        <span className={estilos.rotulo}>ROTEIRO PERCORRIDO</span>
        <p className={estilos.fim}>
          As {total} perguntas do roteiro foram respondidas ou deixadas para depois.
          Leia o encerramento e conclua a entrevista.
          {puladas > 0 && (
            <>
              {" "}
              Ainda há{" "}
              <button type="button" className={estilos.retomar} onClick={onRetomarPuladas}>
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
          <div className={estilos.conferencia}>
            <span className={estilos.conferenciaTitulo}>
              CONFIRA O QUE EU OUVI ({sugestoes.length})
            </span>
            <p className={estilos.conferenciaNota}>
              Nome e CPF não entram sozinhos — número ditado a transcrição erra, e
              ninguém confere dígito de ouvido. É a última parada antes do contrato:
              em branco, eles atravessam a procuração e a petição.
            </p>

            {sugestoes.map((s) => (
              <div key={s.pergunta_id} className={estilos.item}>
                <span className={estilos.itemCampo}>{s.pergunta}</span>
                <strong className={estilos.itemValor}>{s.valor}</strong>
                {s.trecho && <em className={estilos.itemTrecho}>“{s.trecho}”</em>}
                <div className={estilos.itemAcoes}>
                  <button
                    type="button"
                    className={estilos.acao}
                    onClick={() => onAceitar(s.pergunta_id, s.valor)}
                  >
                    Está certo
                  </button>
                  <button
                    type="button"
                    className={estilos.acaoDiscreta}
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
    <section className={`${estilos.barra} ${cobrando ? estilos.cobrando : ""}`}>
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
      {cobrando && (
        <p className={estilos.pare} aria-live="polite">
          <strong className={estilos.pareRotulo}>PARE</strong>
          <span className={estilos.pareTexto}>
            DIRECIONE A PERGUNTA — NÃO PERCA TEMPO
            <em>
              {segundos}s nesta pergunta. Corte com educação e traga o cliente de volta
              ao roteiro — o que ele contar fora de ordem o sistema aproveita sozinho.
            </em>
          </span>
        </p>
      )}

      <div className={estilos.topo}>
        <span className={estilos.rotulo}>
          PERGUNTE AGORA · {posicao} de {total}
          {bloco && <span className={estilos.bloco}> · {bloco}</span>}
        </span>
        {/* Respondendo ganha do relógio: enquanto o cliente desenvolve, o que
          * o entrevistador precisa saber é "deixe ele terminar", não há quantos
          * segundos a pergunta está aberta. */}
        {respondendo ? (
          <span className={estilos.respondendo} title="Trechos desta resposta ainda estão chegando.">
            respondendo — deixe terminar
          </span>
        ) : (
          ativo && (
            <span
              className={cobrando ? estilos.relogioEstourado : estilos.relogio}
              title="Tempo nesta pergunta. Zera quando ela é respondida ou pulada."
            >
              {segundos}s
            </span>
          )
        )}
      </div>

      {/* A frase que traz o cliente de volta, logo ACIMA do enunciado: ela
        * acaba em dois-pontos e emenda nele, de cima para baixo, na ordem em
        * que se fala. */}
      {retomada && (
        <p className={estilos.retomada}>
          <span className={estilos.leia}>LEIA AO CLIENTE</span>
          {retomada}
        </p>
      )}

      {/* O enunciado grande, palavra por palavra: é para ser LIDO ao cliente,
        * não interpretado. O roteiro é do escritório e o texto é dele. */}
      <p className={estilos.pergunta}>{pergunta.texto}</p>

      {/* O fecho vem DEPOIS do enunciado porque é o que se diz depois dele.
        * Dizer o tamanho da resposta esperada encurta quem se perde por não
        * saber onde a pergunta termina. */}
      {fecho && <p className={estilos.fecho}>{fecho}</p>}

      {/* `dica` é orientação interna — nunca vai ao cliente. Ver `roteiros.py`. */}
      {pergunta.dica && <p className={estilos.dica}>{pergunta.dica}</p>}

      <div className={estilos.acoes}>
        <button
          type="button"
          className={estilos.acao}
          onClick={() => onIrPara(pergunta.id)}
        >
          Ir ao campo
        </button>
        {/* Sem isto, uma pergunta que o cliente não pode responder travaria a
          * sequência e a cobrança tocaria para sempre. Pular é explícito e
          * contado — o roteiro não deixa a pergunta cair no esquecimento. */}
        <button
          type="button"
          className={estilos.acaoDiscreta}
          onClick={() => onPular(pergunta.id)}
          title="Sai da vez, mas continua pendente no roteiro"
        >
          Deixar para depois
        </button>
        {puladas > 0 && (
          <button type="button" className={estilos.acaoDiscreta} onClick={onRetomarPuladas}>
            retomar {puladas} pulada(s)
          </button>
        )}
      </div>
    </section>
  );
}
