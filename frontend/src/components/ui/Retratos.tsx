"use client";

import { useEffect, useRef } from "react";

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

function Video({ trilha, espelhar }: { trilha: MediaStreamTrack; espelhar: boolean }) {
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

  return (
    <video
      ref={video}
      className="w-full h-full object-cover"
      style={{ background: "#1c1917", ...(espelhar ? { transform: "scaleX(-1)" } : {}) }}
      playsInline
      autoPlay
      // O próprio vídeo entra mudo e espelhado: ouvir a si mesmo é microfonia,
      // e a imagem não espelhada confunde quem se vê.
      muted={espelhar}
    />
  );
}

function Miolo({
  participante,
  variante,
}: {
  participante: Participante;
  variante: keyof typeof TAMANHO_INICIAL;
}) {
  if (participante.video) {
    return <Video trilha={participante.video} espelhar={participante.souEu} />;
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

export default function Retratos({
  participantes,
  tamanho = "grande",
}: {
  participantes: Participante[];
  tamanho?: "grande" | "coluna";
}) {
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
        className={`relative m-0 w-full border border-borda-forte rounded-campo bg-papel-3 overflow-hidden grid place-items-center ${
          coluna ? "aspect-[4/3] max-h-[360px]" : "aspect-video max-h-[58vh]"
        }`}
      >
        <Miolo participante={noPalco} variante={coluna ? "palco-coluna" : "palco-grande"} />
        <figcaption className={`${NOME_BASE} px-[10px] py-2 text-[0.8125rem]`}>
          {noPalco.nome}
          {noPalco.souEu && <span className="opacity-75 font-normal"> (você)</span>}
        </figcaption>

        {mostrarCanto && eu && (
          <figure
            className={`absolute m-0 border border-[rgba(255,255,255,0.5)] rounded-campo bg-papel-3 shadow-[0_2px_8px_rgba(0,0,0,0.28)] overflow-hidden grid place-items-center [aspect-ratio:4/3] ${
              coluna ? "right-2 bottom-2 w-[84px]" : "right-[10px] bottom-[10px] w-[clamp(84px,26%,168px)]"
            }`}
          >
            <Miolo participante={eu} variante="canto" />
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
