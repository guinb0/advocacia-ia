"use client";

import { useCallback, useEffect, useState } from "react";

import { consultarGravacao, encerrarGravacao, urlDoAudio } from "@/lib/transcricao";
import type { Gravacao } from "@/lib/transcricao";

/* O áudio da entrevista, para ouvir na hora ou baixar em .mp4.
 *
 * Aparece em dois lugares e é o mesmo componente nos dois: no fim do roteiro,
 * quando a escuta é encerrada, e na tela da triagem, para quem já concluiu a
 * entrevista e continua com o caso. É por isso que ele não recebe a gravação
 * pronta por propriedade — ele pergunta ao servidor. A tela da triagem não
 * esteve na conversa e não teria como saber.
 *
 * Quem grava é o servidor, do mesmo PCM que alimenta o Whisper: o arquivo é
 * exatamente o que foi transcrito. Ver `app/gravacao.py`. */

interface Props {
  /** O id que costura a entrevista inteira num arquivo só. */
  entrevistaId: string;
  /** Título de dentro do painel. */
  titulo?: string;
}

export default function AudioDaEntrevista({
  entrevistaId,
  titulo = "ÁUDIO DA ENTREVISTA",
}: Props) {
  const [gravacao, setGravacao] = useState<Gravacao | null>(null);
  const [preparando, setPreparando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const preparar = useCallback(async () => {
    if (!entrevistaId) return;
    setErro(null);
    setPreparando(true);
    try {
      const atual = await consultarGravacao(entrevistaId);
      // Já convertido: voltar a esta tela não pode reconverter a entrevista
      // inteira só porque alguém clicou de novo.
      setGravacao(atual?.pronto ? atual : await encerrarGravacao(entrevistaId));
    } catch (e) {
      // A entrevista já acabou e o texto está salvo; o que falhou foi a
      // conversão — e o áudio continua no disco. Daí "tentar de novo", em vez
      // de um aviso que só comunica a perda.
      setErro(
        e instanceof Error ? e.message : "Não foi possível preparar o áudio da entrevista.",
      );
    } finally {
      setPreparando(false);
    }
  }, [entrevistaId]);

  useEffect(() => {
    void preparar();
  }, [preparar]);

  // Entrevista sem áudio nenhum — microfone nunca aberto, roteiro preenchido à
  // mão. Um painel vazio dizendo "não há áudio" seria ruído no fim da tela.
  if (!entrevistaId || (!preparando && !erro && !gravacao?.existe)) return null;

  return (
    <section className="mt-6 border-t border-borda pt-[14px]">
      <span className="block text-[10px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
        {titulo}
      </span>

      {preparando && (
        <p className="mt-[10px] mb-0 italic font-normal text-[13px] leading-[1.5] font-titulo text-tinta-3" aria-live="polite">
          Preparando o arquivo — leva alguns segundos por hora de conversa.
        </p>
      )}

      {erro && (
        <p className="mt-[10px] mb-0 font-normal text-[12px] leading-[1.5] font-ui text-critico">
          {erro}{" "}
          <button
            type="button"
            className="border-none bg-transparent p-0 text-inherit [font:inherit] underline underline-offset-[3px] cursor-pointer"
            onClick={preparar}
          >
            tentar de novo
          </button>
        </p>
      )}

      {gravacao?.pronto && (
        <>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption -- a legenda
              deste áudio é a transcrição, que está na tela ao lado. */}
          <audio
            className="block w-full max-w-[460px] mt-3"
            controls
            preload="metadata"
            src={urlDoAudio(entrevistaId)}
          />

          <div className="flex items-center gap-[14px] flex-wrap mt-3">
            <a
              className="inline-block no-underline border-[1.5px] border-tinta bg-transparent text-tinta font-semibold text-[11px] leading-none font-ui tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer hover:bg-tinta hover:text-papel"
              href={urlDoAudio(entrevistaId)}
              download={gravacao.nome}
            >
              Baixar o áudio (.mp4)
            </a>
            <span className="font-normal text-[12px] leading-[1.4] font-codigo text-tinta-3">
              {formatarDuracao(gravacao.duracao_s)} de fala · {formatarBytes(gravacao.bytes)}
            </span>
          </div>

          {/* O arquivo é mais curto que a entrevista, e quem for ouvi-lo depois
            * precisa saber por quê antes de concluir que falta trecho. */}
          <p className="mt-[10px] mb-0 font-normal text-[12px] leading-[1.55] font-ui text-tinta-3 max-w-[68ch]">
            Entra no arquivo só o que foi transcrito: o que for dito durante uma pausa,
            ou fora da escuta, não é gravado.
          </p>
        </>
      )}
    </section>
  );
}

/** "12 min 30 s" — o minuto some quando ainda não há minuto nenhum. */
function formatarDuracao(segundos: number): string {
  const minutos = Math.floor(segundos / 60);
  const resto = Math.round(segundos % 60);
  return minutos ? `${minutos} min ${resto} s` : `${resto} s`;
}

function formatarBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
