"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import { CapturaEntrevista } from "@/lib/transcricao";
import estilos from "./ChamadaAoVivo.module.css";

/* Entrevista por chamada de voz, do lado do advogado — na tela do checklist.
 *
 * A chamada em si é a MESMA que roda no resto do app: ela vive no
 * `ProvedorChamada` e PERMANECE ao vir da entrevista para cá. Se o atendente já
 * estava na chamada com o cliente, ela continua aqui; senão, dá para abrir uma
 * na sala do caso. Assim o escritório acompanha o cliente enquanto ele envia os
 * documentos, sem largar a conversa.
 *
 * A faixa remota — a voz do cliente, isolada — alimenta a transcrição, e o que
 * aparece é só o que ele falou, sem o entrevistador no meio. */

interface Props {
  /** Token do portal do caso. Nomeia a sala, caso ainda não haja chamada. */
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
  const chamada = useChamada();
  const [temFaixa, setTemFaixa] = useState(false);
  const [gravando, setGravando] = useState(false);
  const [transcrevendo, setTranscrevendo] = useState(false);
  const [entrando, setEntrando] = useState(false);
  const [parcial, setParcial] = useState("");
  const [falas, setFalas] = useState<Fala[]>([]);
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  const capturaRef = useRef<CapturaEntrevista | null>(null);
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
  }

  // Enquanto o checklist está na tela, o painel flutuante se recolhe: a chamada
  // já está aqui. `registrarPainel` é estável, então roda uma vez.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  // A voz do cliente, quando chega, vira a fonte da transcrição. Assina uma vez
  // (`aoReceberFaixa` é estável) — re-assinar remontaria o áudio a cada render.
  useEffect(
    () =>
      chamada.aoReceberFaixa((trilha) => {
        void capturaRef.current
          ?.usarTrilha(trilha)
          .then(() => {
            setTemFaixa(true);
            setErro(null);
          })
          .catch(() =>
            setErro("A chamada conectou, mas a transcrição não pôde ler o áudio."),
          );
      }),
    [chamada.aoReceberFaixa],
  );

  // Cliente saiu: não há mais voz para transcrever.
  useEffect(() => {
    if (chamada.estado !== "falando") setTemFaixa(false);
  }, [chamada.estado]);

  /* Sair do checklist NÃO desliga a chamada (ela permanece no painel flutuante).
   * Só encerra a captura desta tela — a transcrição para, a conversa não. A
   * captura solta o AudioContext, mas não para a faixa remota, que é do outro. */
  useEffect(() => () => capturaRef.current?.encerrar(), []);

  const chamar = useCallback(async () => {
    setErro(null);
    setEntrando(true);
    try {
      await chamada.entrar(sala, "advogado", { nome: "Escritório" });
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
  }, [sala, chamada]);

  const desligar = useCallback(() => {
    chamada.desligar();
    capturaRef.current?.encerrar();
    setTemFaixa(false);
    setGravando(false);
    setTranscrevendo(false);
    setParcial("");
  }, [chamada]);

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
      // seleção manual, não vale interromper o atendimento com um erro.
    }
  }

  const naChamada = chamada.ativa;
  const ponto =
    chamada.estado === "falando"
      ? estilos.pontoAtivo
      : chamada.estado === "aguardando" || chamada.estado === "conectando"
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
              onClick={chamada.alternarMudo}
            >
              {chamada.mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </button>

            <button type="button" className={estilos.secundario} onClick={desligar}>
              Desligar
            </button>
          </>
        )}

        <span className={estilos.estado}>
          <i className={`${estilos.ponto} ${ponto}`} />
          {LEGENDA[chamada.estado]}
        </span>
      </div>

      {(erro || chamada.erro) && <div className={estilos.erro}>{erro ?? chamada.erro}</div>}

      {aviso && (
        <p className={estilos.aviso} aria-live="polite">
          {aviso}
        </p>
      )}

      {chamada.estado === "aguardando" && (
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
