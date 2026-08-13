"use client";

import type { AnaliseResposta } from "@/lib/types";
import estilos from "./ConferenciaResposta.module.css";

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

export default function ConferenciaResposta({ analise, carregando, erro, onRefazer }: Props) {
  if (carregando) {
    return (
      <div className={estilos.bloco} aria-live="polite">
        <span className={estilos.rotulo}>conferindo a resposta…</span>
      </div>
    );
  }

  /* Erro aqui não é erro de entrevista. O modelo pode estar fora do ar e a
   * entrevista continua — por isso discreto, e nunca em vermelho de alarme. */
  if (erro) {
    return (
      <div className={estilos.bloco} aria-live="polite">
        <span className={estilos.falhou}>{erro}</span>
      </div>
    );
  }

  if (!analise) return null;

  if (analise.suficiente) {
    return (
      <div className={estilos.bloco} aria-live="polite">
        <span className={estilos.completo}>✓ Nada a acrescentar neste ponto.</span>
        {!analise.com_precedentes && <SemPrecedentes />}
      </div>
    );
  }

  return (
    <div className={estilos.bloco} aria-live="polite">
      <div className={estilos.cabecalho}>
        <span className={estilos.rotulo}>o que falta neste ponto</span>
        {!analise.com_precedentes && <SemPrecedentes />}
      </div>

      {analise.faltam.length > 0 && (
        <ul className={estilos.lacunas}>
          {analise.faltam.map((f) => (
            <li key={f.item}>
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
          <span className={estilos.rotuloPerguntar}>pergunte ao cliente</span>
          <ul className={estilos.perguntas}>
            {analise.perguntar.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </>
      )}

      {analise.observacao && <p className={estilos.observacao}>{analise.observacao}</p>}

      {onRefazer && (
        <button type="button" className={estilos.refazer} onClick={onRefazer}>
          Conferir de novo
        </button>
      )}
    </div>
  );
}

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
      className={estilos.precedente}
      href={p.url}
      target="_blank"
      rel="noreferrer"
      title={titulo}
    >
      {indice}
    </a>
  ) : (
    <span className={estilos.precedente} title={titulo}>
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
      className={estilos.semPrecedentes}
      title="O banco de processos não respondeu. A conferência saiu apenas da leitura do texto."
    >
      sem precedentes
    </span>
  );
}
