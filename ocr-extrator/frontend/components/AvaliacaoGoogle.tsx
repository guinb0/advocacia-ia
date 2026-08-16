"use client";

import { useState } from "react";

import { Selo } from "./Basicos";
import estilos from "./AvaliacaoGoogle.module.css";

/* Google Meu Negócio — a etapa que acontece COM O CLIENTE AINDA NA CHAMADA.
 *
 * O roteiro do escritório não manda avaliar depois; manda avaliar agora, com o
 * atendente esperando do outro lado. As palavras são dele, no `FECHAMENTO`:
 *
 *   "peço apenas que realize a avaliação agora. Eu permanecerei na
 *    videoconferência aguardando para confirmar que deu tudo certo e, caso
 *    tenha qualquer dificuldade durante o preenchimento, terei o maior prazer
 *    em ajudá-lo(a)."
 *
 * Daí as duas coisas que esta tela faz e a versão anterior não fazia:
 *
 *   1. lembra, em destaque, que a chamada NÃO se encerra aqui — desligar antes
 *      é perder a avaliação, e não há segunda chance depois que o cliente sai;
 *   2. pede a marcação do atendente. A etapa só está cumprida quando ele
 *      confirmou, olhando o cliente, que a avaliação foi publicada. "Mandei o
 *      link" não é avaliação feita, e era isso que ficava sem registro. */

/** Perfil do escritório no Google Meu Negócio. */
const LINK_AVALIACAO = "https://share.google/jejesXtEzd87GKxbU";
const MENSAGEM =
  "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: ";

interface Props {
  /** A etapa está cumprida. Mora no atendimento, não aqui: voltar ao roteiro
   *  desmonta esta caixa, e uma marcação que se perdesse nisso não é registro. */
  concluida: boolean;
  onConcluir: (concluida: boolean) => void;
}

export default function AvaliacaoGoogle({ concluida, onConcluir }: Props) {
  const [copiado, setCopiado] = useState(false);

  async function copiar() {
    await navigator.clipboard.writeText(`${MENSAGEM}${LINK_AVALIACAO}`);
    setCopiado(true);
    window.setTimeout(() => setCopiado(false), 2500);
  }

  const whatsapp = `https://wa.me/?text=${encodeURIComponent(`${MENSAGEM}${LINK_AVALIACAO}`)}`;

  return (
    <section className={estilos.bloco} aria-labelledby="titulo-avaliacao-google">
      <div className={estilos.numero}>
        GOOGLE MEU NEGÓCIO
        <Selo tom={concluida ? "ok" : "atencao"} simbolo={concluida ? "✓" : "!"}>
          {concluida ? "concluída" : "pendente"}
        </Selo>
      </div>

      <div className={estilos.conteudo}>
        <h3 id="titulo-avaliacao-google">Peça a avaliação com o cliente ainda na chamada</h3>
        <p>
          Envie o link do Google e <strong>permaneça na videoconferência</strong> enquanto
          ele avalia, como diz o roteiro — para confirmar que deu certo e ajudar se
          houver dificuldade. Só o link vai para o cliente; nada mais é enviado.
        </p>

        <div className={estilos.acoes}>
          <a
            className={estilos.primario}
            href={whatsapp}
            target="_blank"
            rel="noopener noreferrer"
          >
            Enviar pelo WhatsApp
          </a>
          <button type="button" className={estilos.secundario} onClick={() => void copiar()}>
            {copiado ? "Convite copiado ✓" : "Copiar convite"}
          </button>
          <a
            className={estilos.discreto}
            href={LINK_AVALIACAO}
            target="_blank"
            rel="noopener noreferrer"
          >
            Abrir página de avaliação
          </a>
        </div>

        {/* A marcação do atendente.
          *
          * Fica embaixo dos botões de propósito: é o último passo, e marcá-la
          * antes de o cliente avaliar seria registrar o que não aconteceu. O
          * texto diz o que se está afirmando — "enviei" não vale, "avaliou"
          * vale — porque um checkbox rotulado só "concluído" cada atendente
          * interpreta de um jeito. */}
        <label className={estilos.marcacao}>
          <input
            type="checkbox"
            checked={concluida}
            onChange={(e) => onConcluir(e.target.checked)}
          />
          <span>
            <strong>O cliente concluiu a avaliação</strong> e eu confirmei com ele na
            chamada.
          </span>
        </label>

        {!concluida && (
          <p className={estilos.pendente}>
            Enquanto não estiver marcada, esta etapa fica em aberto no atendimento.
          </p>
        )}
      </div>
    </section>
  );
}
