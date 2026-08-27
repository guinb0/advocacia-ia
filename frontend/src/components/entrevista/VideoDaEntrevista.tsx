"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { GravacaoVideo, podeGravarTela, podeGravarVideo } from "@/lib/gravacaoVideo";
import type { EstadoVideo, FonteVideo, VideoGravado } from "@/lib/gravacaoVideo";

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
  automatico?: boolean;
}

const BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[13px] py-[9px] cursor-pointer inline-block no-underline hover:bg-tinta hover:text-papel";
/* Gravando: vermelho, como o gravador de áudio. É estado que precisa saltar aos
 * olhos de quem está conversando e não olhando a tela. */
const BOTAO_GRAVANDO =
  "border-[1.5px] border-critico bg-transparent text-critico text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[13px] py-[9px] cursor-pointer inline-block no-underline hover:bg-critico hover:text-papel";
/* O que ainda não foi baixado é o que se perde: enquanto for o caso, o botão de
 * baixar é o único elemento cheio da tela. */
const BOTAO_DESTAQUE =
  "border-[1.5px] border-critico bg-critico text-papel text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[13px] py-[9px] cursor-pointer inline-block no-underline hover:bg-tinta hover:border-tinta";

export default function VideoDaEntrevista({ onPendente, automatico = false }: Props) {
  const [estado, setEstado] = useState<EstadoVideo>("parado");
  const [video, setVideo] = useState<VideoGravado | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [decorrido, setDecorrido] = useState(0);
  const [baixado, setBaixado] = useState(false);
  /* Só depois de montado. `MediaRecorder` não existe no servidor, e decidir
   * isto durante a renderização faria o HTML do servidor (sem o painel) brigar
   * com o do navegador (com ele) na hidratação. */
  const [podeGravar, setPodeGravar] = useState(false);
  const tentouAutomatico = useRef(false);

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
  /* Capacidade separada da de gravar: o Safari do iPhone grava pela câmera e
   * NÃO implementa `getDisplayMedia`. Medido no cliente, nunca no servidor —
   * o mesmo build serve computador e celular. */
  const [temTela, setTemTela] = useState(false);
  useEffect(() => setTemTela(podeGravarTela()), []);

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
      } else if (/InvalidStateError/i.test(m)) {
        setErro("O navegador exige um clique para compartilhar a tela. Use o botão de autorização acima.");
      } else if (!/abort|cancel/i.test(m)) {
        setErro(m);
      }
    }
  }, []);

  useEffect(() => {
    if (!automatico || !podeGravar || tentouAutomatico.current) return;
    tentouAutomatico.current = true;
    // Sem captura de tela, o automático grava pela câmera. Insistir na tela
    // aqui produzia o erro cru assim que a entrevista abria no celular.
    void iniciar(temTela ? "tela" : "camera");
  }, [automatico, podeGravar, temTela, iniciar]);

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
    <section className="border-t border-borda pt-3 pb-[14px] mb-4">
      <div className="flex items-center gap-[10px] flex-wrap">
        <span className="text-[10px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          GRAVAÇÃO VISUAL
        </span>

        {!gravando ? (
          automatico ? (
            <button
              type="button"
              className={BOTAO}
              onClick={() => void iniciar(temTela ? "tela" : "camera")}
            >
              {temTela ? "Autorizar gravação da tela" : "Autorizar gravação pela câmera"}
            </button>
          ) : <>
            <button type="button" className={BOTAO} onClick={() => void iniciar("camera")}>
              Gravar pela câmera
            </button>
            {/* "do sistema", e não "da chamada": a captura é presa nesta aba
                (ver `ESTA_ABA` em `lib/gravacaoVideo.ts`). O rótulo antigo
                prometia escolher uma janela, e escolher era justamente o que
                fazia a entrevista ser gravada como outra aba qualquer.

                Some no iPhone e no iPad: o Safari de lá não implementa
                `getDisplayMedia`, e o botão só existia para estourar ao ser
                clicado. A gravação pela câmera continua oferecida. */}
            {temTela && (
              <button
                type="button"
                className={BOTAO}
                onClick={() => void iniciar("tela")}
                title="Grava esta aba — roteiro e rosto do cliente — com a voz dos dois lados"
              >
                Gravar a tela do sistema
              </button>
            )}
          </>
        ) : (
          <>
            <span className="inline-flex items-center gap-[7px] text-[12px] font-medium leading-none font-codigo text-critico">
              <i className="w-2 h-2 bg-critico rounded-full animate-[pulsarForte_1.6s_ease-in-out_infinite] motion-reduce:animate-none" />
              TELA E VÍDEO GRAVANDO · {formatarRelogio(decorrido)}
            </span>
            <button type="button" className={BOTAO_GRAVANDO} onClick={() => gravacao.current?.parar()}>
              Parar
            </button>
          </>
        )}
      </div>

      <p className="mt-[10px] mb-0 font-normal text-[12px] leading-[1.55] font-ui text-tinta-3 max-w-[72ch]">
        A gravação visual registra esta aba e precisa ser baixada antes de fechar. O áudio continua guardado pelo sistema.
      </p>

      {erro && (
        <p className="mt-[10px] mb-0 font-normal text-[12px] leading-[1.5] font-ui text-critico">{erro}</p>
      )}

      {video && (
        <div className="mt-[14px] border-l-[3px] border-tinta pt-[10px] pr-0 pb-[2px] pl-[14px]">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption -- gravação de
              atendimento, sem legenda a acrescentar. */}
          <video className="block w-full max-w-[420px] mb-3 bg-tinta" controls preload="metadata" src={video.url} />

          <div className="flex items-center gap-[10px] flex-wrap">
            <a
              className={baixado ? BOTAO : BOTAO_DESTAQUE}
              href={video.url}
              download={video.nome}
              onClick={baixar}
            >
              Baixar o vídeo (.{video.nome.split(".").pop()})
            </a>
            <button
              type="button"
              className="border-none bg-transparent p-0 text-tinta-3 font-normal text-[11.5px] leading-none font-ui underline underline-offset-[3px] cursor-pointer hover:text-tinta"
              onClick={descartar}
            >
              descartar
            </button>
            <span className="font-normal text-[12px] leading-[1.4] font-codigo text-tinta-3">
              {formatarRelogio(video.duracaoS)} · {(video.bytes / 1024 / 1024).toFixed(1)} MB
            </span>
          </div>

          <p
            className={
              baixado
                ? "mt-[10px] mb-0 font-normal text-[12px] leading-[1.5] font-ui text-tinta-3"
                : "mt-[10px] mb-0 font-semibold text-[12px] leading-[1.5] font-ui text-critico"
            }
          >
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
