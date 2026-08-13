"use client";

import { useEffect, useRef } from "react";

import type { Participante } from "@/lib/chamadaJitsi";
import estilos from "./Retratos.module.css";

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
      className={estilos.video}
      playsInline
      autoPlay
      // O próprio vídeo entra mudo e espelhado: ouvir a si mesmo é microfonia,
      // e a imagem não espelhada confunde quem se vê.
      muted={espelhar}
      style={espelhar ? { transform: "scaleX(-1)" } : undefined}
    />
  );
}

function Miolo({ participante }: { participante: Participante }) {
  if (participante.video) {
    return <Video trilha={participante.video} espelhar={participante.souEu} />;
  }
  return (
    <span
      className={estilos.inicial}
      style={{ background: corDoNome(participante.nome) }}
      aria-hidden
    >
      {inicial(participante.nome)}
    </span>
  );
}

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

  return (
    <div className={`${estilos.area} ${tamanho === "coluna" ? estilos.coluna : ""}`}>
      <figure className={estilos.palco}>
        <Miolo participante={noPalco} />
        <figcaption className={estilos.nome}>
          {noPalco.nome}
          {noPalco.souEu && <span className={estilos.voce}> (você)</span>}
        </figcaption>

        {mostrarCanto && eu && (
          <figure className={estilos.canto}>
            <Miolo participante={eu} />
          </figure>
        )}
      </figure>

      {/* Terceira pessoa em diante: fileira pequena embaixo. Não é o caso hoje,
          mas a sala do Jitsi aceita mais gente e a tela não pode sumir com ela. */}
      {outros.length > 1 && (
        <div className={estilos.fileira}>
          {outros.slice(1).map((p) => (
            <figure key={p.id} className={estilos.miniatura}>
              <Miolo participante={p} />
              <figcaption className={estilos.nome}>{p.nome}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
