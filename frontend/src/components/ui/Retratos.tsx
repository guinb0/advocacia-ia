"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Participante } from "@/lib/chamadaJitsi";

/* Quem está na chamada.
 *
 * O arranjo é o de qualquer chamada de duas pessoas: o OUTRO ocupa o palco e
 * você fica pequeno num canto. Numa entrevista isso não é estética — quem
 * conduz precisa ler o rosto de quem responde, e quem responde precisa ver a
 * pessoa que está perguntando, não a si mesmo.
 *
 * Sem câmera, o palco vira um círculo com a inicial do nome. Numa chamada só de
 * voz, uma tela sem nenhuma marca da pessoa faz o entrevistador perder a
 * referência de com quem fala, e o cliente ficar sem saber se ainda há alguém
 * do outro lado.
 *
 * Dois tamanhos: `grande` para a tela do entrevistado, onde a chamada é a única
 * coisa; `coluna` para o lado do advogado, que divide a tela com o roteiro. */

const CORES = [
  "#7c3aed", "#0891b2", "#c2410c", "#4d7c0f", "#be123c", "#4338ca", "#a16207",
];

function corDoNome(nome: string): string {
  let soma = 0;
  for (const c of nome) soma = (soma + c.charCodeAt(0)) % 997;
  return CORES[soma % CORES.length];
}

function inicial(nome: string): string {
  const limpo = nome.trim();
  return limpo ? limpo[0].toUpperCase() : "?";
}

/* Cores de vídeo/retrato são chrome de chamada — sempre escuras com texto
 * branco, independente do tema claro do resto do app — por isso não vêm de
 * `globals.css`. */
const TAMANHO_INICIAL = {
  "palco-grande": "w-[clamp(72px,22%,128px)] text-[clamp(1.75rem,7vw,3rem)]",
  "palco-coluna": "w-[84px] text-[2rem]",
  canto: "w-10 text-[1.125rem]",
  miniatura: "w-9 text-[1rem]",
} as const;

function Video({
  trilha,
  espelhar,
  tela,
  cheia,
}: {
  trilha: MediaStreamTrack;
  espelhar: boolean;
  /** Tela compartilhada: cabe inteira, sem recorte e sem espelho. */
  tela: boolean;
  /** O palco ocupa o monitor inteiro. */
  cheia: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const elemento = video.current;
    if (!elemento) return;
    elemento.srcObject = new MediaStream([trilha]);
    // `play()` pode ser recusado antes de a aba receber um gesto; o vídeo
    // aparece assim que o usuário interagir, e não vale um erro na tela.
    void elemento.play().catch(() => {});
    return () => {
      elemento.srcObject = null;
    };
  }, [trilha]);

  /* `contain` na tela, `cover` no rosto. Recortar um rosto para preencher o
   * quadro é o normal de qualquer chamada; recortar uma tela corta a margem do
   * documento que a pessoa quis mostrar — e é sempre na margem que está o
   * número, a data ou o botão que ela está apontando. Espelhar, então, deixa o
   * texto de trás para frente. */
  const espelhado = espelhar && !tela;

  /* Em tela cheia, `contain` tambem para rosto: a proporcao do monitor raramente
   * bate com a da camera, e `cover` cortaria metade da pessoa para preencher. */
  const inteiro = tela || cheia;

  return (
    <video
      ref={video}
      className={`w-full h-full ${inteiro ? "object-contain" : "object-cover"}`}
      style={{ background: "#1c1917", ...(espelhado ? { transform: "scaleX(-1)" } : {}) }}
      playsInline
      autoPlay
      // O próprio vídeo entra mudo e espelhado: ouvir a si mesmo é microfonia,
      // e a imagem não espelhada confunde quem se vê.
      muted={espelhar}
      aria-label={tela ? "Tela compartilhada" : undefined}
    />
  );
}

function Miolo({
  participante,
  variante,
  cheia = false,
}: {
  participante: Participante;
  variante: keyof typeof TAMANHO_INICIAL;
  cheia?: boolean;
}) {
  if (participante.video) {
    return (
      <Video
        trilha={participante.video}
        espelhar={participante.souEu}
        tela={participante.tela}
        cheia={cheia}
      />
    );
  }
  return (
    <span
      className={`grid place-items-center aspect-square rounded-full text-white font-titulo font-semibold leading-none ${TAMANHO_INICIAL[variante]}`}
      style={{ background: corDoNome(participante.nome) }}
      aria-hidden
    >
      {inicial(participante.nome)}
    </span>
  );
}

const NOME_BASE =
  "absolute inset-x-0 bottom-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.66),transparent)] " +
  "text-white font-medium leading-[1.2] whitespace-nowrap overflow-hidden text-ellipsis";

/* Botao de tela cheia sobre o palco.
 *
 * Nasceu junto do compartilhamento de tela: um documento mostrado pelo cliente
 * dentro de um quadro de 4/3 na coluna do advogado e ilegivel — o texto que ele
 * quer apontar tem 6 pixels de altura. Vale para camera tambem, na hora de ler
 * a expressao de quem responde.
 *
 * `requestFullscreen` no <figure>, e nao um "modo expandido" com CSS: em tela
 * cheia de verdade o navegador tira barra de endereco, abas e barra de tarefas,
 * que e justamente o espaco que faltava. O Esc devolve, sem precisar de codigo.
 *
 * O estado NAO e o do nosso clique: e o `fullscreenchange` do documento. Quem
 * sai pelo Esc ou pelo botao do proprio navegador nao passa pelo nosso handler,
 * e o rotulo ficaria dizendo "Sair da tela cheia" com a tela ja normal. */
const BOTAO_PALCO =
  "absolute right-2 top-2 z-10 border border-[rgba(255,255,255,0.45)] bg-[rgba(0,0,0,0.45)] " +
  "text-white text-[10px] font-semibold leading-none font-ui tracking-[0.06em] uppercase " +
  "px-[9px] py-[7px] cursor-pointer hover:bg-[rgba(0,0,0,0.7)]";

export default function Retratos({
  participantes,
  tamanho = "grande",
}: {
  participantes: Participante[];
  tamanho?: "grande" | "coluna";
}) {
  const palco = useRef<HTMLElement | null>(null);
  const [cheia, setCheia] = useState(false);
  /* Falso no servidor e na primeira renderizacao do cliente — `document` nao
   * existe no primeiro — e falso tambem no Safari do iPhone, que nao faz tela
   * cheia de elemento. Sem isto o botao apareceria e nao faria nada. */
  const [podeExpandir, setPodeExpandir] = useState(false);

  useEffect(() => {
    /* Os dois: ja apareceu botao em navegador de celular que anuncia
     * `fullscreenEnabled` e nao implementa o metodo no elemento. */
    setPodeExpandir(
      document.fullscreenEnabled === true &&
        typeof document.documentElement.requestFullscreen === "function",
    );
    const aoTrocar = () => setCheia(document.fullscreenElement === palco.current);
    document.addEventListener("fullscreenchange", aoTrocar);
    return () => document.removeEventListener("fullscreenchange", aoTrocar);
  }, []);

  const alternarTelaCheia = useCallback(async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await palco.current?.requestFullscreen();
    } catch {
      /* O navegador pode recusar (sem gesto do usuario, ou politica de
       * permissao num iframe). Nao ha o que consertar aqui, e um alerta no meio
       * da entrevista atrapalha mais que a tela pequena. */
    }
  }, []);

  if (participantes.length === 0) return null;

  const eu = participantes.find((p) => p.souEu) ?? null;
  const outros = participantes.filter((p) => !p.souEu);
  // Sozinho na sala, quem aparece no palco é você — como em qualquer chamada
  // enquanto o outro não chega.
  const noPalco = outros[0] ?? eu;
  if (!noPalco) return null;

  const mostrarCanto = outros.length > 0 && eu !== null;
  const coluna = tamanho === "coluna";

  return (
    <div className="mt-[14px]">
      <figure
        ref={palco}
        className={`relative m-0 w-full border border-borda-forte bg-papel-3 overflow-hidden grid place-items-center ${
          cheia
            ? "h-screen w-screen max-h-none rounded-none border-0"
            : coluna
              ? "aspect-[4/3] max-h-[360px] rounded-campo"
              /* No celular em pe, 16/9 desperdica a tela: a largura toda vira
               * uma faixa de ~190px de altura e o rosto fica do tamanho de uma
               * unha. Retrato 3/4 usa a mesma largura e mais que dobra a altura.
               * De `sm` para cima volta a 16/9, que e a proporcao do monitor. */
              : "aspect-[3/4] max-h-[62vh] sm:aspect-video sm:max-h-[58vh] rounded-campo"
        }`}
      >
        {podeExpandir && (
          <button
            type="button"
            className={BOTAO_PALCO}
            onClick={() => void alternarTelaCheia()}
            aria-pressed={cheia}
          >
            {cheia ? "Sair da tela cheia" : "Tela cheia"}
          </button>
        )}
        <Miolo
          participante={noPalco}
          variante={coluna && !cheia ? "palco-coluna" : "palco-grande"}
          cheia={cheia}
        />
        <figcaption className={`${NOME_BASE} px-[10px] py-2 text-[0.8125rem]`}>
          {noPalco.nome}
          {noPalco.souEu && <span className="opacity-75 font-normal"> (você)</span>}
          {/* Sem isto, uma tela quase toda branca no palco se parece com câmera
              travada — e o advogado fica esperando a imagem "voltar". */}
          {noPalco.tela && <span className="opacity-75 font-normal"> · mostrando a tela</span>}
        </figcaption>

        {mostrarCanto && eu && (
          <figure
            className={`absolute m-0 border border-[rgba(255,255,255,0.5)] rounded-campo bg-papel-3 shadow-[0_2px_8px_rgba(0,0,0,0.28)] overflow-hidden grid place-items-center [aspect-ratio:4/3] ${
              coluna && !cheia
                ? "right-2 bottom-2 w-[84px]"
                : "right-[10px] bottom-[10px] w-[clamp(84px,26%,168px)]"
            }`}
          >
            {/* Em tela cheia o canto acompanha o palco: um retrato de 84px num
                monitor de 27 polegadas nao mostra rosto nenhum. */}
            <Miolo participante={eu} variante={cheia ? "palco-coluna" : "canto"} cheia={cheia} />
          </figure>
        )}
      </figure>

      {/* Terceira pessoa em diante: fileira pequena embaixo. Não é o caso hoje,
          mas a sala do Jitsi aceita mais gente e a tela não pode sumir com ela. */}
      {outros.length > 1 && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(96px,1fr))] gap-2 mt-2">
          {outros.slice(1).map((p) => (
            <figure
              key={p.id}
              className="relative m-0 aspect-[4/3] border border-borda-forte rounded-campo bg-papel-3 overflow-hidden grid place-items-center"
            >
              <Miolo participante={p} variante="miniatura" />
              <figcaption className={`${NOME_BASE} px-[6px] py-1 text-[0.6875rem]`}>{p.nome}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
