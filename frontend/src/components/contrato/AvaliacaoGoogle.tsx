"use client";

import { useState } from "react";

import { Selo } from "@/components/ui/Basicos";
import { enviarAvaliacaoGoogle } from "@/lib/api";

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

const PRIMARIO =
  "border border-tinta px-3 py-[9px] bg-tinta text-papel text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.06em] uppercase no-underline cursor-pointer max-[640px]:text-center";
const SECUNDARIO =
  "border border-tinta px-3 py-[9px] bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.06em] uppercase no-underline cursor-pointer max-[640px]:text-center";
const DISCRETO =
  "border border-transparent px-3 py-[9px] bg-transparent text-tinta-3 text-[10px] font-semibold leading-none " +
  "font-ui tracking-[0.06em] uppercase underline underline-offset-[3px] cursor-pointer max-[640px]:text-center";

interface Props {
  /** A etapa está cumprida. Mora no atendimento, não aqui: voltar ao roteiro
   *  desmonta esta caixa, e uma marcação que se perdesse nisso não é registro. */
  concluida: boolean;
  onConcluir: (concluida: boolean) => void;
  telefone: string;
}

export default function AvaliacaoGoogle({ concluida, onConcluir, telefone }: Props) {
  const [copiado, setCopiado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [retorno, setRetorno] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);

  async function copiar() {
    await navigator.clipboard.writeText(`${MENSAGEM}${LINK_AVALIACAO}`);
    setCopiado(true);
    window.setTimeout(() => setCopiado(false), 2500);
  }

  async function enviar() {
    setEnviando(true);
    setRetorno(null);
    try {
      await enviarAvaliacaoGoogle(telefone);
      setRetorno({ tom: "ok", texto: "Link enviado para o WhatsApp do cliente." });
    } catch (e) {
      setRetorno({ tom: "erro", texto: e instanceof Error ? e.message : "Não foi possível enviar o link." });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="mt-6 border-t border-borda pt-[14px]" aria-labelledby="titulo-avaliacao-google">
      <div className="flex items-center flex-wrap gap-[10px] mb-2 text-[10px] font-semibold leading-[1.4] font-ui tracking-[0.12em] text-tinta-3">
        GOOGLE MEU NEGÓCIO
        <Selo tom={concluida ? "ok" : "atencao"} simbolo={concluida ? "✓" : "!"}>
          {concluida ? "concluída" : "pendente"}
        </Selo>
      </div>

      <div>
        <h3 id="titulo-avaliacao-google" className="mb-[6px] mt-0 font-medium text-[18px] leading-[1.25] font-titulo">
          Peça a avaliação com o cliente ainda na chamada
        </h3>
        <p className="m-0 max-w-[65ch] font-normal text-[12px] leading-[1.6] font-ui text-tinta-3">
          Envie o link do Google e <strong>permaneça na videoconferência</strong> enquanto
          ele avalia, como diz o roteiro — para confirmar que deu certo e ajudar se
          houver dificuldade. Só o link vai para o cliente; nada mais é enviado.
        </p>

        <div className="flex items-center flex-wrap gap-[9px] mt-[13px] max-[640px]:items-stretch max-[640px]:flex-col">
          <button type="button" className={PRIMARIO} disabled={enviando || !telefone.trim()} onClick={() => void enviar()}>
            {enviando ? "Enviando…" : "Enviar pelo WhatsApp"}
          </button>
          <button type="button" className={SECUNDARIO} onClick={() => void copiar()}>
            {copiado ? "Convite copiado ✓" : "Copiar convite"}
          </button>
          <a className={DISCRETO} href={LINK_AVALIACAO} target="_blank" rel="noopener noreferrer">
            Abrir página de avaliação
          </a>
        </div>
        {!telefone.trim() && <p className="mt-2 text-xs text-atencao">Informe o telefone do cliente antes de enviar.</p>}
        {retorno && <p className={`mt-2 text-xs ${retorno.tom === "ok" ? "text-ok" : "text-critico"}`}>{retorno.texto}</p>}

        {/* A marcação do atendente.
          *
          * Fica embaixo dos botões de propósito: é o último passo, e marcá-la
          * antes de o cliente avaliar seria registrar o que não aconteceu. O
          * texto diz o que se está afirmando — "enviei" não vale, "avaliou"
          * vale — porque um checkbox rotulado só "concluído" cada atendente
          * interpreta de um jeito. */}
        <label className="flex items-start gap-[9px] mt-[14px] border border-borda-forte px-[13px] py-[11px] font-normal text-[12.5px] leading-[1.5] font-ui cursor-pointer hover:bg-papel-2">
          <input
            type="checkbox"
            className="flex-none w-[17px] h-[17px] mt-[1px] cursor-pointer"
            checked={concluida}
            onChange={(e) => onConcluir(e.target.checked)}
          />
          <span>
            <strong>O cliente concluiu a avaliação</strong> e eu confirmei com ele na
            chamada.
          </span>
        </label>

        {!concluida && (
          <p className="mt-[6px] italic font-normal text-[11.5px] leading-[1.5] font-titulo text-tinta-3">
            Enquanto não estiver marcada, esta etapa fica em aberto no atendimento.
          </p>
        )}
      </div>
    </section>
  );
}
