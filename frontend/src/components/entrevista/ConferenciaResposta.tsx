"use client";

import type { AnaliseResposta } from "@/lib/types";

/* O que a resposta recém-dada ainda não trouxe.
 *
 * Aparece embaixo da própria pergunta, enquanto o cliente ainda está na frente —
 * que é a única hora em que serve para alguma coisa. Descoberto depois, "faltou
 * perguntar se houve CAT" vira ligação de volta, e o cliente que já contou a
 * história uma vez não a conta igual na segunda.
 *
 * O painel é pequeno de propósito. Três lacunas e três perguntas: mais que isso
 * ninguém lê no meio de uma entrevista, e o que não é lido não é conferido. */

interface Props {
  analise: AnaliseResposta | null;
  carregando: boolean;
  erro: string | null;
  /** Refazer a conferência depois de completar a resposta. */
  onRefazer?: () => void;
}

const ROTULO =
  "text-[9.5px] font-semibold leading-[1.4] font-ui tracking-[0.13em] uppercase text-tinta-3";
const BLOCO = "mt-[10px] px-[11px] py-[9px] border-l-2 border-borda-forte bg-papel-2";

export default function ConferenciaResposta({ analise, carregando, erro, onRefazer }: Props) {
  if (carregando) {
    return (
      <div className={BLOCO} aria-live="polite">
        <span className={ROTULO}>conferindo a resposta…</span>
      </div>
    );
  }

  /* Erro aqui não é erro de entrevista. O modelo pode estar fora do ar e a
   * entrevista continua — por isso discreto, e nunca em vermelho de alarme. */
  if (erro) {
    return (
      <div className={BLOCO} aria-live="polite">
        <span className="font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">{erro}</span>
      </div>
    );
  }

  if (!analise) return null;

  if (analise.suficiente) {
    return (
      <div className={BLOCO} aria-live="polite">
        <span className="font-normal text-[12px] leading-[1.5] font-ui text-ok">
          ✓ Nada a acrescentar neste ponto.
        </span>
        {!analise.com_precedentes && <SemPrecedentes />}
      </div>
    );
  }

  return (
    <div className={BLOCO} aria-live="polite">
      <div className="flex items-baseline gap-2 flex-wrap mb-[6px]">
        <span className={ROTULO}>o que falta neste ponto</span>
        {!analise.com_precedentes && <SemPrecedentes />}
      </div>

      {analise.faltam.length > 0 && (
        <ul className="m-0 pl-4 font-normal text-[12px] leading-[1.6] font-ui">
          {analise.faltam.map((f) => (
            <li key={f.item} className="mb-[2px]">
              {f.item}
              {f.precedentes.map((p) => (
                <ReferenciaPrecedente key={p} indice={p} analise={analise} />
              ))}
            </li>
          ))}
        </ul>
      )}

      {/* Prontas para ler em voz alta: é o formato que economiza o tempo do
        * entrevistador, que senão precisa traduzir "verificar se houve CAT"
        * numa pergunta enquanto o cliente espera. */}
      {analise.perguntar.length > 0 && (
        <>
          <span className="block mt-[9px] mb-1 text-[9.5px] font-semibold leading-[1.4] font-ui tracking-[0.13em] uppercase text-tinta-3">
            pergunte ao cliente
          </span>
          <ul className="m-0 pl-4 font-normal text-[13px] leading-[1.55] font-titulo">
            {analise.perguntar.map((p) => (
              <li key={p} className="mb-[3px]">
                {p}
              </li>
            ))}
          </ul>
        </>
      )}

      {analise.observacao && (
        <p className="mt-2 mb-0 italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
          {analise.observacao}
        </p>
      )}

      {onRefazer && (
        <button
          type="button"
          className="mt-2 border-none bg-transparent p-0 text-tinta-3 font-normal text-[11px] leading-[1.4] font-ui underline underline-offset-[3px] cursor-pointer hover:text-tinta"
          onClick={onRefazer}
        >
          Conferir de novo
        </button>
      )}
    </div>
  );
}

const PRECEDENTE =
  "inline-block ml-[5px] px-1 py-[1px] border border-borda-forte text-[9.5px] font-normal leading-[1.4] font-codigo text-tinta-3 no-underline align-[1px]";

/** O processo que sustenta a lacuna. Vira link quando há URL pública. */
function ReferenciaPrecedente({
  indice,
  analise,
}: {
  indice: string;
  analise: AnaliseResposta;
}) {
  const p = analise.precedentes.find((x) => x.indice === indice);
  if (!p) return null;

  const titulo = [p.processo, p.resultado, p.vara].filter(Boolean).join(" · ");

  return p.url ? (
    <a
      className={`${PRECEDENTE} hover:text-tinta hover:border-tinta`}
      href={p.url}
      target="_blank"
      rel="noreferrer"
      title={titulo}
    >
      {indice}
    </a>
  ) : (
    <span className={PRECEDENTE} title={titulo}>
      {indice}
    </span>
  );
}

/* O banco de precedentes é remoto e já ficou fora do ar. Quando ele não
 * responde a conferência ainda sai, mas deixa de ser "o que os processos
 * semelhantes mostram" e passa a ser a leitura do modelo sobre o texto. As duas
 * não podem parecer a mesma coisa na tela. */
function SemPrecedentes() {
  return (
    <span
      className="px-[5px] py-[1px] border border-atencao text-atencao text-[9px] font-semibold leading-[1.5] font-ui tracking-[0.1em] uppercase cursor-help"
      title="O banco de processos não respondeu. A conferência saiu apenas da leitura do texto."
    >
      sem precedentes
    </span>
  );
}
