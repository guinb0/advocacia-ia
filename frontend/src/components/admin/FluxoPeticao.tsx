"use client";

/**
 * Fluxo de petição a partir da entrevista em TXT.
 *
 * 1. Análise jurídica resumida
 * 2. Duas opções de estratégia (escolha do advogado)
 * 3. Redação com embeddings de Modelos de Petição + documentos do caso
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

const TITULO = "font-ui text-base font-semibold m-0";
const TEXTO = "text-sm leading-relaxed text-tinta-2 m-0";

type Props = {
  casoId: string;
  agenteLigado: boolean;
  peticao: Peticao | null;
  onPeticaoPronta: () => void;
};

export default function FluxoPeticao({ casoId, agenteLigado, peticao, onPeticaoPronta }: Props) {
  const [estado, setEstado] = useState<EstadoPeticaoFluxo | null>(null);
  const [passo, setPasso] = useState<"inicio" | "analise" | "estrategia" | "redacao" | "pronta">(
    "inicio",
  );
  const [opcao, setOpcao] = useState(0);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [redacao, setRedacao] = useState<{ desde: string; runId: string } | null>(null);

  const recarregar = useCallback(async () => {
    try {
      const dados = await estadoPeticaoFluxo(casoId);
      setEstado(dados);
      if (dados.analise) setPasso((p) => (p === "inicio" ? "analise" : p));
      if (dados.estrategias?.length) setPasso((p) => (p === "analise" ? "estrategia" : p));
      if (dados.escolha != null) setOpcao(dados.escolha);
    } catch {
      /* estado vazio é normal no primeiro uso */
    }
  }, [casoId]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  useEffect(() => {
    if (!redacao) return;
    let ativo = true;
    const intervalo = setInterval(() => {
      void progressoPeticao(casoId, redacao.desde)
        .then(async (andamento) => {
          if (!ativo) return;
          if (andamento.generation_id) {
            const pronta = await buscarPeticao(casoId, andamento.generation_id);
            if (!ativo) return;
            setRedacao(null);
            setPasso("pronta");
            onPeticaoPronta();
            const arquivo = await baixarArquivoDaPeticao(casoId, pronta.id, "docx");
            if (arquivo) {
              baixarArquivo(arquivo, `Peticao inicial - v${pronta.version}.docx`);
            }
          }
        })
        .catch(() => {});
    }, 4000);
    return () => {
      ativo = false;
      clearInterval(intervalo);
    };
  }, [redacao, casoId, onPeticaoPronta]);

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

  const semEntrevista = !estado?.entrevista?.texto;

  return (
    <Cartao className="grid gap-4">
      <header className="grid gap-1">
        <h2 className={TITULO}>Petição a partir da entrevista</h2>
        <p className={TEXTO}>
          Usa a transcrição do atendimento, os modelos de petição treinados (embeddings de
          estilo) e os documentos já enviados ao agente (embeddings do caso).
        </p>
      </header>

      {semEntrevista && (
        <Aviso tom="atencao" titulo="Sem entrevista">
          Envie ou grave a entrevista em TXT antes de gerar a petição.
        </Aviso>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Erro">
          {erro}
        </Aviso>
      )}

      {estado?.entrevista && (
        <details className="text-xs text-tinta-3">
          <summary className="cursor-pointer font-semibold text-tinta-2">
            Transcrição ({estado.entrevista.caracteres} caracteres)
          </summary>
          <pre className="mt-2 whitespace-pre-wrap font-corpo text-xs max-h-48 overflow-auto">
            {estado.entrevista.previa}
            {estado.entrevista.caracteres > 2000 ? "\n…" : ""}
          </pre>
        </details>
      )}

      {passo === "inicio" && !semEntrevista && (
        <Botao
          variante="primario"
          disabled={!agenteLigado || ocupado !== null}
          onClick={() =>
            void executar("analise", async () => {
              await analisarPeticaoFluxo(casoId);
              setPasso("analise");
            })
          }
        >
          {ocupado === "analise" ? "Analisando…" : "1. Analisar entrevista"}
        </Botao>
      )}

      {estado?.analise && (
        <section className="grid gap-2 border-l-2 border-ok pl-3">
          <h3 className="text-sm font-semibold m-0">Análise jurídica</h3>
          <p className={TEXTO}>{estado.analise.resumo}</p>
          {estado.analise.lacunas.length > 0 && (
            <ul className="text-xs text-tinta-3 m-0 pl-4">
              {estado.analise.lacunas.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          )}
          {passo === "analise" && (
            <Botao
              variante="primario"
              disabled={!agenteLigado || ocupado !== null}
              onClick={() =>
                void executar("estrategias", async () => {
                  await proporEstrategiasPeticaoFluxo(casoId);
                  setPasso("estrategia");
                })
              }
            >
              {ocupado === "estrategias" ? "Gerando opções…" : "2. Propor duas estratégias"}
            </Botao>
          )}
        </section>
      )}

      {estado?.estrategias && estado.estrategias.length >= 2 && (
        <section className="grid gap-3">
          <h3 className="text-sm font-semibold m-0">Escolha a estratégia</h3>
          {estado.estrategias.map((op: EstrategiaFluxo, indice: number) => (
            <label
              key={indice}
              className={`block border p-3 cursor-pointer ${
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
              <p className={`${TEXTO} mt-1`}>{op.tese}</p>
              <p className="text-xs text-tinta-3 mt-1">{op.fundamentacao}</p>
            </label>
          ))}
          {(passo === "estrategia" || passo === "analise") && (
            <Botao
              variante="primario"
              disabled={!agenteLigado || ocupado !== null || redacao !== null}
              onClick={() =>
                void executar("gerar", async () => {
                  const pedido = await gerarPeticaoFluxo(casoId, opcao);
                  setPasso("redacao");
                  if (pedido.requested_at) {
                    setRedacao({
                      desde: pedido.requested_at,
                      runId: pedido.run_id ?? "",
                    });
                  }
                })
              }
            >
              {ocupado === "gerar" || redacao ? "Redigindo com modelos…" : "3. Gerar petição"}
            </Botao>
          )}
        </section>
      )}

      {peticao && passo === "pronta" && (
        <Aviso tom="ok" titulo="Petição gerada">
          Versão {peticao.version} disponível abaixo. O arquivo .docx foi baixado automaticamente.
        </Aviso>
      )}
    </Cartao>
  );
}
