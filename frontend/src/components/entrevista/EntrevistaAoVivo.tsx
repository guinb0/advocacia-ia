"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CapturaEntrevista } from "@/lib/transcricao";
import type { EstadoCaptura, Microfone } from "@/lib/transcricao";

/* Transcreve a resposta do entrevistado. A entrevista acontece aqui — o
 * sistema é quem grava.
 *
 * O microfone abre UMA vez e fica aberto; cada pergunta liga e desliga só a
 * transcrição. Reabrir a cada pergunta piscaria o indicador do navegador e
 * arriscaria comer o começo da fala. */

interface Props {
  /** Identificador da pergunta em curso — vai junto da resposta. */
  perguntaId: string;
  /** Enunciado exibido acima da transcrição. */
  pergunta?: string;
  /** Chamado quando a resposta fecha, com o texto consolidado. */
  onResposta?: (perguntaId: string, texto: string, duracaoS: number) => void;
}

const BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
/* Gravando: vermelho, porque é estado que precisa saltar aos olhos. */
const BOTAO_GRAVANDO =
  "border-[1.5px] border-critico bg-transparent text-critico text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-critico enabled:hover:text-papel";
const SECUNDARIO =
  "border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.08em] uppercase px-3 py-[9px] cursor-pointer enabled:hover:bg-papel-2";

export default function EntrevistaAoVivo({ perguntaId, pergunta, onResposta }: Props) {
  const [estado, setEstado] = useState<EstadoCaptura>("sem-audio");
  const [parcial, setParcial] = useState("");
  const [final, setFinal] = useState("");
  const [duracao, setDuracao] = useState(0);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [microfones, setMicrofones] = useState<Microfone[]>([]);
  const [micEscolhido, setMicEscolhido] = useState("");

  const capturaRef = useRef<CapturaEntrevista | null>(null);
  const onRespostaRef = useRef(onResposta);
  onRespostaRef.current = onResposta;

  if (capturaRef.current === null && typeof window !== "undefined") {
    capturaRef.current = new CapturaEntrevista({
      onParcial: setParcial,
      onFinal: (texto, dur) => {
        // Acrescenta ao que já havia: é o que sustenta "adicionar complemento".
        // Substituir apagaria a primeira metade da resposta do cliente.
        setFinal((anterior) => {
          const inteiro = [anterior, texto].filter(Boolean).join(" ");
          onRespostaRef.current?.(perguntaId, inteiro, dur);
          return inteiro;
        });
        setParcial("");
        setDuracao(dur);
        setOcupado(false);
      },
      onEstado: setEstado,
      onErro: (m) => {
        setErro(m);
        setOcupado(false);
      },
    });
  }

  // A captura segura o microfone e um AudioContext: sair da tela sem soltar
  // deixaria o indicador de gravação do navegador aceso.
  useEffect(() => () => capturaRef.current?.encerrar(), []);

  const selecionar = useCallback(async () => {
    setErro(null);
    try {
      await capturaRef.current?.selecionarAudio(micEscolhido || undefined);
      // O nome do dispositivo só aparece depois da permissão concedida.
      setMicrofones(await CapturaEntrevista.microfones());
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      if (/NotAllowedError|permission denied/i.test(msg)) {
        setErro("Permissão de microfone negada. Libere no cadeado da barra de endereço.");
      } else if (!/aborted|cancel/i.test(msg)) {
        setErro(msg);
      }
    }
  }, [micEscolhido]);

  const iniciar = useCallback(async () => {
    setErro(null);
    setParcial("");
    // `final` NÃO é zerado: reiniciar aqui é complementar a mesma resposta. Quem
    // troca de pergunta troca o `perguntaId`, e aí o componente inteiro é outro.
    setDuracao(0);
    try {
      await capturaRef.current?.iniciarResposta(perguntaId);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível iniciar.");
    }
  }, [perguntaId]);

  const finalizar = useCallback(() => {
    setOcupado(true);
    capturaRef.current?.finalizarResposta();
  }, []);

  const gravando = estado === "gravando";
  const pausado = estado === "pausado";
  const emCurso = gravando || pausado;
  const temAudio = estado !== "sem-audio";

  const [ponto, textoPonto]: [React.ReactNode, string] = {
    "sem-audio": [<i key="p" className="w-2 h-2 flex-none border border-tinta-3" />, "microfone desligado"],
    /* A fonte caiu e está voltando — a entrevista NÃO acabou.
     *
     * Precisa aparecer na tela: antes, trocar de microfone emudecia a
     * transcrição pelo resto da entrevista e o indicador continuava verde,
     * dizendo "microfone aberto". Quem conduz só descobria no fim, sem áudio. */
    recuperando: [
      <i
        key="p"
        className="w-2 h-2 flex-none bg-atencao animate-[respirar_2s_ease-in-out_infinite] motion-reduce:animate-none"
      />,
      "reabrindo o áudio…",
    ],
    capturando: [<i key="p" className="w-2 h-2 flex-none bg-ok" />, "microfone aberto"],
    gravando: [
      <i
        key="p"
        className="w-2 h-2 flex-none bg-critico animate-[pulsarForte_1.4s_ease-in-out_infinite] motion-reduce:animate-none"
      />,
      "gravando resposta",
    ],
    // Pausado ainda é uma resposta aberta: o ponto não pode voltar a "microfone
    // aberto", que é o estado de entre perguntas.
    pausado: [<i key="p" className="w-2 h-2 flex-none bg-ok" />, "pausado — a resposta continua aberta"],
  }[estado] as [React.ReactNode, string];

  return (
    <div className="border-t-[3px] border-double border-borda-forte pt-3 mb-5">
      <span className="block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3 mb-2">
        ENTREVISTA AO VIVO
      </span>
      <p className="mb-3 mt-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
        Ligue o microfone uma vez no começo da entrevista. Depois é só iniciar e
        finalizar a cada pergunta — o microfone continua aberto entre elas.
      </p>

      <div className="flex gap-[10px] items-center flex-wrap">
        <button type="button" className={SECUNDARIO} onClick={selecionar} disabled={emCurso}>
          {temAudio ? "Trocar microfone" : "Ligar microfone"}
        </button>

        {!emCurso ? (
          <button type="button" className={BOTAO} onClick={iniciar} disabled={!temAudio || ocupado}>
            {ocupado ? "Transcrevendo…" : final ? "Adicionar complemento" : "Iniciar resposta"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className={SECUNDARIO}
              onClick={() =>
                pausado ? capturaRef.current?.retomar() : capturaRef.current?.pausar()
              }
            >
              {pausado ? "Retomar" : "Pausar"}
            </button>
            <button type="button" className={gravando ? BOTAO_GRAVANDO : BOTAO} onClick={finalizar}>
              Finalizar resposta
            </button>
          </>
        )}

        {temAudio && (
          <button
            type="button"
            className={SECUNDARIO}
            onClick={() => capturaRef.current?.encerrar()}
            disabled={emCurso}
          >
            Encerrar captura
          </button>
        )}

        {microfones.length > 1 && (
          <select
            className="border border-borda-forte bg-papel-2 text-tinta font-normal text-[11px] leading-none font-ui px-[10px] py-[9px] max-w-[210px] [&>option]:bg-papel [&>option]:text-tinta"
            value={micEscolhido}
            onChange={(e) => setMicEscolhido(e.target.value)}
            disabled={emCurso}
            aria-label="Microfone"
          >
            <option value="">Microfone padrão</option>
            {microfones.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nome}
              </option>
            ))}
          </select>
        )}

        <span className="text-[11px] font-normal leading-[1.4] font-codigo text-tinta-3 ml-auto flex items-center gap-[7px]">
          {ponto}
          {textoPonto}
        </span>
      </div>

      {erro && (
        <div className="mt-3 border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui">
          {erro}
        </div>
      )}

      {pergunta && (
        <p className="mt-[14px] mb-0 px-3 py-[10px] border-l-2 border-borda-forte font-normal text-[13.5px] leading-[1.5] font-titulo">
          {pergunta}
        </p>
      )}

      <div
        className="mt-[10px] border border-borda-forte bg-papel-2 p-3 min-h-[76px] font-normal text-[13px] leading-[1.7] font-ui whitespace-pre-wrap"
        aria-live="polite"
      >
        {final ? (
          <span className="text-tinta">{final}</span>
        ) : parcial ? (
          <span className="text-tinta-3">{parcial}</span>
        ) : (
          <span className="text-tinta-3 italic">{gravando ? "Ouvindo…" : "A transcrição aparece aqui."}</span>
        )}
      </div>

      {duracao > 0 && (
        <span className="text-[11px] font-normal leading-none font-codigo tabular-nums text-tinta-3 mt-[6px] block">
          resposta de {duracao.toFixed(1)}s
        </span>
      )}

      {temAudio && (
        <p className="mt-[10px] mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-atencao">
          O microfone está aberto e a conversa é transcrita. Informe o cliente — o
          roteiro de acolhimento promete sigilo, mas não menciona gravação.
        </p>
      )}
    </div>
  );
}
