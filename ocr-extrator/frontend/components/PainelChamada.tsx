"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { ChamadaJitsi } from "@/lib/chamadaJitsi";
import type { EstadoChamada, Participante } from "@/lib/chamadaJitsi";
import estilos from "./PainelChamada.module.css";
import Retratos from "./Retratos";

/* A chamada ao lado do roteiro — a coluna da direita da entrevista.
 *
 * O que este painel resolve não é conversar: é DE QUEM é a voz transcrita. O
 * WebRTC entrega a faixa do outro lado separada da nossa, então o que sobe para
 * o Whisper é só o entrevistado. Sem isso, transcrever a entrevista significaria
 * captar o microfone do advogado e junto dele o cliente saindo do alto-falante:
 * abafado, atrasado e misturado com a própria pergunta.
 *
 * A sala é sorteada aqui, não amarrada ao caso: a entrevista acontece antes de
 * o caso existir — é ela que decide a categoria. */

interface Props {
  /** Recebe a voz do entrevistado assim que a chamada conecta. */
  onFaixaRemota: (trilha: MediaStreamTrack) => void;
  /** A chamada caiu ou foi desligada: a transcrição perde a fonte. */
  onFimDaFaixa?: () => void;
}

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "chamada desligada",
  aguardando: "esperando o entrevistado",
  conectando: "conectando…",
  falando: "em chamada",
  encerrada: "chamada encerrada",
};

export default function PainelChamada({ onFaixaRemota, onFimDaFaixa }: Props) {
  const [sala, setSala] = useState<{ sala: string; url: string } | null>(null);
  const [estado, setEstado] = useState<EstadoChamada>("fora");
  const [abrindo, setAbrindo] = useState(false);
  const [mudo, setMudo] = useState(false);
  const [camera, setCamera] = useState(false);
  const [participantes, setParticipantes] = useState<Participante[]>([]);
  const [copiado, setCopiado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const chamada = useRef<ChamadaJitsi | null>(null);
  // Os callbacks da chamada são fixados na construção e não enxergariam props
  // novas; o ref mantém sempre o mais recente.
  const aoReceber = useRef(onFaixaRemota);
  aoReceber.current = onFaixaRemota;
  const aoPerder = useRef(onFimDaFaixa);
  aoPerder.current = onFimDaFaixa;

  if (chamada.current === null && typeof window !== "undefined") {
    chamada.current = new ChamadaJitsi("advogado", {
      onEstado: (e) => {
        setEstado(e);
        if (e === "aguardando" || e === "encerrada" || e === "fora") aoPerder.current?.();
      },
      onFaixaRemota: (trilha) => aoReceber.current(trilha),
      onParticipantes: setParticipantes,
      onErro: setErro,
    });
  }

  useEffect(() => () => chamada.current?.desligar(), []);

  const abrir = useCallback(async () => {
    setErro(null);
    setAbrindo(true);
    try {
      const nova = sala ?? (await criarSalaChamada());
      setSala(nova);
      await chamada.current?.entrar(nova.sala, { nome: "Escritório" });
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir a chamada.";
      setErro(
        /NotAllowedError|denied/i.test(m)
          ? "Permissão de microfone negada. Libere no cadeado da barra de endereço."
          : m,
      );
    } finally {
      setAbrindo(false);
    }
  }, [sala]);

  async function copiar(texto: string, qual: string) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(qual);
      setTimeout(() => setCopiado(null), 2000);
    } catch {
      // Sem permissão de área de transferência: o link está na tela para
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
    <aside className={estilos.painel}>
      <div className={estilos.topo}>
        <span className={estilos.rotulo}>CHAMADA</span>
        <span className={estilos.estado}>
          <i className={`${estilos.ponto} ${ponto}`} />
          {LEGENDA[estado]}
        </span>
      </div>

      {!naChamada ? (
        <>
          <p className={estilos.texto}>
            Abra a chamada e mande o link ao entrevistado. A voz dele chega separada da sua
            — é ela, e só ela, que vira texto no roteiro.
          </p>
          <button type="button" className={estilos.botao} onClick={abrir} disabled={abrindo}>
            {abrindo ? "Abrindo…" : "Abrir chamada"}
          </button>
        </>
      ) : (
        <>
          {sala && (
            <div className={estilos.convite}>
              <span className={estilos.rotuloPequeno}>LINK PARA O ENTREVISTADO</span>
              <span className={estilos.link}>{sala.url}</span>
              <div className={estilos.acoes}>
                <button
                  type="button"
                  className={estilos.secundario}
                  onClick={() => copiar(sala.url, "url")}
                >
                  {copiado === "url" ? "✓ Copiado" : "Copiar link"}
                </button>
                <button
                  type="button"
                  className={estilos.secundario}
                  onClick={() =>
                    copiar(
                      `Olá! Para a nossa conversa, entre por aqui: ${sala.url}`,
                      "msg",
                    )
                  }
                >
                  {copiado === "msg" ? "✓ Copiado" : "Copiar mensagem"}
                </button>
              </div>
            </div>
          )}

          {estado === "aguardando" && (
            <p className={estilos.espera}>
              Mande o link e deixe esta tela aberta. Quando ele entrar, o áudio conecta
              sozinho e o gravador de cada pergunta passa a ouvir a voz dele.
            </p>
          )}

          {estado === "falando" && (
            <p className={estilos.pronto}>
              A voz do entrevistado está chegando. Use “Gravar resposta” em cada pergunta do
              roteiro — o que for transcrito é a fala dele, não a sua.
            </p>
          )}

          <Retratos participantes={participantes} tamanho="coluna" />

          <div className={estilos.acoes}>
            <button
              type="button"
              className={estilos.secundario}
              onClick={async () => setCamera(await (chamada.current?.alternarCamera() ?? false))}
            >
              {camera ? "Desligar câmera" : "Ligar câmera"}
            </button>
            <button
              type="button"
              className={estilos.secundario}
              onClick={() => setMudo(chamada.current?.alternarMudo() ?? false)}
            >
              {mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </button>
            <button
              type="button"
              className={estilos.secundario}
              onClick={() => {
                chamada.current?.desligar();
                setMudo(false);
                setCamera(false);
              }}
            >
              Desligar
            </button>
          </div>
        </>
      )}

      {erro && <div className={estilos.erro}>{erro}</div>}

      <p className={estilos.aviso}>
        A conversa é transcrita. O roteiro de acolhimento promete sigilo, mas não menciona
        gravação — avise o cliente antes de começar.
      </p>
    </aside>
  );
}
