"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CapturaEntrevista } from "@/lib/transcricao";
import type { EstadoCaptura, Microfone } from "@/lib/transcricao";
import estilos from "./EntrevistaAoVivo.module.css";

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

  const pontos: [string, string] = {
    "sem-audio": [estilos.pontoOcioso, "microfone desligado"],
    capturando: [estilos.pontoPronto, "microfone aberto"],
    gravando: [estilos.pontoGravando, "gravando resposta"],
    // Pausado ainda é uma resposta aberta: o ponto não pode voltar a "microfone
    // aberto", que é o estado de entre perguntas.
    pausado: [estilos.pontoPronto, "pausado — a resposta continua aberta"],
  }[estado] as [string, string];

  return (
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>ENTREVISTA AO VIVO</span>
      <p className={estilos.texto}>
        Ligue o microfone uma vez no começo da entrevista. Depois é só iniciar e
        finalizar a cada pergunta — o microfone continua aberto entre elas.
      </p>

      <div className={estilos.acoes}>
        <button
          type="button"
          className={estilos.secundario}
          onClick={selecionar}
          disabled={emCurso}
        >
          {temAudio ? "Trocar microfone" : "Ligar microfone"}
        </button>

        {!emCurso ? (
          <button
            type="button"
            className={estilos.botao}
            onClick={iniciar}
            disabled={!temAudio || ocupado}
          >
            {ocupado ? "Transcrevendo…" : final ? "Adicionar complemento" : "Iniciar resposta"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className={estilos.secundario}
              onClick={() =>
                pausado ? capturaRef.current?.retomar() : capturaRef.current?.pausar()
              }
            >
              {pausado ? "Retomar" : "Pausar"}
            </button>
            <button
              type="button"
              className={`${estilos.botao} ${gravando ? estilos.gravando : ""}`}
              onClick={finalizar}
            >
              Finalizar resposta
            </button>
          </>
        )}

        {temAudio && (
          <button
            type="button"
            className={estilos.secundario}
            onClick={() => capturaRef.current?.encerrar()}
            disabled={emCurso}
          >
            Encerrar captura
          </button>
        )}

        {microfones.length > 1 && (
          <select
            className={estilos.seletor}
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

        <span className={estilos.estado}>
          <i className={`${estilos.ponto} ${pontos[0]}`} />
          {pontos[1]}
        </span>
      </div>

      {erro && <div className={estilos.erro}>{erro}</div>}

      {pergunta && <p className={estilos.pergunta}>{pergunta}</p>}

      <div className={estilos.transcricao} aria-live="polite">
        {final ? (
          <span className={estilos.final}>{final}</span>
        ) : parcial ? (
          <span className={estilos.parcial}>{parcial}</span>
        ) : (
          <span className={estilos.vazio}>
            {gravando ? "Ouvindo…" : "A transcrição aparece aqui."}
          </span>
        )}
      </div>

      {duracao > 0 && (
        <span className={estilos.duracao}>resposta de {duracao.toFixed(1)}s</span>
      )}

      {temAudio && (
        <p className={estilos.aviso}>
          O microfone está aberto e a conversa é transcrita. Informe o cliente — o
          roteiro de acolhimento promete sigilo, mas não menciona gravação.
        </p>
      )}
    </div>
  );
}
