"use client";

/* O que uma resposta do agente tem em comum, esteja ela onde estiver.
 *
 * Existem duas telas que conversam com o agente: o painel ao lado do caso
 * (`AjudanteDoCaso`) e o chat geral (`AgenteGeral`). O que elas mostram do agente é a
 * mesma coisa — o lastro da resposta e a proposta de alteração —, e é por isso que mora
 * aqui e não em cada uma.
 *
 * A razão não é economia de linhas. Se as duas telas divergirem sobre como um fato
 * ALEGADO aparece, o guardrail do backend deixa de valer numa delas: o advogado passa a
 * ler relato e prova com o mesmo peso, justamente na tela em que a cópia ficou para trás.
 * Um mapa só, num arquivo só, é o que impede isso. */

import { Aviso, Selo } from "@/components/ui/Basicos";
import estilos from "@/components/RespostaDoAgente.module.css";
import type { AfirmacaoDoAgente, NaturezaDaAfirmacao, PropostaDoAgente } from "@/lib/agente";

/** Como cada natureza aparece. Símbolo + palavra + cor, nunca só cor (`docs/GUIA-VISUAL.md`).
 *
 * A distinção entre provado e alegado é a que decide a leitura do advogado: fato de
 * entrevista nasce alegado, e o backend recusa a resposta que troca um pelo outro.
 * Achatar os dois aqui anularia esse guardrail. */
export const NATUREZA: Record<
  NaturezaDaAfirmacao,
  { tom: "ok" | "atencao" | "info" | "neutro"; simbolo: string; palavra: string }
> = {
  PROVEN_FACT: { tom: "ok", simbolo: "✓", palavra: "Provado" },
  ALLEGED_FACT: { tom: "atencao", simbolo: "!", palavra: "Alegado" },
  HYPOTHESIS: { tom: "neutro", simbolo: "?", palavra: "Hipótese" },
  INFERENCE: { tom: "neutro", simbolo: "→", palavra: "Inferência" },
  RECOMMENDATION: { tom: "info", simbolo: "→", palavra: "Recomendação" },
  STATISTICAL_PATTERN: { tom: "neutro", simbolo: "%", palavra: "Padrão histórico" },
  PRECEDENT: { tom: "info", simbolo: "§", palavra: "Precedente" },
};

interface PropsDoLastro {
  afirmacoes: AfirmacaoDoAgente[];
  pendencias: string[];
  /** Leva a citação ao item correspondente. Sem isto o lastro vira decoração:
   *  identificadores que o advogado não tem como seguir. */
  aoAbrirReferencia?: (referencia: string) => void;
  /** O texto do botão de referência muda com o destino: ao lado do dossiê ele rola até o
   *  cartão ("ver no dossiê"); no chat geral ele troca de tela ("abrir no dossiê"), e
   *  prometer "ver" ali seria prometer menos do que acontece. */
  rotuloDaReferencia?: string;
  /** Quais referências levam a algum lugar.
   *
   * O analista cita coisas que não são caso — `panorama`, `jurimetria`, um verbete do
   * glossário. Elas sustentam a afirmação e não abrem tela nenhuma: desenhar um botão
   * para elas seria prometer um caminho que não existe, e o clique morre em silêncio. */
  referenciaNavegavel?: (referencia: string) => boolean;
}

/** O rodapé de toda resposta do agente: em que ela se apoia, e o que faltou para apoiar. */
export function LastroDaResposta({
  afirmacoes,
  pendencias,
  aoAbrirReferencia,
  rotuloDaReferencia = "ver no dossiê",
  referenciaNavegavel = () => true,
}: PropsDoLastro) {
  if (afirmacoes.length === 0 && pendencias.length === 0) return null;

  return (
    <>
      {afirmacoes.length > 0 && (
        <div className={estilos.lastro}>
          <span className={estilos.rotuloDoLastro}>Em que a resposta se apoia</span>
          {afirmacoes.map((afirmacao, indice) => (
            <Afirmacao
              key={`${afirmacao.statement}-${indice}`}
              afirmacao={afirmacao}
              aoAbrirReferencia={aoAbrirReferencia}
              rotuloDaReferencia={rotuloDaReferencia}
              referenciaNavegavel={referenciaNavegavel}
            />
          ))}
        </div>
      )}

      {pendencias.length > 0 && (
        <Aviso tom="atencao" titulo="O que falta para responder melhor">
          <ul className={estilos.itens}>
            {pendencias.map((pendencia) => (
              <li key={pendencia}>{pendencia}</li>
            ))}
          </ul>
        </Aviso>
      )}
    </>
  );
}

function Afirmacao({
  afirmacao,
  aoAbrirReferencia,
  rotuloDaReferencia,
  referenciaNavegavel,
}: {
  afirmacao: AfirmacaoDoAgente;
  aoAbrirReferencia?: (referencia: string) => void;
  rotuloDaReferencia: string;
  referenciaNavegavel: (referencia: string) => boolean;
}) {
  const natureza = NATUREZA[afirmacao.nature] ?? NATUREZA.INFERENCE;
  const navegaveis = afirmacao.refs.filter(referenciaNavegavel);

  return (
    <div className={estilos.afirmacao}>
      <Selo tom={natureza.tom} simbolo={natureza.simbolo}>
        {natureza.palavra}
      </Selo>
      <div className={estilos.textoDaAfirmacao}>
        {afirmacao.statement}
        {navegaveis.length > 0 && aoAbrirReferencia && (
          <div className={estilos.referencias}>
            {navegaveis.map((referencia) => (
              <button
                key={referencia}
                type="button"
                className={estilos.referencia}
                onClick={() => aoAbrirReferencia(referencia)}
              >
                {rotuloDaReferencia}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** A alteração que o agente propôs — com o antes e o depois, e sem nada aplicado ainda.
 *
 * O backend recusa qualquer outro caminho (`AGENTS.md §2.4`), e a tela não pode sugerir
 * que algo já foi feito. */
export function CartaoDeProposta({
  proposta,
  aoAplicar,
}: {
  proposta: PropostaDoAgente;
  aoAplicar: () => void;
}) {
  return (
    <div className={estilos.proposta}>
      <div className={estilos.tituloDaProposta}>
        <Selo tom="info">Proposta — ainda não aplicada</Selo>
      </div>
      <div className={estilos.corpoDaProposta}>
        <p className={estilos.textoDaAfirmacao}>{proposta.intencao}</p>

        {(proposta.antes || proposta.depois) && (
          <>
            <span className={estilos.rotuloDoLastro}>Hoje</span>
            <div className={estilos.antes}>{proposta.antes || "(seção vazia)"}</div>
            <span className={estilos.rotuloDoLastro}>Passaria a ser</span>
            <div className={estilos.depois}>{proposta.depois}</div>
          </>
        )}

        {proposta.impacto.length > 0 && (
          <ul className={estilos.itens}>
            {proposta.impacto.map((linha) => (
              <li key={linha}>{linha}</li>
            ))}
          </ul>
        )}

        <div className={estilos.acoesDaProposta}>
          <button type="button" className="botao botao--primario" onClick={aoAplicar}>
            Aplicar alteração
          </button>
        </div>
      </div>
    </div>
  );
}
