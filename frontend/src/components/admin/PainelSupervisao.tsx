"use client";

/* O topo da supervisão: o que o escritório deve, e quem deve o quê.
 *
 * O QUE ISTO SUBSTITUIU
 *
 * Uma linha de texto — "27 entrevista(s) · 5 pessoa(s)" — e uma lista de nomes.
 * Os dois números diziam o tamanho do acervo, que é justamente o que o secretário
 * já sabe; nenhum deles respondia a pergunta com que ele abre a tela, que é O QUE
 * COBRAR HOJE, DE QUEM.
 *
 * DUAS DECISÕES QUE PARECEM DETALHE E NÃO SÃO
 *
 * 1. Os indicadores contam PENDÊNCIA, não acerto. "21 com avaliação" obriga a
 *    subtrair de cabeça para chegar em "6 faltando", que é o número que ele veio
 *    buscar. Quando não há pendência nenhuma o cartão fica verde e diz isso — um
 *    zero grande em vermelho seria lido como problema.
 *
 * 2. A tabela ordena por quem tem MAIS pendência, não por quem fez mais. Ordenar
 *    por volume é um ranking de produtividade, e esta tela não mede produtividade
 *    — mede o que ficou por fazer. Ver o cabeçalho de `app/auditoria.py`: aqui não
 *    se dá nota e não se compara pessoa.
 */

import type { PendenciasSupervisao, PessoaSupervisao } from "@/lib/api";

/** Barra de proporção com a leitura em palavra ao lado — cor nunca vai sozinha. */
function Proporcao({ feitos, total }: { feitos: number; total: number }) {
  const pct = total ? Math.round((feitos * 100) / total) : 0;
  const completo = feitos === total;
  return (
    <span className="inline-flex items-center gap-2 min-w-[104px]">
      <span className="h-[6px] w-12 shrink-0 rounded-pill bg-papel-3 overflow-hidden">
        <i
          className={`block h-full rounded-pill ${completo ? "bg-ok" : "bg-atencao-marca"}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`text-xs tabular-nums ${completo ? "text-ok" : "text-atencao"}`}>
        {feitos}/{total}
      </span>
    </span>
  );
}

function Indicador({
  numero,
  rotulo,
  ajuda,
  tom,
}: {
  numero: number;
  rotulo: string;
  ajuda: string;
  tom: "critico" | "atencao" | "neutro";
}) {
  // Zero pendência é notícia boa e tem de parecer notícia boa. Um "0" grande em
  // vermelho, ao lado de outros vermelhos, lê-se como mais um problema.
  const zerado = numero === 0;
  const cor = zerado
    ? "text-ok"
    : tom === "critico"
      ? "text-critico"
      : tom === "atencao"
        ? "text-atencao"
        : "text-tinta";
  const borda = zerado
    ? "border-ok-borda bg-ok-claro"
    : tom === "critico"
      ? "border-critico-borda bg-critico-claro"
      : tom === "atencao"
        ? "border-atencao-borda bg-atencao-claro"
        : "border-borda bg-papel-2";

  return (
    <div className={`px-[14px] py-3 border rounded-campo ${borda}`} title={ajuda}>
      <div className={`font-titulo text-xl font-semibold tabular-nums leading-none ${cor}`}>
        {numero}
      </div>
      <div className="mt-[6px] text-tinta text-xs font-semibold">{rotulo}</div>
      <div className="mt-[2px] text-tinta-3 text-xs leading-[1.45]">{ajuda}</div>
    </div>
  );
}

interface Props {
  pessoas: PessoaSupervisao[];
  pendencias: PendenciasSupervisao;
  total: number;
  /** Quem está aberto na lista abaixo — a linha da tabela acende junto. */
  pessoaAberta: string | null;
  onEscolherPessoa: (entrevistador: string) => void;
}

const TH = "px-3 py-2 text-left text-tinta-3 text-xs font-semibold uppercase tracking-[0.04em]";
const TD = "px-3 py-[10px] border-t border-borda align-middle";

export default function PainelSupervisao({
  pessoas,
  pendencias,
  total,
  pessoaAberta,
  onEscolherPessoa,
}: Props) {
  /* Quem deve mais primeiro. `pendentes` soma as duas dívidas conferíveis sem ir
   * ao modelo; empate desempata por volume, para a lista não dançar a cada
   * carregamento. "não identificado" cai para o fim: é buraco de dado antigo, não
   * trabalho mal feito de ninguém. */
  const ordenadas = [...pessoas].sort((a, b) => {
    const semNome = (p: PessoaSupervisao) => (p.entrevistador === "não identificado" ? 1 : 0);
    if (semNome(a) !== semNome(b)) return semNome(a) - semNome(b);
    const devendo = (p: PessoaSupervisao) =>
      p.quantidade - p.com_avaliacao + (p.quantidade - p.com_dossie);
    return devendo(b) - devendo(a) || b.quantidade - a.quantidade;
  });

  return (
    <div className="grid gap-5">
      {/* ------------------------------------------------------- indicadores */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
        <Indicador
          numero={pendencias.sem_avaliacao}
          rotulo="Sem avaliação no Google"
          ajuda="A etapa do roteiro que não tem segunda chance depois que o cliente desliga."
          tom="critico"
        />
        <Indicador
          numero={pendencias.sem_dossie}
          rotulo="Sem dossiê"
          ajuda="A conversa não foi lida pelo agente: os fatos dela não estão no caso."
          tom="atencao"
        />
        <Indicador
          numero={pendencias.sem_quem_conduziu}
          rotulo="Sem quem conduziu"
          ajuda="Gravadas antes de o sistema atribuir a entrevista. Ausência de dado, não de trabalho."
          tom="neutro"
        />
        <div className="px-[14px] py-3 border border-borda rounded-campo bg-papel-2">
          <div className="font-titulo text-xl font-semibold tabular-nums leading-none text-tinta">
            {total}
          </div>
          <div className="mt-[6px] text-tinta text-xs font-semibold">Entrevistas no acervo</div>
          <div className="mt-[2px] text-tinta-3 text-xs leading-[1.45]">
            {pendencias.ao_vivo} conduzida(s) pelo roteiro · {pendencias.anexadas} anexada(s)
          </div>
        </div>
      </div>

      {/* ---------------------------------------------------- por funcionário */}
      <div className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
        <div className="px-4 py-3 border-b border-borda bg-papel-2">
          <h2 className="m-0 text-tinta font-titulo text-md font-semibold">Por funcionário</h2>
          <p className="mt-1 mb-0 text-tinta-3 text-xs leading-[1.5]">
            Quem tem mais pendência aparece primeiro. Isto não mede produtividade — mede o
            que ficou por fazer. Clique para ver as entrevistas da pessoa.
          </p>
        </div>

        {/* A tabela rola sozinha em vez de espremer as colunas: num celular,
          * quatro colunas em 360px viram quatro tiras ilegíveis. */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse min-w-[560px]">
            <thead>
              <tr className="bg-papel-2">
                <th className={TH}>Quem conduziu</th>
                <th className={TH}>Entrevistas</th>
                <th className={TH}>Avaliação Google</th>
                <th className={TH}>Dossiê</th>
                <th className={TH}>Última</th>
              </tr>
            </thead>
            <tbody>
              {ordenadas.map((p) => {
                const aberta = pessoaAberta === p.entrevistador;
                return (
                  <tr
                    key={p.entrevistador}
                    className={`cursor-pointer ${aberta ? "bg-acao-clara" : "hover:bg-papel-3"}`}
                    onClick={() => onEscolherPessoa(p.entrevistador)}
                  >
                    <td className={`${TD} text-tinta text-sm font-semibold`}>
                      {p.entrevistador}
                    </td>
                    <td className={`${TD} text-tinta-2 text-sm tabular-nums`}>{p.quantidade}</td>
                    <td className={TD}>
                      <Proporcao feitos={p.com_avaliacao} total={p.quantidade} />
                    </td>
                    <td className={TD}>
                      <Proporcao feitos={p.com_dossie} total={p.quantidade} />
                    </td>
                    <td className={`${TD} text-tinta-3 text-xs tabular-nums whitespace-nowrap`}>
                      {p.ultima_em || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
