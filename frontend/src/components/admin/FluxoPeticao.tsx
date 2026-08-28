"use client";

/**
 * Fluxo principal do caso: entrevista + documentos → análise → estratégia → petição.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Cartao } from "@/components/ui/Basicos";
import {
  analisarPeticaoFluxo,
  baixarArquivoDaPeticao,
  buscarPeticao,
  estadoPeticaoFluxo,
  gerarPeticaoFluxo,
  proporEstrategiasPeticaoFluxo,
  progressoPeticao,
  type EstrategiaFluxo,
  type EstadoPeticaoFluxo,
  type Peticao,
} from "@/lib/agente";

function baixarArquivo(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

const TITULO = "font-ui text-lg font-semibold m-0";
const SUB = "text-sm leading-relaxed text-tinta-3 m-0";
const TEXTO = "text-sm leading-relaxed text-tinta-2 m-0";
const PASSOS = ["Análise do caso", "Estratégias", "Redação"] as const;

type Props = {
  casoId: string;
  /** Há transcrição no Acervo — independe do agente estar respondendo. */
  temEntrevista: boolean;
  agenteLigado: boolean;
  peticao: Peticao | null;
  onPeticaoPronta: () => void;
  onAnalisePronta?: () => void;
};

export default function FluxoPeticao({
  casoId,
  temEntrevista,
  agenteLigado,
  peticao,
  onPeticaoPronta,
  onAnalisePronta,
}: Props) {
  const [estado, setEstado] = useState<EstadoPeticaoFluxo | null>(null);
  const [passo, setPasso] = useState<0 | 1 | 2 | 3>(0);
  const [opcao, setOpcao] = useState(0);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [redacao, setRedacao] = useState<{ desde: string; runId: string } | null>(null);
  const [passosRedacao, setPassosRedacao] = useState(0);

  const recarregar = useCallback(async () => {
    try {
      const dados = await estadoPeticaoFluxo(casoId);
      setEstado(dados);
      if (dados.analise) setPasso((p) => (p < 1 ? 1 : p));
      if (dados.estrategias?.length) setPasso((p) => (p < 2 ? 2 : p));
      if (dados.escolha != null) setOpcao(dados.escolha);
      if (peticao) setPasso(3);
    } catch {
      /* primeiro uso */
    }
  }, [casoId, peticao]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  /* A geração pode terminar em outro worker/processo (ou após um refresh do dossiê).
   * Quando a petição chega pelas props, não deixe uma tentativa antiga manter o botão
   * permanentemente cinza. */
  useEffect(() => {
    if (!peticao) return;
    setRedacao(null);
    setOcupado(null);
    setPasso(3);
  }, [peticao]);

  useEffect(() => {
    if (!redacao) return;
    let ativo = true;
    const limite = Date.now() + 16 * 60 * 1000;
    const intervalo = setInterval(() => {
      void progressoPeticao(casoId, redacao.desde)
        .then(async (andamento) => {
          if (!ativo) return;
          setPassosRedacao(andamento.completed_steps);
          if (andamento.status === "DONE" && andamento.generation_id) {
            const pronta = await buscarPeticao(casoId, andamento.generation_id);
            if (!ativo) return;
            setRedacao(null);
            setPasso(3);
            onPeticaoPronta();
            const arquivo = await baixarArquivoDaPeticao(casoId, pronta.id, "docx");
            if (arquivo) {
              baixarArquivo(arquivo, `Peticao inicial - v${pronta.version}.docx`);
            }
          }
        })
        .catch((e) => {
          if (!ativo) return;
          setRedacao(null);
          setErro(e instanceof Error ? e.message : "Não foi possível acompanhar a redação.");
        });
      if (Date.now() > limite) {
        setRedacao(null);
        setErro(
          "A redação passou do prazo sem concluir. Verifique se o worker do agente está no ar e tente de novo.",
        );
      }
    }, 4000);
    return () => {
      ativo = false;
      clearInterval(intervalo);
    };
  }, [redacao, casoId, onPeticaoPronta]);

  async function gerarComModelos() {
    setErro(null);
    try {
      if (!estado?.analise) {
        setOcupado("analise");
        await analisarPeticaoFluxo(casoId);
        setPasso(1);
        onAnalisePronta?.();
      }
      if (!estado?.estrategias?.length) {
        setOcupado("estrategias");
        await proporEstrategiasPeticaoFluxo(casoId);
        await recarregar();
      }
      setOcupado("gerar");
      const pedido = await gerarPeticaoFluxo(casoId, opcao);
      setPasso(2);
      const desde =
        typeof pedido.requested_at === "string"
          ? pedido.requested_at
          : new Date().toISOString();
      setRedacao({
        desde,
        runId: pedido.run_id ?? "",
      });
      setPassosRedacao(0);
      await recarregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha na redação.");
    } finally {
      setOcupado(null);
    }
  }

  async function executar(rotulo: string, acao: () => Promise<unknown>) {
    setErro(null);
    setOcupado(rotulo);
    try {
      await acao();
      await recarregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha na operação.");
    } finally {
      setOcupado(null);
    }
  }

  const semEntrevista = !temEntrevista && !estado?.entrevista?.texto;
  const prep = estado?.preparacao;

  return (
    <Cartao className="grid gap-5">
      <header className="grid gap-2">
        <h2 className={TITULO}>Petição e estratégia do caso</h2>
        <p className={SUB}>
          Cruza a entrevista já transcrita com os documentos do checklist, propõe duas
          estratégias e redige a peça com os modelos treinados e os embeddings dos anexos.
        </p>
        <ol className="flex flex-wrap gap-2 m-0 p-0 list-none text-xs font-semibold">
          {PASSOS.map((rotulo, indice) => {
            const ativo = passo === indice + 1 || (passo === 3 && indice === 2);
            const feito = passo > indice + 1 || passo === 3;
            return (
              <li
                key={rotulo}
                className={`px-3 py-1 border rounded-full ${
                  feito
                    ? "border-ok text-ok bg-papel-2"
                    : ativo
                      ? "border-acao text-acao"
                      : "border-borda text-tinta-3"
                }`}
              >
                {feito ? "✓ " : `${indice + 1}. `}
                {rotulo}
              </li>
            );
          })}
        </ol>
      </header>

      {semEntrevista && (
        <Aviso tom="atencao" titulo="Falta a entrevista">
          Este caso ainda não tem transcrição do atendimento — ela é o ponto de partida do
          fluxo.
        </Aviso>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Erro">
          {erro}
        </Aviso>
      )}

      {prep && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-tinta-3">
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{prep.fatos_no_agente ?? 0}</strong>
            fatos no agente
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{prep.documentos_lidos ?? 0}</strong>
            docs com texto
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{prep.achados_documentos ?? 0}</strong>
            achados cruzados
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {prep.checklist_entregues ?? 0}/{prep.checklist_obrigatorios ?? "?"}
            </strong>
            checklist obrigatório
          </div>
        </div>
      )}

      {passo === 0 && !semEntrevista && !estado?.analise && (
        <Botao
          variante="primario"
          disabled={ocupado !== null || redacao !== null}
          onClick={() => void gerarComModelos()}
        >
          {ocupado === "analise"
            ? "Analisando entrevista e documentos…"
            : ocupado === "estrategias"
              ? "Definindo a estratégia…"
              : ocupado === "gerar" || redacao
                ? "Redigindo a petição…"
                : "Gerar petição agora"}
        </Botao>
      )}

      {estado?.analise && (
        <section className="grid gap-3 border-l-[3px] border-ok pl-4">
          <h3 className="text-sm font-semibold m-0">Análise unificada</h3>
          <p className={TEXTO}>{estado.analise.resumo}</p>
          {estado.analise.cruzamento_entrevista_documentos && (
            <div>
              <p className="text-xs font-semibold text-tinta-3 m-0 mb-1">
                Entrevista × documentos
              </p>
              <p className={TEXTO}>{estado.analise.cruzamento_entrevista_documentos}</p>
            </div>
          )}
          {estado.analise.fatos_confirmados && estado.analise.fatos_confirmados.length > 0 && (
            <ListaRotulo titulo="Confirmados nos documentos" itens={estado.analise.fatos_confirmados} />
          )}
          {estado.analise.fatos_so_na_entrevista &&
            estado.analise.fatos_so_na_entrevista.length > 0 && (
              <ListaRotulo
                titulo="Só na entrevista (alegações)"
                itens={estado.analise.fatos_so_na_entrevista}
              />
            )}
          {estado.analise.lacunas.length > 0 && (
            <ListaRotulo titulo="Lacunas" itens={estado.analise.lacunas} />
          )}
          {estado.analise.achados_documentos &&
            estado.analise.achados_documentos.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-tinta-3 m-0 mb-1">
                  Achados nos documentos
                </p>
                <ul className="text-xs text-tinta-2 m-0 pl-0 list-none grid gap-2">
                  {estado.analise.achados_documentos.map((a, i) => (
                    <li key={`${a.documento}-${i}`} className="border-l-2 border-borda pl-2">
                      <strong>{a.informacao}</strong>
                      {a.contradiz && (
                        <span className="text-critico ml-1">· contradiz a entrevista</span>
                      )}
                      <div className="text-tinta-3">{a.documento}</div>
                      {a.citacao && (
                        <blockquote className="m-0 mt-1 text-tinta-3 italic border-l border-borda pl-2">
                          {a.citacao}
                        </blockquote>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          {passo >= 1 && passo < 3 && agenteLigado && (
            <div className="grid gap-2 pt-1">
              <Botao
                variante="primario"
                disabled={ocupado !== null || redacao !== null}
                onClick={() => void gerarComModelos()}
              >
                {ocupado === "gerar" || ocupado === "estrategias" || redacao
                  ? "Redigindo com modelos e documentos do caso…"
                  : "Gerar petição com modelos do escritório"}
              </Botao>
              <p className="text-xs text-tinta-3 m-0">
                Usa os modelos de petição treinados (style) e os embeddings dos documentos
                anexados ao caso.
              </p>
            </div>
          )}
          {estado.estrategias && estado.estrategias.length >= 2 && passo < 3 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-tinta-3 font-semibold">
                Ajustar estratégia antes de gerar
              </summary>
              <div className="grid gap-2 mt-2">
                {estado.estrategias.map((op: EstrategiaFluxo, indice: number) => (
                  <label
                    key={indice}
                    className={`block border p-2 cursor-pointer text-xs ${
                      opcao === indice ? "border-destaque bg-papel-2" : "border-borda"
                    }`}
                  >
                    <input
                      type="radio"
                      name="estrategia-fluxo"
                      className="mr-2"
                      checked={opcao === indice}
                      onChange={() => setOpcao(indice)}
                    />
                    <strong>{op.titulo}</strong>
                    <p className={`${TEXTO} mt-1 mb-0`}>{op.tese}</p>
                  </label>
                ))}
              </div>
            </details>
          )}
        </section>
      )}

      {redacao && (
        <Aviso tom="info" titulo="Redação em andamento">
          {passosRedacao > 0
            ? `${passosRedacao} etapa(s) concluída(s) no agente — a peça aparece aqui quando terminar.`
            : "A tarefa foi enfileirada no agente. A redação leva alguns minutos (várias seções + revisão)."}
          O download do .docx abre sozinho quando terminar.
        </Aviso>
      )}

      {peticao && (
        <section className="grid gap-3 border border-borda p-4 bg-papel-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold m-0">
              Petição inicial — versão {peticao.version}
            </h3>
            <div className="flex gap-2 flex-wrap">
              <Botao
                variante="secundario"
                pequeno
                onClick={() =>
                  void baixarArquivoDaPeticao(casoId, peticao.id, "docx").then((arquivo) =>
                    baixarArquivo(arquivo, `Peticao inicial - v${peticao.version}.docx`),
                  )
                }
              >
                Baixar .docx
              </Botao>
              <Botao
                variante="texto"
                pequeno
                onClick={() =>
                  void baixarArquivoDaPeticao(casoId, peticao.id, "pdf").then((arquivo) =>
                    baixarArquivo(arquivo, `Peticao inicial - v${peticao.version}.pdf`),
                  )
                }
              >
                Baixar PDF
              </Botao>
            </div>
          </div>
          {peticao.readiness?.pendencias && peticao.readiness.pendencias.length > 0 && (
            <Aviso tom="atencao" titulo="Pontos sem comprovação documental">
              Revise a minuta antes de protocolar — há fatos que ainda dependem só do relato.
            </Aviso>
          )}
        </section>
      )}
    </Cartao>
  );
}

function ListaRotulo({ titulo, itens }: { titulo: string; itens: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold text-tinta-3 m-0 mb-1">{titulo}</p>
      <ul className="text-xs text-tinta-2 m-0 pl-4">
        {itens.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
