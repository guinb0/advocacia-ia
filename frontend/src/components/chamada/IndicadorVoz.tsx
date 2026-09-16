"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";

import { LIMIAR_VOZ, medirNivel } from "@/lib/medidorNivel";

/* A barra que diz se está entrando voz — a pergunta que a chamada não sabia responder.
 *
 * "Áudio conectado" e "✓ microfone ligado" respondiam outra coisa: que uma faixa
 * chegou e que a permissão foi dada. As duas ficam verdes com o cliente mudo.
 * Aqui o que acende é som de verdade, medido na própria faixa.
 *
 * O SILÊNCIO É O ESTADO QUE PRECISA GRITAR
 *
 * Numa entrevista com idoso, quem percebe que o áudio morreu é sempre o lado
 * errado — o cliente acha que está sendo ouvido e segue falando. Por isso o
 * componente não se limita a desenhar a barra: passados alguns segundos sem
 * nenhuma voz, ele diz o que fazer, e `acaoSilencio` põe o botão de conserto
 * ali mesmo, sem obrigar ninguém a procurar controle em outro canto da tela.
 *
 * Mudo por escolha não é silêncio defeituoso: com `mudo`, o aviso não aparece —
 * seria acusar defeito de quem pediu para não ser ouvido. */

/** Quanto tempo sem voz antes de avisar. Generoso de propósito: numa entrevista
 *  há pausas longas legítimas — o entrevistado pensa, procura um documento. */
const ESPERA_SILENCIO_MS = 12_000;

export default function IndicadorVoz({
  trilha,
  titulo,
  mudo = false,
  acaoSilencio,
}: {
  /** A faixa a medir. `null` enquanto não há áudio — a barra some. */
  trilha: MediaStreamTrack | null;
  /** "Sua voz" no lado do cliente, "Voz do cliente" no do escritório. */
  titulo: string;
  /** Mudo por escolha: desenha a barra apagada e cala o aviso de silêncio. */
  mudo?: boolean;
  /** Botão de conserto, mostrado junto do aviso de silêncio. */
  acaoSilencio?: React.ReactNode;
}) {
  const [nivel, setNivel] = useState(0);
  const [emSilencio, setEmSilencio] = useState(false);
  // A hora da última voz vive num ref, e não no estado: ela muda dez vezes por
  // segundo e redesenhar a árvore a cada leitura não traz nada à tela.
  const ultimaVoz = useRef(Date.now());

  useEffect(() => {
    if (!trilha) {
      setNivel(0);
      setEmSilencio(false);
      return;
    }
    ultimaVoz.current = Date.now();
    setEmSilencio(false);

    const medidor = medirNivel(trilha, (valor) => {
      setNivel(valor);
      if (valor >= LIMIAR_VOZ) ultimaVoz.current = Date.now();
    });

    const vigia = window.setInterval(() => {
      setEmSilencio(Date.now() - ultimaVoz.current > ESPERA_SILENCIO_MS);
    }, 1_000);

    return () => {
      medidor.parar();
      window.clearInterval(vigia);
    };
  }, [trilha]);

  if (!trilha) return null;

  const temVoz = !mudo && nivel >= LIMIAR_VOZ;
  const alertar = emSilencio && !mudo;
  // A barra cheia com pouca voz engana; `nivel` cru mal sai do canto. A raiz
  // abre a faixa baixa, que é onde a fala normal de uma pessoa cai.
  const largura = mudo ? 0 : Math.round(Math.sqrt(nivel) * 100);

  return (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        {mudo ? (
          <MicOff size={15} className="flex-none text-tinta-3" aria-hidden />
        ) : (
          <Mic size={15} className={`flex-none ${temVoz ? "text-ok" : "text-tinta-3"}`} aria-hidden />
        )}
        <span className="flex-none text-[11.5px] font-semibold font-ui text-tinta-3">{titulo}</span>

        <div
          className="flex-1 min-w-[60px] h-[9px] rounded-pill bg-papel-3 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={largura}
          aria-label={`Volume de ${titulo}`}
        >
          <i
            className="block h-full rounded-pill transition-[width] duration-100 ease-out"
            style={{
              width: `${largura}%`,
              background: alertar ? "var(--atencao-marca)" : temVoz ? "var(--ok)" : "var(--borda-campo)",
            }}
          />
        </div>

        {/* A cor sozinha não conta a história: a palavra é o que sobra para quem
            não distingue verde de âmbar, e para quem está de relance na tela. */}
        <span
          className={`flex-none text-[11px] font-ui tabular-nums ${
            mudo ? "text-tinta-3" : alertar ? "text-atencao font-semibold" : temVoz ? "text-ok font-semibold" : "text-tinta-3"
          }`}
          aria-live="polite"
        >
          {mudo ? "desligado" : alertar ? "sem som" : temVoz ? "ouvindo" : "silêncio"}
        </span>
      </div>

      {alertar && (
        <div className="mt-2 rounded-campo border border-atencao-borda bg-atencao-claro px-3 py-[10px] text-[12.5px] leading-[1.5] text-tinta-2" role="alert">
          <strong className="block text-tinta">Não está entrando som há alguns segundos</strong>
          Fale “alô” e veja se a barra se mexe. Se não mexer, o microfone pode ter sido
          tomado por outro aplicativo ou o fone pode ter desconectado.
          {acaoSilencio && <div className="mt-[10px]">{acaoSilencio}</div>}
        </div>
      )}
    </div>
  );
}
