"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { criarSalaChamada } from "@/lib/api";
import { useChamada } from "@/lib/ChamadaContexto";
import type { EstadoChamada } from "@/lib/chamadaJitsi";
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
}

const LEGENDA: Record<EstadoChamada, string> = {
  fora: "chamada desligada",
  aguardando: "esperando o entrevistado",
  conectando: "conectando…",
  falando: "em chamada",
  encerrada: "chamada encerrada",
};

export default function PainelChamada({ onFaixaRemota, onFimDaFaixa }: Props) {
  const chamada = useChamada();
  const [sala, setSala] = useState<{ sala: string; url: string } | null>(null);
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
      await chamada.entrar(nova.sala, "advogado", { nome: "Escritório" });
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
    chamada.estado === "falando"
      ? estilos.pontoAtivo
      : chamada.estado === "aguardando" || chamada.estado === "conectando"
        ? estilos.pontoEsperando
        : estilos.pontoOcioso;

  return (
    <aside className={estilos.painel}>
      <div className={estilos.topo}>
        <span className={estilos.rotulo}>CHAMADA</span>
        <span className={estilos.estado}>
          <i className={`${estilos.ponto} ${ponto}`} />
          {LEGENDA[chamada.estado]}
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

          {chamada.estado === "aguardando" && (
            <p className={estilos.espera}>
              Mande o link e deixe esta tela aberta. Quando ele entrar, o áudio conecta
              sozinho e o gravador de cada pergunta passa a ouvir a voz dele.
            </p>
          )}

          {chamada.estado === "falando" && (
            <p className={estilos.pronto}>
              A voz do entrevistado está chegando. Use “Gravar resposta” em cada pergunta do
              roteiro — o que for transcrito é a fala dele, não a sua.
            </p>
          )}

          <Retratos participantes={chamada.participantes} tamanho="coluna" />

          <div className={estilos.acoes}>
            <button
              type="button"
              className={estilos.secundario}
              onClick={() => void chamada.alternarCamera()}
            >
              {chamada.temCamera ? "Desligar câmera" : "Ligar câmera"}
            </button>
            <button
              type="button"
              className={estilos.secundario}
              onClick={chamada.alternarMudo}
            >
              {chamada.mudo ? "Reativar meu microfone" : "Ficar mudo"}
            </button>
            <button
              type="button"
              className={estilos.secundario}
              onClick={() => {
                chamada.desligar();
                setSala(null);
              }}
            >
              Desligar
            </button>
          </div>

          <p className={estilos.permanece}>
            A chamada continua ao sair desta tela — segue num painel no canto até você
            desligar, para acompanhar o cliente no envio dos documentos.
          </p>
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
