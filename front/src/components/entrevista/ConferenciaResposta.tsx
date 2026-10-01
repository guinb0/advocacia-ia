"use client";

import type { AnaliseResposta } from "@/lib/types";

/* O que a resposta recém-dada ainda não trouxe.
 *
 * Aparece embaixo da própria pergunta, enquanto o cliente ainda está na frente —
 * que é a única hora em que serve para alguma coisa. Descoberto depois, "faltou
 * perguntar quando saiu da empresa" vira ligação de volta.
 *
 * Quem conduz pode não ser advogado, e está com o cliente esperando: o painel
 * mostra só o que dá para LER EM VOZ ALTA, no máximo duas perguntas. A lista de
 * lacunas (`faltam`) é o mesmo conteúdo em outra forma, e só aparece quando o
 * modelo não trouxe pergunta pronta. */

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

  const perguntas = analise.perguntar;
  const lacunas = perguntas.length > 0 ? [] : analise.faltam.map((f) => f.item);

  if (perguntas.length === 0 && lacunas.length === 0 && !analise.observacao) {
    return (
      <div className={BLOCO} aria-live="polite">
        <span className="font-normal text-[12px] leading-[1.5] font-ui text-ok">
          ✓ Resposta completa. Pode seguir.
        </span>
      </div>
    );
  }

  return (
    <div className={BLOCO} aria-live="polite">
      {(perguntas.length > 0 || lacunas.length > 0) && (
        <div className="flex items-baseline gap-2 flex-wrap mb-[6px]">
          <span className={ROTULO}>{perguntas.length > 0 ? "pergunte ao cliente" : "falta neste ponto"}</span>
          {!analise.com_precedentes && <SemPrecedentes />}
        </div>
      )}

      {perguntas.length > 0 && (
        <ul className="m-0 pl-4 font-normal text-[13px] leading-[1.55] font-titulo">
          {perguntas.map((p) => (
            <li key={p} className="mb-[3px]">
              {p}
            </li>
          ))}
        </ul>
      )}

      {lacunas.length > 0 && (
        <ul className="m-0 pl-4 font-normal text-[12px] leading-[1.6] font-ui">
          {lacunas.map((item) => (
            <li key={item} className="mb-[2px]">
              {item}
            </li>
          ))}
        </ul>
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
