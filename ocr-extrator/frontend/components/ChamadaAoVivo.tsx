"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ChamadaJitsi } from "@/lib/chamadaJitsi";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import { CapturaEntrevista } from "@/lib/transcricao";
import estilos from "./ChamadaAoVivo.module.css";

/* Entrevista por chamada de voz, do lado do advogado.
 *
 * A peça que faz isto valer a pena é a ligação entre os dois módulos: a
 * `ChamadaJitsi` entrega a faixa remota — a voz do CLIENTE, isolada — e ela vai
 * direto para a `CapturaEntrevista`. O microfone do advogado não entra na
 * transcrição: ele vai para a chamada e para.
 *
 * Por isso o que aparece aqui é só o que o cliente falou, sem diarização e sem
 * o entrevistador no meio do texto. */

interface Props {
  /** Token do portal do caso. É o nome da sala — o cliente já o tem no link. */
  sala: string;
  /** Cada fala fechada, já transcrita. */
  onFala?: (texto: string) => void;
}

interface Fala {
  texto: string;
  duracaoS: number;
}

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "fora da chamada",
  aguardando: "esperando o cliente",
  conectando: "conectando…",
  falando: "em chamada",
  encerrada: "chamada encerrada",
};

export default function ChamadaAoVivo({ sala, onFala }: Props) {
  const [estado, setEstado] = useState<EstadoChamada>("fora");
  const [temFaixa, setTemFaixa] = useState(false);
  const [gravando, setGravando] = useState(false);
  const [transcrevendo, setTranscrevendo] = useState(false);
  const [mudo, setMudo] = useState(false);
  const [entrando, setEntrando] = useState(false);
  const [parcial, setParcial] = useState("");
  const [falas, setFalas] = useState<Fala[]>([]);
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  const chamadaRef = useRef<ChamadaJitsi | null>(null);
  const capturaRef = useRef<CapturaEntrevista | null>(null);
  // Numera as falas para o servidor de transcrição. Os callbacks são fixados na
  // construção e não enxergariam um estado do React.
  const contador = useRef(0);
  const onFalaRef = useRef(onFala);
  onFalaRef.current = onFala;

  if (capturaRef.current === null && typeof window !== "undefined") {
    capturaRef.current = new CapturaEntrevista({
      onParcial: (texto) => {
        setAviso(null);
        setParcial(texto);
      },
      onAviso: setAviso,
      onFinal: (texto, duracaoS) => {
        setParcial("");
        setTranscrevendo(false);
        setGravando(false);
        if (!texto.trim()) return;
        setFalas((f) => [...f, { texto, duracaoS }]);
        onFalaRef.current?.(texto);
      },
      onErro: (m) => {
        setErro(m);
        setTranscrevendo(false);
        setGravando(false);
      },
    });

    chamadaRef.current = new ChamadaJitsi("advogado", {
      onEstado: (e) => {
        setEstado(e);
        // A faixa remota morre junto com o par: se o cliente saiu, não há mais
        // voz para transcrever, e deixar o botão ativo prometeria o impossível.
        if (e === "aguardando" || e === "encerrada" || e === "fora") setTemFaixa(false);
      },
      onFaixaRemota: (trilha) => {
        // É aqui que a voz do cliente vira texto: a faixa que chegou pela
        // chamada substitui o microfone como fonte da transcrição.
        void capturaRef.current
          ?.usarTrilha(trilha)
          .then(() => {
            setTemFaixa(true);
            setErro(null);
          })
          .catch(() =>
            setErro("A chamada conectou, mas a transcrição não pôde ler o áudio."),
          );
      },
      onErro: setErro,
    });
  }

  /* A chamada segura o microfone e a captura segura um AudioContext: sair da
   * tela sem soltar deixaria o indicador de gravação do navegador aceso e a
   * sala ocupada por um fantasma. */
  useEffect(
    () => () => {
      chamadaRef.current?.desligar();
      capturaRef.current?.encerrar();
    },
    [],
  );

  const chamar = useCallback(async () => {
    setErro(null);
    setEntrando(true);
    try {
      await chamadaRef.current?.entrar(sala, { nome: "Escritório" });
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível entrar na chamada.";
      setErro(
        /NotAllowedError|denied/i.test(m)
          ? "Permissão de microfone negada. Libere no cadeado da barra de endereço."
          : m,
      );
    } finally {
      setEntrando(false);
    }
  }, [sala]);

  const desligar = useCallback(() => {
    chamadaRef.current?.desligar();
    capturaRef.current?.encerrar();
    setTemFaixa(false);
    setGravando(false);
    setTranscrevendo(false);
    setParcial("");
  }, []);

  const alternarTranscricao = useCallback(async () => {
    setErro(null);
    if (gravando) {
      setTranscrevendo(true); // o texto final ainda vem do servidor
      capturaRef.current?.finalizarResposta();
      return;
    }
    try {
      contador.current += 1;
      await capturaRef.current?.iniciarResposta(`fala-${contador.current}`);
      setGravando(true);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível iniciar a transcrição.");
    }
  }, [gravando]);

  const texto = falas.map((f) => f.texto).join("\n\n");

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto está na tela para
      // seleção manual, não vale interromper a entrevista com um erro.
    }
  }

  const naChamada = estado !== "fora";
  const ponto =
    estado === "falando"
      ? estilos.pontoAtivo
      : estado === "aguardando" || estado === "conectando"
        ? estilos.pontoEsperando
        : estilos.pontoOcioso;

  return (
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>ENTREVISTA POR CHAMADA</span>
      <p className={estilos.texto}>
        O cliente entra pelo mesmo link do portal, com a mesma senha. A voz dele chega
        numa faixa separada da sua — e é só ela que vira texto.
      </p>

      <div className={estilos.acoes}>
        {!naChamada ? (
          <button
            type="button"
            className={estilos.botao}
            onClick={chamar}
            disabled={entrando}
          >
            {entrando ? "Abrindo…" : "Entrar na chamada"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className={`${estilos.botao} ${gravando ? estilos.gravando : ""}`}
              onClick={alternarTranscricao}
              disabled={!temFaixa || transcrevendo}
              title={temFaixa ? "" : "Só depois que o cliente entrar na chamada"}
            >
              {transcrevendo
                ? "Transcrevendo…"
                : gravando
                  ? "Encerrar fala"
                  : "Transcrever fala do cliente"}
            </button>

            <button
              type="button"
              className={estilos.secundario}
              onClick={() => setMudo(chamadaRef.current?.alternarMudo() ?? false)}
            >
              {mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </button>

            <button type="button" className={estilos.secundario} onClick={desligar}>
              Desligar
            </button>
          </>
        )}

        <span className={estilos.estado}>
          <i className={`${estilos.ponto} ${ponto}`} />
          {LEGENDA[estado]}
        </span>
      </div>

      {erro && <div className={estilos.erro}>{erro}</div>}

      {aviso && (
        <p className={estilos.aviso} aria-live="polite">
          {aviso}
        </p>
      )}

      {estado === "aguardando" && (
        <p className={estilos.espera}>
          Avise o cliente para abrir o link do portal e tocar em “Entrar na chamada”. Assim
          que ele entrar, o áudio conecta sozinho.
        </p>
      )}

      {(falas.length > 0 || parcial) && (
        <div className={estilos.transcricao} aria-live="polite">
          {falas.map((f, i) => (
            <p key={i} className={estilos.fala}>
              {f.texto}
              <span className={estilos.duracao}>{f.duracaoS.toFixed(1)}s</span>
            </p>
          ))}
          {parcial && <p className={estilos.parcial}>{parcial}</p>}
        </div>
      )}

      {falas.length > 0 && (
        <button type="button" className={estilos.secundario} onClick={copiar}>
          {copiado ? "✓ Copiado" : "Copiar transcrição"}
        </button>
      )}

      {naChamada && (
        <p className={estilos.aviso}>
          A conversa está sendo transcrita. Avise o cliente — o roteiro de acolhimento
          promete sigilo, mas não menciona gravação.
        </p>
      )}
    </div>
  );
}
