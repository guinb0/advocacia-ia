"use client";

/**
 * Análise + petição local (DeepSeek) — entrevista + OCR, sem agente.
 * O botão principal fica no cabeçalho do dossiê; aqui só resultado e edição.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Cartao, RotuloCampo, Campo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import {
  baixarArquivoDaPeticao,
  buscarPeticao,
  estadoPeticaoFluxo,
  gerarAnaliseEPeticao,
  historicoDePeticao,
  revisarPeticaoComPrompt,
  salvarRascunhoPeticao,
  type EstadoPeticaoFluxo,
  type HistoricoDePeticao,
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
  /* O botão de gerar mora no cabeçalho do dossiê, longe deste cartão: sem o
   * resultado aqui, quem clicava lá em cima não via nem o erro nem o fim. */
  erro: string | null;
  concluido: string | null;
};

type AcaoPeticao = "gerar" | "salvar" | "revisar";
/** Resultado da última ação, com a ação que o produziu — cada um aparece junto do próprio botão. */
type Retorno = { acao: AcaoPeticao; texto: string } | null;

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
  /** Qual formato está sendo salvo: cada botão de download mostra só o próprio andamento. */
  const [salvandoComo, setSalvandoComo] = useState<"docx" | "pdf" | null>(null);
  const salvando = salvandoComo !== null;
  const [erro, setErro] = useState<Retorno>(null);
  const [concluido, setConcluido] = useState<Retorno>(null);
  const [mostrarPrevia, setMostrarPrevia] = useState(true);

  // Revisão por prompt — issue "Permitir alteração da petição por prompt com
  // rastreabilidade". `historico` fica separado de `peticao` porque uma falha
  // ao carregar o histórico não pode esconder a petição, que é o que importa
  // primeiro.
  const [promptRevisao, setPromptRevisao] = useState("");
  /* Marcado por padrão: a crítica quase sempre é uma lição do escritório, e é
   * dela que a IA aprende. Desmarcar é o que impede um ajuste pontual — "troque
   * o nome do cliente" — de virar regra de todas as petições da categoria. */
  const [ensinarIA, setEnsinarIA] = useState(true);
  const [revisando, setRevisando] = useState(false);
  const [historico, setHistorico] = useState<HistoricoDePeticao | null>(null);
  const [mostrarHistorico, setMostrarHistorico] = useState(false);

  const recarregar = useCallback(async () => {
    try {
      const dados = await estadoPeticaoFluxo(casoId);
      setEstado(dados);
      if (dados.peticao_pronta) {
        const pronta = await buscarPeticao(casoId, "local");
        setPeticao(pronta);
        try {
          setHistorico(await historicoDePeticao(casoId, "local"));
        } catch {
          /* rastreabilidade é complementar — a petição continua utilizável sem ela */
        }
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
    setConcluido(null);
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
        setConcluido({
          acao: "gerar",
          texto: `Petição gerada (versão ${resultado.peticao.version}) e .docx baixado.`,
        });
      }
    } catch (e) {
      setErro({ acao: "gerar", texto: e instanceof Error ? e.message : "Falha ao gerar a petição." });
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

  const erroGerar = erro?.acao === "gerar" ? erro.texto : null;
  const concluidoGerar = concluido?.acao === "gerar" ? concluido.texto : null;

  useEffect(() => {
    onControlesGeracao?.({
      gerar: () => void gerar(),
      ocupado,
      // A API valida a transcrição real. Não bloqueie o botão por metadados
      // incompletos do dossiê (casos antigos podem ter texto e `caracteres` zerado).
      podeGerar: true,
      rotulo: rotuloGerar,
      erro: erroGerar,
      concluido: concluidoGerar,
    });
  }, [onControlesGeracao, gerar, ocupado, semEntrevista, rotuloGerar, erroGerar, concluidoGerar]);

  async function salvar(baixarPdf = false) {
    if (!peticao) return;
    const formato = baixarPdf ? "pdf" : "docx";
    setSalvandoComo(formato);
    setErro(null);
    setConcluido(null);
    try {
      const secoes = (peticao.sections ?? []).map((s) => ({
        code: s.code,
        content: edicao[s.code] ?? s.content,
      }));
      const atualizada = await salvarRascunhoPeticao(casoId, peticao.id, secoes);
      setPeticao(atualizada);
      const arquivo = await baixarArquivoDaPeticao(casoId, peticao.id, formato);
      baixarArquivo(arquivo, `Peticao inicial - v${atualizada.version}.${formato}`);
      setConcluido({ acao: "salvar", texto: `Versão ${atualizada.version} salva e .${formato} baixado.` });
    } catch (e) {
      setErro({ acao: "salvar", texto: e instanceof Error ? e.message : "Não foi possível salvar." });
    } finally {
      setSalvandoComo(null);
    }
  }

  async function revisar() {
    if (!peticao || !promptRevisao.trim()) return;
    setRevisando(true);
    setErro(null);
    setConcluido(null);
    try {
      const resultado = await revisarPeticaoComPrompt(
        casoId,
        peticao.id,
        promptRevisao.trim(),
        ensinarIA,
      );
      setPeticao(resultado.peticao);
      setPromptRevisao("");
      setConcluido({
        acao: "revisar",
        texto: `Revisão aplicada — a petição está na versão ${resultado.peticao.version}.`,
      });
      setHistorico((atual) => ({
        criticas: resultado.criticas,
        versoes: atual?.versoes ?? [],
      }));
      await recarregar();
    } catch (e) {
      setErro({
        acao: "revisar",
        texto: e instanceof Error ? e.message : "Não foi possível aplicar a revisão.",
      });
    } finally {
      setRevisando(false);
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

      {/* O erro de gerar aparece também aqui, além do botão do cabeçalho: quem já
        * rolou até este cartão não vê mais o topo. Salvar e revisar mostram o
        * próprio resultado junto dos seus botões. */}
      {erro?.acao === "gerar" && (
        <Aviso tom="critico" titulo="A petição não foi gerada">
          {erro.texto}
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
              <BotaoProcesso
                variante="secundario"
                pequeno
                processando={salvandoComo === "docx"}
                textoProcessando="Salvando…"
                aguardando={ocupado || salvandoComo === "pdf"}
                onClick={() => salvar(false)}
              >
                Salvar e baixar .docx
              </BotaoProcesso>
              <BotaoProcesso
                variante="texto"
                pequeno
                processando={salvandoComo === "pdf"}
                textoProcessando="Gerando o PDF…"
                aguardando={ocupado || salvandoComo === "docx"}
                onClick={() => salvar(true)}
              >
                Baixar PDF
              </BotaoProcesso>
            </div>
          </div>

          {erro?.acao === "salvar" && (
            <Aviso tom="critico" titulo="Não foi possível salvar">
              {erro.texto}
            </Aviso>
          )}
          {concluido?.acao === "salvar" && <Aviso tom="ok">{concluido.texto}</Aviso>}

          {(peticao.readiness?.pendencias ?? []).length > 0 && (
            <Aviso tom="atencao" titulo="Pontos sem comprovação documental">
              Revise a minuta antes de protocolar.
            </Aviso>
          )}

          {historico && (historico.criticas.length > 0 || historico.versoes.length > 0) && (
            <HistoricoDeCriticas
              historico={historico}
              aberto={mostrarHistorico}
              onAlternar={() => setMostrarHistorico((atual) => !atual)}
            />
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

          {/* A revisão por prompt vem DEPOIS do texto: ela age sobre o que está
            * escrito, e pedir a mudança antes de ver a peça invertia a leitura —
            * o advogado abria a tela num campo em branco e precisava rolar para
            * descobrir o que iria alterar. */}
          <div className="grid gap-2 border border-borda-forte bg-papel p-3">
            <RotuloCampo htmlFor="prompt-revisao">
              Pedir uma revisão por prompt
            </RotuloCampo>
            <p className="text-xs text-tinta-3 m-0">
              Descreva o que deve mudar (ex.: &quot;separe dano moral do material nos
              pedidos&quot;). A IA aplica só o que você pedir e preserva o resto do texto. A
              versão atual fica guardada no histórico, e a revisão volta para
              &quot;em revisão&quot; — precisa aprovar de novo.
            </p>
            <Campo
              area
              id="prompt-revisao"
              value={promptRevisao}
              onChange={(e) => setPromptRevisao(e.target.value)}
              rows={3}
              placeholder="O que deve mudar nesta petição?"
            />
            <label className="flex items-start gap-2 text-xs text-tinta-2 cursor-pointer">
              <input
                type="checkbox"
                className="mt-[2px]"
                checked={ensinarIA}
                onChange={(e) => setEnsinarIA(e.target.checked)}
              />
              <span>
                Ensinar a IA com esta correção
                <span className="block text-tinta-3">
                  Marcado, ela passa a valer para as próximas petições desta mesma
                  categoria de caso. Desmarque quando o ajuste for só deste cliente
                  (um nome, um valor, uma data) — a correção continua no histórico
                  deste caso de qualquer jeito.
                </span>
              </span>
            </label>
            <div>
              <BotaoProcesso
                variante="secundario"
                pequeno
                processando={revisando}
                textoProcessando="Aplicando a revisão…"
                pendencia={promptRevisao.trim() ? null : "Descreva acima o que deve mudar."}
                aguardando={salvando || ocupado}
                erro={erro?.acao === "revisar" ? erro.texto : null}
                concluido={concluido?.acao === "revisar" ? concluido.texto : null}
                onClick={revisar}
              >
                Aplicar revisão
              </BotaoProcesso>
            </div>
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

/**
 * A rastreabilidade que a issue pede: quem pediu cada revisão, quando, sobre
 * qual versão — visível, não só guardada no banco. Fechado por padrão porque
 * a maioria das visitas à tela não precisa dela; abre com um clique quando
 * alguém precisa auditar o que mudou e por quê.
 */
function HistoricoDeCriticas({
  historico,
  aberto,
  onAlternar,
}: {
  historico: HistoricoDePeticao;
  aberto: boolean;
  onAlternar: () => void;
}) {
  return (
    <div className="grid gap-2 border border-borda p-3 bg-papel">
      <button
        type="button"
        className="flex items-center justify-between gap-2 text-left text-xs font-semibold text-tinta-3 uppercase tracking-wide bg-transparent border-0 p-0 cursor-pointer"
        onClick={onAlternar}
      >
        <span>
          Histórico de revisões ({historico.criticas.length} crítica
          {historico.criticas.length === 1 ? "" : "s"})
        </span>
        <span aria-hidden>{aberto ? "▲" : "▼"}</span>
      </button>
      {aberto && (
        <ul className="grid gap-3 m-0 p-0 list-none">
          {historico.criticas.length === 0 && (
            <li className="text-xs text-tinta-3">Nenhuma crítica registrada ainda.</li>
          )}
          {[...historico.criticas].reverse().map((critica) => (
            <li key={critica.id} className="grid gap-1 border-l-2 border-borda pl-3">
              <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-tinta-3">
                <strong className="text-tinta-2">{critica.usuario || "usuário não identificado"}</strong>
                <span>
                  v{critica.versao_origem} → v{critica.versao_resultado}
                </span>
                <span>{new Date(critica.criado_em).toLocaleString("pt-BR")}</span>
                {/* Qual crítica está ensinando a IA e qual valeu só aqui — sem
                  * isto não há como saber por que a próxima petição saiu
                  * diferente. */}
                <span
                  className={
                    critica.generaliza === false
                      ? "text-tinta-3"
                      : "text-ok font-semibold"
                  }
                  title={
                    critica.generaliza === false
                      ? "Valeu só neste caso — não instrui as próximas petições."
                      : "Esta correção instrui as próximas petições desta categoria."
                  }
                >
                  {critica.generaliza === false ? "só neste caso" : "ensina a IA"}
                </span>
              </div>
              <p className="text-sm text-tinta-2 m-0 whitespace-pre-wrap">{critica.prompt}</p>
            </li>
          ))}
        </ul>
      )}
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
        {dados.jurisdicao && (
          <p className="text-xs text-tinta-3 m-0">
            Focada em <strong className="text-tinta-2">{dados.jurisdicao}</strong>.
          </p>
        )}
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
