"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
import Retratos from "@/components/ui/Retratos";

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
          {modo === "documentos" ? "CHAMADA E GRAVAÇÃO" : "CHAMADA"}
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
              ? "Crie a chamada no Meet e mande o link ao cliente. Você continua na aba de documentos, e a conversa entra na mesma gravação do atendimento."
              : "Abra a chamada e mande o link ao entrevistado. A voz dele chega separada da sua — é ela, e só ela, que vira texto no roteiro."}
          </p>
          <button
            type="button"
            className="w-full border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui tracking-[0.1em] uppercase px-[14px] py-3 cursor-pointer disabled:opacity-40 disabled:cursor-default enabled:hover:bg-tinta enabled:hover:text-papel"
            onClick={abrir}
            disabled={abrindo}
          >
            {abrindo ? "Abrindo…" : modo === "documentos" ? "Criar chamada no Meet" : "Abrir chamada"}
          </button>
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

          {chamada.estado === "aguardando" && (
            <p className="m-0 font-normal text-[12px] leading-[1.55] font-ui text-atencao">
              Mande o link e deixe esta tela aberta. Quando ele entrar, o áudio conecta
              sozinho e o gravador de cada pergunta passa a ouvir a voz dele.
            </p>
          )}

          {chamada.estado === "falando" && (
            <p className="m-0 font-normal text-[12px] leading-[1.55] font-ui text-ok">
              {modo === "documentos"
                ? "A voz do cliente está chegando e sendo acrescentada à gravação do atendimento. Continue conferindo os documentos abaixo."
                : "A voz do entrevistado está chegando. Use “Gravar resposta” em cada pergunta do roteiro — o que for transcrito é a fala dele, não a sua."}
            </p>
          )}

          <Retratos participantes={chamada.participantes} tamanho="coluna" />

          <div className="flex gap-2 flex-wrap mt-[10px]">
            <button type="button" className={BOTAO_SECUNDARIO} onClick={() => void chamada.alternarCamera()}>
              {chamada.temCamera ? "Desligar câmera" : "Ligar câmera"}
            </button>
            {chamada.telaDisponivel && (
              <button type="button" className={BOTAO_SECUNDARIO} onClick={() => void chamada.alternarTela()}>
                {chamada.compartilhandoTela ? "Parar de mostrar a tela" : "Mostrar minha tela"}
              </button>
            )}
            <button type="button" className={BOTAO_SECUNDARIO} onClick={chamada.alternarMudo}>
              {chamada.mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </button>
            <button
              type="button"
              className={BOTAO_SECUNDARIO}
              onClick={() => {
                chamada.desligar();
                setSala(null);
              }}
            >
              Desligar
            </button>
          </div>

          <p className="mt-3 mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-ok">
            A chamada continua ao sair desta tela — segue num painel no canto até você
            desligar, para acompanhar o cliente no envio dos documentos.
          </p>
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
