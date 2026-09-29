"use client";

import { useState } from "react";

import { Botao, LinkBotao, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
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
const LINK_AVALIACAO = "https://share.google/BrQVYGnjqdSz3pEw7";
const MENSAGEM =
  "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: ";

const FALA_ANTES_DO_LINK = [
  "Sr.(a) [Nome], concluímos a nossa entrevista.Primeiramente gostaria de agradecer, em nome do Dr. Gustavo Lara e de toda a equipe da Lara & Melo Advogados Associados, pela confiança em compartilhar conosco a sua história.",
  "Pode ter certeza de que todas as informações prestadas hoje serão analisadas com muita atenção.",
  "Antes de encerrarmos, posso lhe fazer apenas uma última pergunta?",
  "Como foi a sua experiência durante este atendimento? O(a) senhor(a) gostou da forma como foi atendido(a)? Existe alguma sugestão ou algo que poderíamos melhorar?",
  "(Aguardar a resposta do cliente.)",
  "Fico muito feliz em ouvir isso. Trabalhamos diariamente para oferecer um atendimento de excelência para todos os trabalhadores que confiam no nosso escritório.",
  "Se o(a) senhor(a) permitir, gostaria de lhe encaminhar um link de avaliação. A sua opinião é extremamente importante para nós, pois nos ajuda a aperfeiçoar continuamente nossos atendimentos e também auxilia outras pessoas a conhecerem o trabalho desenvolvido pela nossa equipe.",
];

interface Props {
  cliente?: string;
  /** A etapa está cumprida. Mora no atendimento, não aqui: voltar ao roteiro
   *  desmonta esta caixa, e uma marcação que se perdesse nisso não é registro. */
  concluida: boolean;
  onConcluir: (concluida: boolean) => void;
  telefone: string;
}

export default function AvaliacaoGoogle({ cliente = "", concluida, onConcluir, telefone }: Props) {
  const [copiado, setCopiado] = useState(false);
  /** Qual envio está em curso — o primeiro ou o reenvio pedido pelo atendente —
   *  para só o botão clicado mostrar o andamento. */
  const [enviando, setEnviando] = useState<"envio" | "reenvio" | null>(null);
  const [retorno, setRetorno] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);
  // O link já foi mandado antes: em vez de deixar a mensagem num beco sem saída,
  // abre a opção de reenviar quando o atendente pede, com o cliente na chamada.
  const [jaEnviado, setJaEnviado] = useState(false);

  async function copiar() {
    await navigator.clipboard.writeText(`${MENSAGEM}${LINK_AVALIACAO}`);
    setCopiado(true);
    window.setTimeout(() => setCopiado(false), 2500);
  }

  async function enviar(forcar = false) {
    setEnviando(forcar ? "reenvio" : "envio");
    setRetorno(null);
    try {
      const resultado = await enviarAvaliacaoGoogle(telefone, forcar);
      // `ja_enviado` só volta quando NÃO se forçou: um reenvio deliberado passa
      // pela dedup e cai no ramo "enviado", limpando a oferta de reenvio.
      if (resultado.ja_enviado) {
        setJaEnviado(true);
        setRetorno({ tom: "ok", texto: "O link já tinha sido enviado para este cliente." });
      } else {
        setJaEnviado(false);
        setRetorno({ tom: "ok", texto: "Link enviado para o WhatsApp do cliente." });
      }
    } catch (e) {
      setRetorno({ tom: "erro", texto: e instanceof Error ? e.message : "Não foi possível enviar o link." });
    } finally {
      setEnviando(null);
    }
  }

  const semTelefone = telefone.trim() ? null : "Informe o telefone do cliente antes de enviar.";

  /* QUEM APERTA O BOTÃO É O ADVOGADO, e isto já foi automático uma vez.
   *
   * O envio disparava sozinho ao abrir a etapa. O problema não é técnico — a
   * deduplicação no servidor funciona — é de momento: esta etapa aparece assim
   * que a qualificação fica pronta, e nem sempre é a hora de pedir avaliação. O
   * roteiro pede que o link vá COM O CLIENTE AINDA NA CHAMADA, para o atendente
   * acompanhar; disparado antes disso, o cliente recebe o link no meio do
   * atendimento, sem ninguém ter pedido nada, e a avaliação se perde.
   *
   * Quem sabe se a conversa chegou nesse ponto é quem está conduzindo. */

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

        <div className="mt-[13px] max-w-[74ch] border-l-4 border-acao bg-acao-clara px-4 py-3">
          <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.12em] text-acao">
            Leia para o cliente antes de enviar o link
          </span>
          {FALA_ANTES_DO_LINK.map((paragrafo) => (
            <p
              key={paragrafo}
              className={`mb-2 mt-0 last:mb-0 text-[14px] leading-[1.6] font-titulo ${
                paragrafo.startsWith("(") ? "italic text-tinta-3" : "text-tinta"
              }`}
            >
              {paragrafo.replace("[Nome]", cliente.trim() || "[Nome]")}
            </p>
          ))}
        </div>

        <div className="flex items-start flex-wrap gap-[9px] mt-[13px] max-[640px]:items-stretch max-[640px]:flex-col">
          <BotaoProcesso
            variante="primario"
            onClick={() => enviar()}
            processando={enviando === "envio"}
            textoProcessando="Enviando…"
            pendencia={semTelefone}
            aguardando={enviando === "reenvio"}
            erro={retorno?.tom === "erro" ? retorno.texto : null}
            concluido={retorno?.tom === "ok" ? retorno.texto : null}
          >
            Enviar pelo WhatsApp
          </BotaoProcesso>
          <Botao variante="secundario" onClick={() => void copiar()}>
            {copiado ? "✓ Convite copiado" : "Copiar convite"}
          </Botao>
          <LinkBotao variante="texto" className="h-10" href={LINK_AVALIACAO} target="_blank" rel="noopener noreferrer">
            Abrir página de avaliação
          </LinkBotao>
        </div>
        {jaEnviado && (
          <div className="mt-2">
            <BotaoProcesso
              variante="texto"
              pequeno
              onClick={() => enviar(true)}
              processando={enviando === "reenvio"}
              textoProcessando="Reenviando…"
              pendencia={semTelefone}
              aguardando={enviando === "envio"}
            >
              Enviar novamente
            </BotaoProcesso>
          </div>
        )}

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
