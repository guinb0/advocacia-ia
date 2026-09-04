"use client";

/**
 * Análise + petição local (DeepSeek) — entrevista + OCR, sem agente.
 * O botão principal fica no cabeçalho do dossiê; aqui só resultado e edição.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Cartao, RotuloCampo, Campo } from "@/components/ui/Basicos";
import {
  baixarArquivoDaPeticao,
  buscarPeticao,
  estadoPeticaoFluxo,
  gerarAnaliseEPeticao,
  salvarRascunhoPeticao,
  type EstadoPeticaoFluxo,
  type Peticao,
  type SecaoPeticao,
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

export type ControlesGeracaoPeticao = {
  gerar: () => void;
  ocupado: boolean;
  podeGerar: boolean;
  rotulo: string;
};

type Props = {
  casoId: string;
  temEntrevista: boolean;
  onControlesGeracao?: (controles: ControlesGeracaoPeticao) => void;
};

export default function FluxoPeticao({ casoId, temEntrevista, onControlesGeracao }: Props) {
  const [estado, setEstado] = useState<EstadoPeticaoFluxo | null>(null);
  const [peticao, setPeticao] = useState<Peticao | null>(null);
  const [edicao, setEdicao] = useState<Record<string, string>>({});
  const [ocupado, setOcupado] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [mostrarPrevia, setMostrarPrevia] = useState(true);

  const recarregar = useCallback(async () => {
    try {
      const dados = await estadoPeticaoFluxo(casoId);
      setEstado(dados);
      if (dados.peticao_pronta) {
        const pronta = await buscarPeticao(casoId, "local");
        setPeticao(pronta);
      }
    } catch {
      /* primeiro uso */
    }
  }, [casoId]);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  useEffect(() => {
    if (!peticao?.sections) return;
    setEdicao(Object.fromEntries(peticao.sections.map((s) => [s.code, s.content])));
  }, [peticao?.id, peticao?.sections]);

  const gerar = useCallback(async () => {
    setErro(null);
    setOcupado(true);
    try {
      const resultado = await gerarAnaliseEPeticao(casoId);
      if (resultado.peticao) {
        setPeticao(resultado.peticao);
        if (resultado.analise) {
          setEstado((atual) => ({ ...(atual ?? {}), analise: resultado.analise }));
        }
        await recarregar();
        const arquivo = await baixarArquivoDaPeticao(casoId, "local", "docx");
        baixarArquivo(arquivo, `Peticao inicial - v${resultado.peticao.version}.docx`);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha ao gerar a petição.");
    } finally {
      setOcupado(false);
    }
  }, [casoId, recarregar]);

  const semEntrevista = !temEntrevista && !estado?.entrevista?.texto;
  const rotuloGerar = ocupado
    ? "Analisando e redigindo…"
    : peticao
      ? "Gerar de novo"
      : "Gerar análise e petição";

  useEffect(() => {
    onControlesGeracao?.({
      gerar: () => void gerar(),
      ocupado,
      // A API valida a transcrição real. Não bloqueie o botão por metadados
      // incompletos do dossiê (casos antigos podem ter texto e `caracteres` zerado).
      podeGerar: true,
      rotulo: rotuloGerar,
    });
  }, [onControlesGeracao, gerar, ocupado, semEntrevista, rotuloGerar]);

  async function salvar(baixarPdf = false) {
    if (!peticao) return;
    setSalvando(true);
    setErro(null);
    try {
      const secoes = (peticao.sections ?? []).map((s) => ({
        code: s.code,
        content: edicao[s.code] ?? s.content,
      }));
      const atualizada = await salvarRascunhoPeticao(casoId, peticao.id, secoes);
      setPeticao(atualizada);
      const formato = baixarPdf ? "pdf" : "docx";
      const arquivo = await baixarArquivoDaPeticao(casoId, peticao.id, formato);
      baixarArquivo(arquivo, `Peticao inicial - v${atualizada.version}.${formato}`);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  const analise = estado?.analise;
  const prep = estado?.preparacao;

  return (
    <Cartao className="grid gap-4">
      <header className="grid gap-2">
        <h2 className={TITULO}>Análise e petição</h2>
        <p className={SUB}>
          Cruza a entrevista com os documentos lidos por OCR e redige a petição inicial com
          DeepSeek. Use o botão no topo do dossiê para gerar.
        </p>
      </header>

      {semEntrevista && (
        <Aviso tom="atencao" titulo="Falta a entrevista">
          Este caso ainda não tem transcrição do atendimento.
        </Aviso>
      )}

      {erro && (
        <Aviso tom="critico" titulo="Erro">
          {erro}
        </Aviso>
      )}

      {prep && (
        <div className="grid grid-cols-2 gap-2 text-xs text-tinta-3">
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{prep.documentos_lidos ?? 0}</strong>
            docs com texto OCR
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {prep.checklist_entregues ?? 0}/{prep.checklist_obrigatorios ?? "?"}
            </strong>
            checklist obrigatório
          </div>
        </div>
      )}

      {analise && (
        <section className="grid gap-2 border-l-[3px] border-ok pl-4">
          <h3 className="text-sm font-semibold m-0">Análise do caso</h3>
          <p className={TEXTO}>{analise.resumo}</p>
          {analise.cruzamento_entrevista_documentos && (
            <p className={TEXTO}>
              <span className="text-xs font-semibold text-tinta-3">Entrevista × documentos: </span>
              {analise.cruzamento_entrevista_documentos}
            </p>
          )}
          {analise.lacunas && analise.lacunas.length > 0 && (
            <ListaRotulo titulo="Lacunas" itens={analise.lacunas} />
          )}
        </section>
      )}

      {peticao && (
        <section className="grid gap-3 border border-borda p-4 bg-papel-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold m-0">
              Petição inicial — versão {peticao.version}
            </h3>
            <div className="flex gap-2 flex-wrap">
              <Botao
                variante="texto"
                pequeno
                onClick={() => setMostrarPrevia((atual) => !atual)}
              >
                {mostrarPrevia ? "Ocultar prévia" : "Mostrar prévia"}
              </Botao>
              <Botao
                variante="secundario"
                pequeno
                disabled={salvando || ocupado}
                onClick={() => void salvar(false)}
              >
                {salvando ? "Salvando…" : "Salvar e baixar .docx"}
              </Botao>
              <Botao
                variante="texto"
                pequeno
                disabled={salvando || ocupado}
                onClick={() => void salvar(true)}
              >
                Baixar PDF
              </Botao>
            </div>
          </div>

          {(peticao.readiness?.pendencias ?? []).length > 0 && (
            <Aviso tom="atencao" titulo="Pontos sem comprovação documental">
              Revise a minuta antes de protocolar.
            </Aviso>
          )}

          <div className={mostrarPrevia ? "grid gap-4 lg:grid-cols-2 lg:items-start" : "grid gap-4"}>
            <div className="grid gap-4">
              {(peticao.sections ?? []).map((secao: SecaoPeticao) => (
                <div key={secao.code} className="grid gap-1">
                  <RotuloCampo htmlFor={`secao-${secao.code}`}>
                    {secao.label || secao.code}
                  </RotuloCampo>
                  <Campo
                    area
                    id={`secao-${secao.code}`}
                    value={edicao[secao.code] ?? secao.content}
                    onChange={(e) =>
                      setEdicao((atual) => ({ ...atual, [secao.code]: e.target.value }))
                    }
                    rows={10}
                  />
                </div>
              ))}
            </div>

            {mostrarPrevia && (
              <PreviaPeticao
                titulo={peticao.title}
                secoes={peticao.sections ?? []}
                edicao={edicao}
              />
            )}
          </div>
        </section>
      )}

      {peticao?.jurimetria && <ModuloJurimetria dados={peticao.jurimetria} />}
    </Cartao>
  );
}

/**
 * Prévia ao vivo: lê o mesmo estado `edicao` dos textareas, então cada tecla
 * digitada aparece aqui sem round-trip com a API. É só leitura — quem edita
 * de verdade é o textarea ao lado; isto simula como a peça fica montada.
 */
function PreviaPeticao({
  titulo,
  secoes,
  edicao,
}: {
  titulo: string;
  secoes: SecaoPeticao[];
  edicao: Record<string, string>;
}) {
  return (
    <div className="lg:sticky lg:top-4 grid gap-2">
      <p className="text-xs font-semibold text-tinta-3 m-0 uppercase tracking-wide">
        Prévia da petição
      </p>
      <div className="font-titulo border border-borda-forte bg-papel shadow-sm p-8 max-h-[80vh] overflow-y-auto">
        <h1 className="text-center text-sm font-bold uppercase tracking-wide text-tinta mb-6">
          {titulo || "Petição inicial"}
        </h1>
        <div className="grid gap-4">
          {secoes.map((secao) => {
            const conteudo = edicao[secao.code] ?? secao.content;
            return (
              <section key={secao.code} className="grid gap-2">
                {secao.label && (
                  <h2 className="text-center text-xs font-bold uppercase tracking-wide text-tinta">
                    {secao.label}
                  </h2>
                )}
                <p className="text-sm leading-relaxed text-justify text-tinta-2 whitespace-pre-wrap m-0">
                  {conteudo || "—"}
                </p>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ModuloJurimetria({
  dados,
}: {
  dados: NonNullable<Peticao["jurimetria"]>;
}) {
  if (!dados.disponivel) {
    return (
      <section className="grid gap-3 border border-borda p-4 bg-papel">
        <h3 className="text-sm font-semibold m-0">Jurimetria da minuta</h3>
        <Aviso tom="atencao">{dados.aviso || "Base de processos indisponível."}</Aviso>
      </section>
    );
  }

  const estatisticas = dados.estatisticas;
  const merito = estatisticas?.desfechos_merito;
  const similaridade = estatisticas?.similaridade_amostra;
  return (
    <section className="grid gap-4 border border-borda p-4 bg-papel">
      <header className="grid gap-1">
        <h3 className="text-sm font-semibold m-0">Jurimetria da minuta</h3>
        <p className={SUB}>
          Busca vetorial pelos embeddings do acervo do Advocacia IA. Módulo interno de apoio
          à decisão; não integra o texto nem o arquivo da petição.
        </p>
      </header>

      {estatisticas && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-tinta-3">
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">{estatisticas.processos_analisados}</strong>
            processos semelhantes
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {merito ? `${merito.favoraveis}/${merito.processos} (${merito.percentual.toLocaleString("pt-BR")}%)` : "—"}
            </strong>
            favoráveis no mérito
          </div>
          <div className="border border-borda p-2 bg-papel-2">
            <strong className="block text-tinta-2">
              {similaridade ? similaridade.mediana.toFixed(3) : "—"}
            </strong>
            similaridade mediana
          </div>
        </div>
      )}

      {dados.sintese && <p className={TEXTO}>{dados.sintese}</p>}
      {(dados.fundamentos ?? []).length > 0 && (
        <ListaJurimetria
          titulo="Fundamentos que orientaram a análise"
          itens={(dados.fundamentos ?? []).map((item) => ({
            titulo: item.ponto || "Fundamento",
            detalhe: item.impacto || "",
            refs: item.processos,
          }))}
        />
      )}
      {(dados.riscos ?? []).length > 0 && (
        <ListaJurimetria
          titulo="Riscos e distinções"
          itens={(dados.riscos ?? []).map((item) => ({
            titulo: item.ponto || "Risco",
            detalhe: item.distincao || "",
            refs: item.processos,
          }))}
        />
      )}

      {(dados.precedentes ?? []).length > 0 && (
        <div className="grid gap-2">
          <h4 className="text-xs font-semibold text-tinta-3 m-0">Decisões consultadas</h4>
          <ul className="grid gap-2 list-none p-0 m-0">
            {(dados.precedentes ?? []).map((item) => (
              <li key={item.indice} className="text-xs text-tinta-2 border-l-2 border-borda pl-3">
                <strong>[{item.indice}] Processo {item.processo || "não informado"}</strong>
                {` — ${item.resultado || "desfecho não informado"}; ${item.vara || "órgão não informado"}`}
                {typeof item.similaridade === "number" ? `; similaridade ${item.similaridade.toFixed(3)}` : ""}
                {item.url && <> — <a className="text-acao underline" href={item.url} target="_blank" rel="noreferrer">abrir decisão</a></>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-tinta-3 m-0">{dados.aviso}</p>
    </section>
  );
}

function ListaJurimetria({
  titulo,
  itens,
}: {
  titulo: string;
  itens: Array<{ titulo: string; detalhe: string; refs: string[] }>;
}) {
  return (
    <div className="grid gap-2">
      <h4 className="text-xs font-semibold text-tinta-3 m-0">{titulo}</h4>
      <ul className="grid gap-2 m-0 pl-4 text-xs text-tinta-2">
        {itens.map((item, indice) => (
          <li key={`${item.titulo}-${indice}`}>
            <strong>{item.titulo}</strong>{item.detalhe ? ` — ${item.detalhe}` : ""}{" "}
            <span className="text-tinta-3">[{item.refs.join(", ")}]</span>
          </li>
        ))}
      </ul>
    </div>
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
