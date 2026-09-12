"use client";

import { useEffect, useMemo, useState } from "react";

import { obterEntrega } from "@/lib/api";
import type { Campo, EntregaDetalhe, ItemSituacao } from "@/lib/types";
import { Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";

/** A ficha do cliente em seções, na ordem em que se lê um cadastro. Agrupar é o
 *  que tira o resumo do "muro de campos" e deixa o olho achar o que procura —
 *  identidade num bloco, filiação no outro, documentos e endereço à parte. Uma
 *  seção só aparece se algum de seus campos foi extraído. */
const SECOES_FICHA: { titulo: string; campos: { nome: string; rotulo: string }[] }[] = [
  {
    titulo: "Identificação",
    campos: [
      { nome: "cpf", rotulo: "CPF" },
      { nome: "rg", rotulo: "RG" },
      { nome: "data_nascimento", rotulo: "Nascimento" },
      { nome: "naturalidade", rotulo: "Naturalidade" },
      { nome: "sexo", rotulo: "Sexo" },
    ],
  },
  {
    titulo: "Filiação",
    campos: [
      { nome: "nome_mae", rotulo: "Mãe" },
      { nome: "nome_pai", rotulo: "Pai" },
    ],
  },
  {
    titulo: "Documentos e benefícios",
    campos: [
      { nome: "pis", rotulo: "PIS/PASEP" },
      { nome: "numero_ctps", rotulo: "CTPS" },
      { nome: "titulo_eleitor", rotulo: "Título de eleitor" },
      { nome: "cns", rotulo: "Cartão SUS" },
      { nome: "cnh", rotulo: "CNH" },
    ],
  },
  {
    titulo: "Contato e endereço",
    campos: [
      { nome: "endereco", rotulo: "Endereço" },
      { nome: "cep", rotulo: "CEP" },
    ],
  },
];

type CampoConsolidado = { valor: string; origem: string; duvidoso: boolean };

/** Reúne, de todos os documentos lidos, o melhor valor de cada campo, por nome.
 *
 * "Melhor" = validado na frente do não validado, e maior confiança no desempate.
 * É o que transforma vinte fichas repetidas de RG, CPF e CNH numa só ficha do
 * cliente — a leitura que o advogado queria e que o dump por documento não dava. */
function consolidar(detalhes: EntregaDetalhe[]): Map<string, CampoConsolidado> {
  const melhor = new Map<string, { campo: Campo; origem: string }>();
  for (const entrega of detalhes) {
    for (const campo of entrega.extracao?.campos ?? []) {
      if (!campo.valor?.trim()) continue;
      const atual = melhor.get(campo.nome);
      const ganha =
        !atual ||
        (atual.campo.valido === false && campo.valido !== false) ||
        (atual.campo.valido === campo.valido && campo.confianca > atual.campo.confianca);
      if (ganha) melhor.set(campo.nome, { campo, origem: entrega.arquivo });
    }
  }
  const saida = new Map<string, CampoConsolidado>();
  for (const [nome, { campo, origem }] of melhor) {
    saida.set(nome, { valor: campo.valor, origem, duvidoso: campo.valido === false });
  }
  return saida;
}

/** Um campo da ficha: rótulo pequeno em cima, valor em destaque, fonte discreta. */
function CampoFicha({ rotulo, dado }: { rotulo: string; dado: CampoConsolidado }) {
  return (
    <div className="grid min-w-0 gap-[2px]">
      <span className="text-[11px] font-medium uppercase tracking-wide text-tinta-3">{rotulo}</span>
      <span className="text-sm font-semibold text-tinta [overflow-wrap:anywhere]">
        {dado.valor}
        {dado.duvidoso && (
          <span className="ml-2 align-middle text-[10px] font-normal text-atencao">confira</span>
        )}
      </span>
      <span className="truncate text-[11px] text-tinta-3" title={dado.origem}>
        {dado.origem}
      </span>
    </div>
  );
}

export default function ResumoDocumentos({ itens }: { itens: ItemSituacao[] }) {
  const entregas = useMemo(() => {
    const unicas = new Map<string, { id: string; arquivo: string; status_proc?: string }>();
    for (const item of itens) {
      for (const entrega of item.entregas) unicas.set(entrega.id, entrega);
    }
    return [...unicas.values()];
  }, [itens]);
  const chave = entregas.map((e) => `${e.id}:${e.status_proc}`).join("|");
  const [aberto, setAberto] = useState(false);
  const [detalhes, setDetalhes] = useState<EntregaDetalhe[]>([]);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    if (!aberto) return;
    const prontas = entregas.filter((e) => e.status_proc === "pronto");
    if (!prontas.length) {
      setDetalhes([]);
      setCarregando(false);
      return;
    }
    let cancelado = false;
    setDetalhes([]);
    setCarregando(true);
    void (async () => {
      const carregadas: EntregaDetalhe[] = [];
      // Evita abrir dezenas de consultas pesadas ao mesmo tempo. Quatro mantém a
      // ficha responsiva sem saturar API, banco e enriquecimento do agente.
      for (let inicio = 0; inicio < prontas.length && !cancelado; inicio += 4) {
        const lote = await Promise.allSettled(
          prontas.slice(inicio, inicio + 4).map((e) => obterEntrega(e.id)),
        );
        carregadas.push(...lote.flatMap((r) => (r.status === "fulfilled" ? [r.value] : [])));
      }
      if (!cancelado) {
        setDetalhes(carregadas);
        setCarregando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
    // A chave muda quando o OCR termina ou uma entrega é adicionada/removida.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto, chave]);

  const dados = useMemo(() => consolidar(detalhes), [detalhes]);
  const nome = dados.get("nome");
  // As seções que têm ao menos um campo preenchido — as vazias não entram.
  const secoes = SECOES_FICHA.map((s) => ({
    titulo: s.titulo,
    campos: s.campos.flatMap((c) => {
      const dado = dados.get(c.nome);
      return dado ? [{ rotulo: c.rotulo, dado }] : [];
    }),
  })).filter((s) => s.campos.length > 0);
  const temFicha = Boolean(nome) || secoes.length > 0;

  if (!entregas.length) return null;

  return (
    <Cartao
      titulo="Dados do cliente nos documentos"
      subtitulo="Ficha reunida sob demanda: carregue quando precisar conferir os dados extraídos."
    >
      {!aberto ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="m-0 text-sm leading-[1.55] text-tinta-3">
            {entregas.length} arquivo{entregas.length === 1 ? "" : "s"} no caso. A navegação abre primeiro; os dados extraídos carregam só quando você pedir.
          </p>
          <Botao variante="secundario" pequeno onClick={() => setAberto(true)}>
            Carregar ficha dos documentos
          </Botao>
        </div>
      ) : carregando && detalhes.length === 0 ? (
        <Vazio>Montando a ficha do cliente…</Vazio>
      ) : detalhes.length === 0 ? (
        <Vazio>Os documentos ainda estão sendo interpretados.</Vazio>
      ) : (
        <div className="flex flex-col gap-5">
          {temFicha && (
            <section className="overflow-hidden rounded-campo border border-borda-forte bg-papel">
              {/* Nome como cabeçalho da ficha: é a identidade do caso. */}
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-borda bg-papel-2 px-4 py-3">
                <h3 className="m-0 text-base font-semibold text-tinta [overflow-wrap:anywhere]">
                  {nome ? nome.valor : "Cliente"}
                  {nome?.duvidoso && (
                    <span className="ml-2 align-middle text-[10px] font-normal text-atencao">confira</span>
                  )}
                </h3>
                <span className="text-xs text-tinta-3">
                  reunida de {detalhes.length} documento{detalhes.length === 1 ? "" : "s"}
                </span>
              </div>

              <div className="flex flex-col gap-4 p-4">
                {secoes.map((secao) => (
                  <div key={secao.titulo}>
                    <h4 className="mb-2 mt-0 text-[11px] font-semibold uppercase tracking-wide text-tinta-3">
                      {secao.titulo}
                    </h4>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-3 max-[560px]:grid-cols-1">
                      {secao.campos.map((c) => (
                        <CampoFicha key={c.rotulo} rotulo={c.rotulo} dado={c.dado} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold uppercase tracking-wide text-tinta-3 [&::-webkit-details-marker]:hidden">
              <span className="inline-block transition-transform group-open:rotate-90" aria-hidden>
                ▸
              </span>
              Detalhe por documento ({detalhes.length})
            </summary>

            <div className="mt-3 flex flex-col gap-2">
              {detalhes.map((entrega) => {
                const extracao = entrega.extracao;
                const semantica = extracao?.classificacao_semantica;
                const achados = semantica?.achados?.length
                  ? semantica.achados
                  : (extracao?.campos ?? []).map((campo) => ({
                      campo: campo.rotulo,
                      valor: campo.valor,
                      importancia: campo.observacao || undefined,
                      relevante_para: undefined,
                    }));
                const finalidades = semantica?.serve_para ?? [];
                const tipo =
                  semantica?.tipo_semantico ||
                  extracao?.tipo?.descricao_detectado ||
                  entrega.tipo_detectado ||
                  "Documento não identificado";
                return (
                  <details key={entrega.id} className="group/doc border border-borda rounded-campo bg-papel-2">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3 [&::-webkit-details-marker]:hidden">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="inline-block flex-none text-tinta-3 transition-transform group-open/doc:rotate-90" aria-hidden>
                          ▸
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-tinta">{entrega.arquivo}</span>
                          <span className="block text-xs text-tinta-3">{tipo}</span>
                        </span>
                      </div>
                      <Selo tom={semantica ? "info" : "neutro"}>{semantica ? "Interpretado" : "OCR"}</Selo>
                    </summary>

                    <div className="border-t border-borda p-4">
                      {achados.length > 0 ? (
                        <div className="flex flex-col gap-3">
                          {achados.map((achado, indice) => (
                            <div
                              key={`${achado.campo}-${indice}`}
                              className="grid grid-cols-[minmax(120px,0.7fr)_minmax(180px,1fr)] gap-4 max-[640px]:grid-cols-1 max-[640px]:gap-1"
                            >
                              <strong className="text-xs text-tinta">{achado.campo}</strong>
                              <div className="text-xs leading-[1.55] text-tinta-2">
                                <strong className="font-codigo text-tinta">{achado.valor}</strong>
                                {achado.importancia && <span className="block mt-1">Por que importa: {achado.importancia}</span>}
                                {achado.relevante_para && <span className="block text-acao">Importante para: {achado.relevante_para}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="m-0 text-xs text-tinta-3">Nenhum dado jurídico específico foi destacado neste arquivo.</p>
                      )}

                      {finalidades.length > 0 && (
                        <div className="mt-4 pt-3 border-t border-borda">
                          <strong className="text-xs text-tinta">Este documento ajuda em:</strong>
                          <ul className="mt-2 mb-0 pl-5 text-xs leading-[1.55] text-tinta-2">
                            {finalidades.map((finalidade, indice) => (
                              <li key={`${finalidade.item}-${indice}`}>
                                <strong>{finalidade.item}</strong> — {finalidade.porque}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </details>
                );
              })}
            </div>
          </details>
        </div>
      )}
    </Cartao>
  );
}
