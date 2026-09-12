"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, CameraOff, Mic, MicOff, MonitorUp, PhoneOff, Volume2 } from "lucide-react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "@/components/ui/Retratos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";

/* A chamada ao lado do roteiro — a coluna da direita da entrevista.
 *
 * O que este painel resolve não é conversar: é DE QUEM é a voz transcrita. O
 * WebRTC entrega a faixa do outro lado separada da nossa, então o que sobe para
 * o Whisper é só o entrevistado. Sem isso, transcrever a entrevista significaria
 * captar o microfone do advogado e junto dele o cliente saindo do alto-falante:
 * abafado, atrasado e misturado com a própria pergunta.
 *
 * A chamada em si não mora mais aqui: ela vive no `ProvedorChamada`, na raiz do
 * app, para PERMANECER quando o atendente sai da entrevista para o checklist.
 * Este painel só a inicia, mostra o link e os retratos, e some — a ligação
 * continua no painel flutuante (`DockChamada`). Enquanto este painel está na
 * tela, o flutuante se recolhe (`registrarPainel`), para a chamada não aparecer
 * duas vezes. */

interface Props {
  /** Recebe a voz do entrevistado assim que a chamada conecta. */
  onFaixaRemota: (trilha: MediaStreamTrack) => void;
  /** A chamada caiu ou foi desligada: a transcrição perde a fonte. */
  onFimDaFaixa?: () => void;
  /** No fluxo de entrevista pronta, a chamada acompanha a coleta de documentos. */
  modo?: "roteiro" | "documentos";
}

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "chamada desligada",
  aguardando: "esperando o entrevistado",
  conectando: "conectando…",
  falando: "em chamada",
  encerrada: "chamada encerrada",
};

/* Duas classes, e não uma, porque há dois tipos de botão neste painel.
 *
 * Os controles da chamada (câmera, tela, microfone, desligar) viraram ícone —
 * caixa quadrada de 40px. Já "Copiar link" e "Copiar mensagem" continuam sendo
 * TEXTO: são a ação de mandar a sala para o cliente, e um ícone de prancheta não
 * diz qual dos dois formatos vai para o WhatsApp dele.
 *
 * Com uma classe só, os dois botões de copiar ficavam espremidos numa caixa de
 * 40x40 — justamente na tela que o atendente usa antes de o cliente entrar. */
const BOTAO_ICONE =
  "grid h-10 w-10 place-items-center rounded-campo border border-borda bg-papel text-tinta cursor-pointer " +
  "hover:bg-papel-2 hover:border-borda-forte focus:outline-none focus:ring-2 focus:ring-acao";

const BOTAO_SECUNDARIO =
  "flex-1 min-w-[118px] border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none " +
  "font-ui tracking-[0.08em] uppercase px-[10px] py-[9px] cursor-pointer hover:bg-papel-2";

export default function PainelChamada({ onFaixaRemota, onFimDaFaixa, modo = "roteiro" }: Props) {
  const chamada = useChamada();
  const [sala, setSala] = useState<{ sala: string; url: string; token: string } | null>(null);
  const [abrindo, setAbrindo] = useState(false);
  const [copiado, setCopiado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // As props chegam por callbacks inline do pai (novos a cada render); o ref
  // deixa as assinaturas serem feitas UMA vez e ainda chamarem o mais recente.
  // Sem isso, cada render do pai re-assinaria e remontaria o áudio da faixa.
  const onFaixaRef = useRef(onFaixaRemota);
  onFaixaRef.current = onFaixaRemota;
  const onFimRef = useRef(onFimDaFaixa);
  onFimRef.current = onFimDaFaixa;

  // Enquanto este painel está montado, o flutuante se recolhe: a chamada já
  // está inteira aqui. `registrarPainel` é estável, então roda uma vez.
  useEffect(() => chamada.registrarPainel(), [chamada.registrarPainel]);

  // A voz do entrevistado alimenta a transcrição. A assinatura entrega a faixa
  // que já chegou (se o painel montou depois dela) e as próximas.
  useEffect(
    () => chamada.aoReceberFaixa((trilha) => onFaixaRef.current(trilha)),
    [chamada.aoReceberFaixa],
  );

  // Sem faixa não há o que transcrever: o cliente saiu, ou a chamada caiu.
  useEffect(() => {
    if (chamada.estado === "aguardando" || chamada.estado === "encerrada" || chamada.estado === "fora") {
      onFimRef.current?.();
    }
  }, [chamada.estado]);

  const abrir = useCallback(async () => {
    setErro(null);
    setAbrindo(true);
    try {
      // Se já há uma chamada de pé (por exemplo, retomada), reaproveita a sala.
      const nova = sala ?? (await criarSalaChamada());
      setSala(nova);
      await chamada.entrar(nova.sala, "advogado", { nome: "Escritório" }, nova.token);
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
  }, [sala, chamada]);

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
    <aside className="border border-borda-forte px-4 pt-[14px] pb-4 bg-papel">
      <div className="flex justify-between items-center gap-[10px] flex-wrap mb-[10px]">
        <span className="text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          {modo === "documentos" ? "JITSI MEET · CHAMADA E GRAVAÇÃO" : "JITSI MEET"}
        </span>
        <span className="text-[11px] font-normal leading-[1.4] font-codigo text-tinta-3 flex items-center gap-[7px]">
          {ponto}
          {LEGENDA[chamada.estado]}
        </span>
      </div>

      {!naChamada ? (
        <>
          <p className="mb-3 mt-0 font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
            {modo === "documentos"
              ? "Crie a chamada no Jitsi Meet e mande o link ao cliente. Você continua na aba de documentos, e a conversa entra na mesma gravação do atendimento."
              : "Abra a chamada e mande o link ao entrevistado. A voz dele chega separada da sua — é ela, e só ela, que vira texto no roteiro."}
          </p>
          <BotaoProcesso
            variante="primario"
            bloco
            onClick={abrir}
            processando={abrindo}
            textoProcessando="Abrindo a chamada…"
            erro={erro}
          >
            {modo === "documentos" ? "Criar chamada no Jitsi Meet" : "Abrir Jitsi Meet"}
          </BotaoProcesso>
        </>
      ) : (
        <>
          {sala && (
            <div className="border border-dashed border-borda-forte px-3 py-[10px] mb-3">
              <span className="block text-[9.5px] font-semibold leading-none font-ui tracking-[0.12em] text-tinta-3 mb-[6px]">
                LINK PARA O ENTREVISTADO
              </span>
              <span className="block text-[11px] font-normal leading-[1.5] font-codigo [word-break:break-all] text-tinta mb-[10px]">
                {sala.url}
              </span>
              <div className="flex gap-2 flex-wrap mt-[10px]">
                <button type="button" className={BOTAO_SECUNDARIO} onClick={() => copiar(sala.url, "url")}>
                  {copiado === "url" ? "✓ Copiado" : "Copiar link"}
                </button>
                <button
                  type="button"
                  className={BOTAO_SECUNDARIO}
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

          <div className="mb-2 flex items-center gap-2 text-xs text-tinta-3" title={chamada.estado === "falando" ? "Áudio do entrevistado conectado" : "Aguardando áudio do entrevistado"}>
            <Volume2 size={15} className={chamada.estado === "falando" ? "text-ok" : "text-atencao"} aria-hidden />
            <span>{chamada.estado === "falando" ? "Áudio conectado" : "Aguardando áudio"}</span>
          </div>

          <Retratos participantes={chamada.participantes} tamanho="coluna" />

          <div className="flex gap-2 flex-wrap mt-[10px]">
            <button type="button" title={chamada.temCamera ? "Desligar câmera" : "Ligar câmera"} aria-label={chamada.temCamera ? "Desligar câmera" : "Ligar câmera"} className={BOTAO_ICONE} onClick={() => void chamada.alternarCamera()}>
              {chamada.temCamera ? <CameraOff size={18} /> : <Camera size={18} />}
            </button>
            {chamada.telaDisponivel && (
              <button type="button" title={chamada.compartilhandoTela ? "Parar de mostrar tela" : "Mostrar tela"} aria-label={chamada.compartilhandoTela ? "Parar de mostrar tela" : "Mostrar tela"} className={BOTAO_ICONE} onClick={() => void chamada.alternarTela()}>
                <MonitorUp size={18} />
              </button>
            )}
            <button type="button" title={chamada.mudo ? "Reativar microfone" : "Desligar microfone"} aria-label={chamada.mudo ? "Reativar microfone" : "Desligar microfone"} className={BOTAO_ICONE} onClick={chamada.alternarMudo}>
              {chamada.mudo ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
            <button type="button" title="Reativar áudio" aria-label="Reativar áudio" className={BOTAO_ICONE} onClick={() => void chamada.reativarAudio()}>
              <Volume2 size={18} />
            </button>
            <button
              type="button"
              title="Desligar chamada"
              aria-label="Desligar chamada"
              className={`${BOTAO_ICONE} text-critico`}
              onClick={() => {
                chamada.desligar();
                setSala(null);
              }}
            >
              <PhoneOff size={18} />
            </button>
          </div>

        </>
      )}

      {erro && (
        <div className="mt-3 border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui">
          {erro}
        </div>
      )}

      <p className="mt-[14px] mb-0 pt-[10px] border-t border-borda font-normal text-[11px] leading-[1.5] font-ui text-tinta-3">
        A conversa é transcrita. O roteiro de acolhimento promete sigilo, mas não menciona
        gravação — avise o cliente antes de começar.
      </p>
    </aside>
  );
}
