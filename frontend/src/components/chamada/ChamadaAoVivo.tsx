"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import { CapturaEntrevista } from "@/lib/transcricao";
import { Botao } from "@/components/ui/Basicos";
import IndicadorVoz from "@/components/chamada/IndicadorVoz";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

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
  const [faixaRemota, setFaixaRemota] = useState<MediaStreamTrack | null>(null);

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
        setFaixaRemota(trilha);
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
    if (chamada.estado !== "falando") {
      setTemFaixa(false);
      setFaixaRemota(null);
    }
  }, [chamada.estado]);

  /* Sair do checklist NÃO desliga a chamada (ela permanece no painel flutuante).
   * Só encerra a captura desta tela — a transcrição para, a conversa não. A
   * captura solta o AudioContext, mas não para a faixa remota, que é do outro. */
  useEffect(() => () => capturaRef.current?.encerrar(), []);

  const chamar = useCallback(async () => {
    setErro(null);
    setEntrando(true);
    try {
      const { token, p2p } = await criarSalaChamada(sala);
      await chamada.entrar(sala, "advogado", { nome: "Escritório", p2p }, token);
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
    chamada.estado === "falando" ? (
      <i className="w-2 h-2 flex-none bg-ok" />
    ) : chamada.estado === "aguardando" || chamada.estado === "conectando" ? (
      <i className="w-2 h-2 flex-none bg-atencao animate-[respirar_2s_ease-in-out_infinite] motion-reduce:animate-none" />
    ) : (
      <i className="w-2 h-2 flex-none border border-tinta-3" />
    );

  return (
    <div className="border-t-[3px] border-double border-borda-forte pt-3 mb-5">
      <span className="block text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3 mb-2">
        ENTREVISTA POR CHAMADA
      </span>
      <p className="mb-3 mt-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3 max-w-[64ch]">
        O cliente entra pelo mesmo link do portal, com a mesma senha. A voz dele chega
        numa faixa separada da sua — e é só ela que vira texto.
      </p>

      <div className="flex gap-[10px] items-start flex-wrap">
        {!naChamada ? (
          <BotaoProcesso
            variante="primario"
            pequeno
            onClick={chamar}
            processando={entrando}
            textoProcessando="Abrindo a chamada…"
          >
            Entrar na chamada
          </BotaoProcesso>
        ) : (
          <>
            {/* Transcrevendo: vermelho, porque é estado que precisa saltar aos olhos. */}
            <BotaoProcesso
              variante={gravando ? "perigo" : "primario"}
              pequeno
              onClick={alternarTranscricao}
              processando={transcrevendo}
              textoProcessando={gravando ? "Transcrevendo…" : "Iniciando…"}
              pendencia={temFaixa ? null : "Só depois que o cliente entrar na chamada."}
            >
              {gravando ? "Encerrar fala" : "Transcrever fala do cliente"}
            </BotaoProcesso>

            <Botao variante="secundario" pequeno onClick={chamada.alternarMudo}>
              {chamada.mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </Botao>

            <Botao variante="secundario" pequeno onClick={desligar}>
              Desligar
            </Botao>
          </>
        )}

        <span className="text-[11px] font-normal leading-[1.4] font-codigo text-tinta-3 ml-auto flex items-center gap-[7px]">
          {ponto}
          {LEGENDA[chamada.estado]}
        </span>
      </div>

      {naChamada && (
        <>
          <IndicadorVoz trilha={faixaRemota} titulo="Voz do cliente" />
          <IndicadorVoz trilha={chamada.faixaLocal} titulo="Sua voz" mudo={chamada.mudo} />
        </>
      )}

      {(erro || chamada.erro) && (
        <div className="mt-3 border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui">
          {erro ?? chamada.erro}
        </div>
      )}

      {aviso && (
        <p className="mt-[10px] mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-atencao" aria-live="polite">
          {aviso}
        </p>
      )}

      {chamada.estado === "aguardando" && (
        <p className="mt-3 mb-0 font-normal text-[12px] leading-[1.5] font-ui text-atencao max-w-[64ch]">
          Avise o cliente para abrir o link do portal e tocar em “Entrar na chamada”. Assim
          que ele entrar, o áudio conecta sozinho.
        </p>
      )}

      {(falas.length > 0 || parcial) && (
        <div
          className="mt-3 border border-borda-forte bg-papel-2 px-[14px] py-3 max-h-[320px] overflow-y-auto"
          aria-live="polite"
        >
          {falas.map((f, i) => (
            <p key={i} className="mb-[10px] mt-0 font-normal text-[13px] leading-[1.7] font-ui whitespace-pre-wrap last:mb-0">
              {f.texto}
              <span className="ml-2 font-normal text-[10.5px] leading-none font-codigo tabular-nums text-tinta-3 whitespace-nowrap">
                {f.duracaoS.toFixed(1)}s
              </span>
            </p>
          ))}
          {parcial && (
            <p className="m-0 font-normal text-[13px] leading-[1.7] font-ui text-tinta-3 whitespace-pre-wrap">
              {parcial}
            </p>
          )}
        </div>
      )}

      {falas.length > 0 && (
        <Botao variante="secundario" pequeno className="mt-[10px]" onClick={copiar}>
          {copiado ? "✓ Copiado" : "Copiar transcrição"}
        </Botao>
      )}

      {naChamada && (
        <p className="mt-[10px] mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-atencao">
          A conversa está sendo transcrita. Avise o cliente — o roteiro de acolhimento
          promete sigilo, mas não menciona gravação.
        </p>
      )}
    </div>
  );
}
