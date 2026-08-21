"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { GravacaoVideo, podeGravarVideo } from "@/lib/gravacaoVideo";
import type { EstadoVideo, FonteVideo, VideoGravado } from "@/lib/gravacaoVideo";
import estilos from "./VideoDaEntrevista.module.css";

/* Gravar a entrevista em vídeo — e baixar, porque ela não fica guardada.
 *
 * O áudio o servidor guarda; o vídeo não sai desta aba. Isso muda o que a tela
 * precisa fazer: não basta oferecer o download, ela tem que impedir que alguém
 * saia sem ele. Daí o aviso em vermelho, o `beforeunload` e o `onPendente`, que
 * deixa o roteiro perguntar antes de concluir a entrevista.
 *
 * O botão fica em cima, junto do "começar", e não no rodapé: vídeo se decide no
 * início da conversa. No fim, só sobra o arrependimento. */

interface Props {
  /** Avisa que há vídeo gravado e ainda não baixado — o que se perde ao sair. */
  onPendente?: (pendente: boolean) => void;
  /** Só a preparação pode abrir uma gravação nova. */
  permitirInicio?: boolean;
  /** Para uma gravação em curso quando a entrevista é finalizada. */
  finalizar?: boolean;
}

export default function VideoDaEntrevista({
  onPendente,
  permitirInicio = true,
  finalizar = false,
}: Props) {
  const [estado, setEstado] = useState<EstadoVideo>("parado");
  const [video, setVideo] = useState<VideoGravado | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [decorrido, setDecorrido] = useState(0);
  const [baixado, setBaixado] = useState(false);
  /* Só depois de montado. `MediaRecorder` não existe no servidor, e decidir
   * isto durante a renderização faria o HTML do servidor (sem o painel) brigar
   * com o do navegador (com ele) na hidratação. */
  const [podeGravar, setPodeGravar] = useState(false);

  const gravacao = useRef<GravacaoVideo | null>(null);
  const onPendenteRef = useRef(onPendente);
  onPendenteRef.current = onPendente;

  if (gravacao.current === null && typeof window !== "undefined") {
    gravacao.current = new GravacaoVideo({
      onEstado: setEstado,
      onPronto: (pronto) => {
        setVideo(pronto);
        setBaixado(false);
        onPendenteRef.current?.(true);
      },
      onErro: setErro,
    });
  }

  // O cronômetro. Um segundo de resolução basta e não repinta a tela à toa
  // durante uma conversa de quarenta minutos.
  useEffect(() => {
    if (estado !== "gravando") return;
    const id = setInterval(() => setDecorrido(gravacao.current?.decorridoS ?? 0), 1000);
    return () => clearInterval(id);
  }, [estado]);

  /* A última barreira antes de a gravação virar nada.
   *
   * Fechar a aba destrói o blob — não há como recuperá-lo depois, nem no
   * servidor, que nunca o recebeu. O navegador mostra o seu próprio texto aqui;
   * o que se pode fazer é ligar o aviso. */
  useEffect(() => {
    if (!video || baixado) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [video, baixado]);

  useEffect(() => setPodeGravar(podeGravarVideo()), []);

  useEffect(() => {
    if (finalizar && estado === "gravando") gravacao.current?.parar();
  }, [estado, finalizar]);

  // Sair da tela solta câmera e microfone. Sem isto a luz da câmera fica acesa
  // depois da entrevista fechada.
  useEffect(() => () => gravacao.current?.encerrar(), []);

  const iniciar = useCallback(async (fonte: FonteVideo) => {
    setErro(null);
    setDecorrido(0);
    setVideo(null);
    onPendenteRef.current?.(false);
    try {
      await gravacao.current?.iniciar(fonte);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível gravar o vídeo.";
      // Cancelar a escolha da janela é um NotAllowedError igual ao da permissão
      // negada, e um erro vermelho para quem só desistiu seria ruído.
      if (/Permission denied|NotAllowedError/i.test(m)) {
        setErro("Permissão de câmera ou de tela negada.");
      } else if (!/abort|cancel/i.test(m)) {
        setErro(m);
      }
    }
  }, []);

  const baixar = useCallback(() => {
    gravacao.current?.marcarBaixado();
    setBaixado(true);
    onPendenteRef.current?.(false);
  }, []);

  const descartar = useCallback(() => {
    gravacao.current?.descartar();
    setVideo(null);
    setBaixado(false);
    onPendenteRef.current?.(false);
  }, []);

  if (!podeGravar) return null;

  const gravando = estado === "gravando";

  return (
    <section className={estilos.bloco}>
      <div className={estilos.linha}>
        <span className={estilos.rotulo}>VÍDEO</span>

        {!gravando && permitirInicio ? (
          <>
            <button
              type="button"
              className={estilos.botao}
              onClick={() => void iniciar("camera")}
            >
              Gravar pela câmera
            </button>
            {/* "do sistema", e não "da chamada": a captura é presa nesta aba
                (ver `ESTA_ABA` em `lib/gravacaoVideo.ts`). O rótulo antigo
                prometia escolher uma janela, e escolher era justamente o que
                fazia a entrevista ser gravada como outra aba qualquer. */}
            <button
              type="button"
              className={estilos.botao}
              onClick={() => void iniciar("tela")}
              title="Grava esta aba — roteiro e rosto do cliente — com a voz dos dois lados"
            >
              Gravar a tela do sistema
            </button>
          </>
        ) : gravando ? (
          <>
            <button
              type="button"
              className={`${estilos.botao} ${estilos.gravando}`}
              onClick={() => gravacao.current?.parar()}
            >
              Parar o vídeo
            </button>
            <span className={estilos.tempo}>
              <i className={estilos.ponto} />
              {formatarRelogio(decorrido)}
            </span>
          </>
        ) : null}
      </div>

      <p className={estilos.nota}>
        O vídeo <strong>não fica guardado</strong> no sistema: ele existe só nesta
        aba, e precisa ser baixado antes de fechar a entrevista. Quem grava e guarda
        é o áudio.
      </p>

      {erro && <p className={estilos.erro}>{erro}</p>}

      {video && (
        <div className={estilos.pronto}>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption -- gravação de
              atendimento, sem legenda a acrescentar. */}
          <video className={estilos.player} controls preload="metadata" src={video.url} />

          <div className={estilos.linha}>
            <a
              className={`${estilos.botao} ${baixado ? "" : estilos.destaque}`}
              href={video.url}
              download={video.nome}
              onClick={baixar}
            >
              Baixar o vídeo (.{video.nome.split(".").pop()})
            </a>
            <button type="button" className={estilos.descartar} onClick={descartar}>
              descartar
            </button>
            <span className={estilos.meta}>
              {formatarRelogio(video.duracaoS)} · {(video.bytes / 1024 / 1024).toFixed(1)} MB
            </span>
          </div>

          <p className={baixado ? estilos.salvo : estilos.perigo}>
            {baixado
              ? "Baixado. O arquivo está na pasta de downloads deste computador."
              : "Ainda não baixado — sair desta tela agora perde a gravação."}
          </p>
        </div>
      )}
    </section>
  );
}

/** "12:07" — relógio, que é como se lê duração de gravação. */
function formatarRelogio(segundos: number): string {
  const total = Math.round(segundos);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
