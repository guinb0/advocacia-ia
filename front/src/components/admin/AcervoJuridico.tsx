"use client";

/* Acervo Jurídico: as leis, súmulas e precedentes que a IA usa para fundamentar as peças.
 *
 * A tela só LÊ o acervo. As duas ações que mexem nele — verificar agora e reindexar — apenas
 * enfileiram a sincronização no servidor, e o texto das normas nunca é editado aqui. Sem a
 * migration 011 no PostgreSQL do RAG, o servidor responde `migracao_aplicada: false` e a tela
 * diz isso em vez de mostrar números vazios.
 *
 * Status sempre com símbolo e palavra (nunca cor sozinha): verde atualizado, amarelo pendente,
 * vermelho erro, cinza revogado, azul em andamento.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenCheck,
  Boxes,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileClock,
  Gavel,
  History,
  Landmark,
  RefreshCcw,
  ScrollText,
} from "lucide-react";

import {
  Aviso,
  BarraAbas,
  Botao,
  BotaoAba,
  Campo,
  CampoSeletor,
  Cartao,
  Selo,
  Tabela,
  Td,
  Th,
  TrZebra,
  Vazio,
} from "@/components/ui/Basicos";
import {
  ApiError,
  alertasDoAcervo,
  anotarNoAcervo,
  configuracaoDoAcervo,
  dispositivoDoAcervo,
  importarJurisprudencia,
  jurisprudenciaDoAcervo,
  normaDoAcervo,
  normasDoAcervo,
  problemasDoAcervo,
  reindexarNorma,
  resolverAlertaDoAcervo,
  resolverAutoridadeDoAcervo,
  resumoDoAcervo,
  sincronizacoesDoAcervo,
  verificarNormaAgora,
  type AlertaAcervo,
  type ConfiguracaoAcervo,
  type CorAcervo,
  type DispositivoAcervo,
  type EnvelopeAcervo,
  type JurisprudenciaAcervo,
  type NoArvoreAcervo,
  type NormaAcervo,
  type NormaDetalhe,
  type ProblemaAcervo,
  type ResumoAcervo,
  type SeloAcervo,
  type SincronizacaoAcervo,
} from "@/lib/api";
import type { TomSelo } from "@/lib/formato";

type Aba = "geral" | "legislacao" | "jurisprudencia" | "embeddings" | "atualizacoes" | "problemas";

const ABAS: { id: Aba; rotulo: string }[] = [
  { id: "geral", rotulo: "Visão geral" },
  { id: "legislacao", rotulo: "Legislação" },
  { id: "jurisprudencia", rotulo: "Jurisprudência" },
  { id: "embeddings", rotulo: "Embeddings" },
  { id: "atualizacoes", rotulo: "Atualizações" },
  { id: "problemas", rotulo: "Problemas" },
];

const TOM_DA_COR: Record<CorAcervo, { tom: TomSelo; simbolo: string }> = {
  verde: { tom: "ok", simbolo: "✓" },
  amarelo: { tom: "atencao", simbolo: "!" },
  vermelho: { tom: "critico", simbolo: "✕" },
  cinza: { tom: "neutro", simbolo: "⊘" },
  azul: { tom: "info", simbolo: "↻" },
};

/** Status jurídico de um dispositivo (VIGENTE, REVOGADA...) no mesmo código de cores do painel. */
const SELO_JURIDICO: Record<string, SeloAcervo> = {
  VIGENTE: { status: "VIGENTE", cor: "verde", texto: "Vigente" },
  vigente: { status: "VIGENTE", cor: "verde", texto: "Vigente" },
  ALTERADA: { status: "ALTERADA", cor: "cinza", texto: "Redação anterior" },
  REVOGADA: { status: "REVOGADA", cor: "cinza", texto: "Revogado" },
  revogado: { status: "REVOGADA", cor: "cinza", texto: "Revogado" },
  SUPERADA: { status: "SUPERADA", cor: "cinza", texto: "Superado" },
  SUSPENSA: { status: "SUSPENSA", cor: "amarelo", texto: "Suspenso" },
  AGUARDANDO_VERIFICACAO: { status: "AGUARDANDO_VERIFICACAO", cor: "amarelo", texto: "Aguardando verificação" },
};

const SEVERIDADE: Record<string, { tom: TomSelo; simbolo: string; texto: string }> = {
  alta: { tom: "critico", simbolo: "✕", texto: "Alta" },
  media: { tom: "atencao", simbolo: "!", texto: "Média" },
  baixa: { tom: "info", simbolo: "i", texto: "Baixa" },
};

function SeloStatus({ selo }: { selo: SeloAcervo }) {
  const visual = TOM_DA_COR[selo.cor] ?? TOM_DA_COR.amarelo;
  return (
    <Selo tom={visual.tom} simbolo={visual.simbolo}>
      {selo.texto}
    </Selo>
  );
}

function SeloJuridico({ status }: { status: string }) {
  return <SeloStatus selo={SELO_JURIDICO[status] ?? { status, cor: "amarelo", texto: status || "—" }} />;
}

function quando(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [a, m, d] = iso.split("-");
    return `${d}/${m}/${a}`;
  }
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? iso : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function numero(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("pt-BR");
}

function hashCurto(hash: string | null | undefined): string {
  return hash ? `${hash.slice(0, 12)}…` : "—";
}

function mensagemDeErro(e: unknown, padrao: string): string {
  return e instanceof ApiError ? e.message : padrao;
}

/** Barra de cobertura com a leitura em palavra ao lado — a cor sozinha não diz nada a quem não a distingue. */
function Cobertura({ percentual }: { percentual: number }) {
  const cor = percentual >= 99 ? "bg-ok" : percentual >= 60 ? "bg-atencao-marca" : "bg-critico";
  return (
    <div className="flex min-w-[140px] items-center gap-2">
      <div className="h-[6px] flex-1 overflow-hidden rounded-pill bg-papel-3">
        <i className={`block h-full rounded-pill ${cor}`} style={{ width: `${Math.max(0, Math.min(100, percentual))}%` }} />
      </div>
      <span className="text-xs tabular-nums text-tinta-2">{percentual.toLocaleString("pt-BR")}%</span>
    </div>
  );
}

function CartaoNumero({ icone, rotulo, valor, apoio }: { icone: ReactNode; rotulo: string; valor: string; apoio?: string }) {
  return (
    <div className="rounded-campo border border-borda bg-papel px-4 py-3 shadow-cartao">
      <div className="flex items-center gap-2 text-xs font-semibold text-tinta-3">
        {icone}
        {rotulo}
      </div>
      <div className="mt-1 font-titulo text-lg font-semibold tabular-nums text-tinta">{valor}</div>
      {apoio && <div className="mt-[2px] text-xs text-tinta-3">{apoio}</div>}
    </div>
  );
}

function AvisoDeEnvelope({ envelope }: { envelope: EnvelopeAcervo | null }) {
  if (!envelope) return null;
  if (envelope.migracao_aplicada === false) {
    return (
      <Aviso tom="atencao" titulo="Migração não aplicada">
        O PostgreSQL do RAG ainda não tem as tabelas do Acervo. Aplique{" "}
        <code className="font-codigo">back/sql/011_acervo_juridico.sql</code> e rode{" "}
        <code className="font-codigo">python -m scripts.sincronizar_acervo --executar</code>. Até lá a geração de
        peças continua usando a carga antiga, sem versionamento.
      </Aviso>
    );
  }
  if (!envelope.disponivel) {
    return (
      <Aviso tom="critico" titulo="Banco do acervo indisponível">
        {envelope.erro || "Não foi possível ler o PostgreSQL do RAG."}
      </Aviso>
    );
  }
  return null;
}

/* ------------------------------------------------------------------ visão geral */

function VisaoGeral({ resumo }: { resumo: ResumoAcervo }) {
  const c = resumo.cartoes;
  const sinc = resumo.sincronizacao;
  const rag = resumo.saude_rag;
  if (!c || !sinc || !rag) return null;
  return (
    <div className="space-y-5">
      <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))] gap-3">
        <CartaoNumero icone={<Landmark size={14} aria-hidden />} rotulo="Normas" valor={numero(c.normas)} />
        <CartaoNumero icone={<ScrollText size={14} aria-hidden />} rotulo="Dispositivos vigentes" valor={numero(c.dispositivos_vigentes)} />
        <CartaoNumero icone={<FileClock size={14} aria-hidden />} rotulo="Revogados" valor={numero(c.revogados)} />
        <CartaoNumero icone={<History size={14} aria-hidden />} rotulo="Versões históricas" valor={numero(c.versoes_historicas)} />
        <CartaoNumero
          icone={<Gavel size={14} aria-hidden />}
          rotulo="Jurisprudência"
          valor={numero(c.jurisprudencia)}
          apoio={`${numero(c.jurisprudencia_aguardando)} aguardando verificação · ${numero(c.jurisprudencia_superada)} superadas`}
        />
        <CartaoNumero
          icone={<AlertTriangle size={14} aria-hidden />}
          rotulo="Alertas abertos"
          valor={numero(c.alertas_abertos)}
          apoio={c.alertas_altos ? `${numero(c.alertas_altos)} de severidade alta` : "nenhum de severidade alta"}
        />
      </div>

      <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,380px),1fr))] gap-5">
        <Cartao titulo="Atualização das leis" subtitulo="Como o acervo acompanha as fontes oficiais.">
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-tinta-3">Automática</dt>
            <dd className="m-0">
              {sinc.automatica ? (
                <Selo tom="ok" simbolo="✓">Ligada</Selo>
              ) : (
                <>
                  <Selo tom="neutro" simbolo="⊘">Desligada</Selo>
                  <span className="mt-1 block font-codigo text-xs text-tinta-3">ACERVO_SINCRONIZACAO_ATIVA=0</span>
                </>
              )}
            </dd>
            <dt className="text-tinta-3">Agenda</dt>
            <dd className="m-0 text-tinta-2">{sinc.agenda}</dd>
            <dt className="text-tinta-3">Próxima</dt>
            <dd className="m-0 text-tinta-2">{sinc.automatica ? quando(sinc.proxima) : "—"}</dd>
            <dt className="text-tinta-3">Última</dt>
            <dd className="m-0 text-tinta-2">
              {sinc.ultima ? `${sinc.ultima.document_id} · ${quando(sinc.ultima.iniciada_em)} · ${sinc.ultima.status}` : "nenhuma ainda"}
            </dd>
            <dt className="text-tinta-3">Fila</dt>
            <dd className="m-0 font-codigo text-tinta-2">{sinc.fila}</dd>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {(Object.keys(TOM_DA_COR) as CorAcervo[]).map((cor) => (
              <SeloStatus
                key={cor}
                selo={{
                  status: cor,
                  cor,
                  texto: `${{ verde: "Atualizado", amarelo: "Pendente", vermelho: "Erro", cinza: "Revogado", azul: "Em andamento" }[cor]}: ${resumo.normas_por_cor?.[cor] ?? 0}`,
                }}
              />
            ))}
          </div>
        </Cartao>

        <Cartao
          titulo="Saúde do RAG"
          subtitulo={`${numero(rag.chunks_com_embedding)} de ${numero(rag.chunks_com_embedding + rag.chunks_pendentes)} trechos com vetor · modelo ${rag.modelo_configurado || "não configurado"} (${rag.dimensoes_configuradas} dimensões)`}
        >
          <div className="mb-3">
            <Cobertura percentual={rag.cobertura_percentual} />
          </div>
          <ul className="m-0 list-none space-y-2 p-0">
            {rag.verificacoes.map((v) => (
              <li key={v.nome} className="flex items-start justify-between gap-3 border-b border-borda pb-2 last:border-b-0">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-tinta">{v.nome}</span>
                  <span className="block text-xs text-tinta-3 [overflow-wrap:anywhere]">{v.detalhe}</span>
                </span>
                <span className="shrink-0">
                  <SeloStatus selo={{ ...v.selo, texto: v.ok ? "OK" : v.selo.cor === "amarelo" ? "Atenção" : "Falha" }} />
                </span>
              </li>
            ))}
          </ul>
        </Cartao>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ legislação */

function ListaNormas({ onAbrir }: { onAbrir: (id: string) => void }) {
  const [busca, setBusca] = useState("");
  const [status, setStatus] = useState("");
  const [normas, setNormas] = useState<NormaAcervo[] | null>(null);
  const [envelope, setEnvelope] = useState<EnvelopeAcervo | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    const id = window.setTimeout(() => {
      normasDoAcervo({ busca, status })
        .then((r) => {
          if (!vivo) return;
          setEnvelope(r);
          setNormas(r.itens ?? []);
          setErro(null);
        })
        .catch((e) => vivo && setErro(mensagemDeErro(e, "Não foi possível carregar as normas.")));
    }, 250);
    return () => {
      vivo = false;
      window.clearTimeout(id);
    };
  }, [busca, status]);

  return (
    <Cartao titulo="Legislação" subtitulo="Normas do manifesto oficial. Clique para ver a árvore de dispositivos.">
      <div className="mb-4 grid grid-cols-[minmax(0,1fr)_220px] gap-3 max-[700px]:grid-cols-1">
        <Campo placeholder="Buscar por nome, número ou sigla…" value={busca} onChange={(e) => setBusca(e.target.value)} aria-label="Buscar norma" />
        <CampoSeletor value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrar por status">
          <option value="">Todos os status</option>
          <option value="ATUALIZADO">Atualizado</option>
          <option value="PENDENTE">Pendente</option>
          <option value="ERRO">Erro</option>
          <option value="EM_ANDAMENTO">Em andamento</option>
          <option value="REVOGADO">Revogado</option>
        </CampoSeletor>
      </div>
      <AvisoDeEnvelope envelope={envelope} />
      {erro && <Aviso tom="critico" titulo="Erro">{erro}</Aviso>}
      {normas && normas.length === 0 && <Vazio>Nenhuma norma com esse filtro.</Vazio>}
      {normas && normas.length > 0 && (
        <div className="max-w-full overflow-x-auto rounded-cartao border border-borda">
          <Tabela className="min-w-[860px]">
            <thead>
              <tr>
                {["Norma", "Status", "Artigos", "Revogados", "Versões antigas", "Embeddings", "Última verificação"].map((t) => (
                  <Th key={t}>{t}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {normas.map((n) => {
                const total = n.embeddings.chunks_com_embedding + n.embeddings.chunks_pendentes;
                return (
                  <TrZebra key={n.id} className="cursor-pointer hover:bg-acao-clara" onClick={() => onAbrir(n.id)}>
                    <Td>
                      <strong className="block">{n.nome}</strong>
                      <span className="text-xs text-tinta-3">{n.nome_oficial}</span>
                    </Td>
                    <Td>
                      <SeloStatus selo={n.selo} />
                      {n.ultimo_erro && <span className="mt-1 block max-w-[260px] truncate text-xs text-critico" title={n.ultimo_erro}>{n.ultimo_erro}</span>}
                    </Td>
                    <Td className="tabular-nums">{numero(n.artigos)}</Td>
                    <Td className="tabular-nums">{numero(n.revogados)}</Td>
                    <Td className="tabular-nums">{numero(n.versoes_historicas)}</Td>
                    <Td>
                      <Cobertura percentual={total ? Math.round((1000 * n.embeddings.chunks_com_embedding) / total) / 10 : 0} />
                    </Td>
                    <Td className="whitespace-nowrap">{quando(n.ultima_verificacao)}</Td>
                  </TrZebra>
                );
              })}
            </tbody>
          </Tabela>
        </div>
      )}
    </Cartao>
  );
}

function NoDaArvore({
  no,
  selecionado,
  onSelecionar,
  nivel,
}: {
  no: NoArvoreAcervo;
  selecionado: number | null;
  onSelecionar: (id: number) => void;
  nivel: number;
}) {
  const [aberto, setAberto] = useState(false);
  const ativo = selecionado === no.id;
  useEffect(() => {
    if (selecionado !== null && no.filhos.some(function contem(f): boolean { return f.id === selecionado || f.filhos.some(contem); })) setAberto(true);
  }, [selecionado, no.filhos]);
  return (
    <li>
      <div
        className={`flex items-center gap-1 rounded-[6px] py-[3px] pr-2 text-sm ${ativo ? "bg-acao-clara text-acao" : "hover:bg-papel-3"}`}
        style={{ paddingLeft: `${nivel * 16 + 4}px` }}
      >
        {no.filhos.length > 0 ? (
          <button
            type="button"
            className="grid size-5 shrink-0 place-items-center rounded text-tinta-3 hover:text-tinta"
            onClick={() => setAberto(!aberto)}
            aria-label={aberto ? `Recolher ${no.rotulo}` : `Expandir ${no.rotulo}`}
            aria-expanded={aberto}
          >
            {aberto ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}
        <button type="button" className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left" onClick={() => onSelecionar(no.id)}>
          <span className={`truncate ${no.tipo === "artigo" ? "font-semibold" : ""}`}>{no.rotulo}</span>
          {no.status !== "VIGENTE" && no.status !== "vigente" && (
            <span className="shrink-0">
              <SeloJuridico status={no.status} />
            </span>
          )}
        </button>
      </div>
      {aberto && no.filhos.length > 0 && (
        <ul className="m-0 list-none p-0">
          {no.filhos.map((f) => (
            <NoDaArvore key={f.id} no={f} selecionado={selecionado} onSelecionar={onSelecionar} nivel={nivel + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function PainelDispositivo({ versionId, onAnotado }: { versionId: number; onAnotado?: () => void }) {
  const [disp, setDisp] = useState<DispositivoAcervo | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [nota, setNota] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [versaoAberta, setVersaoAberta] = useState<number | null>(null);

  const carregar = useCallback(async () => {
    try {
      const r = await dispositivoDoAcervo(versionId);
      setDisp(r.dispositivo ?? null);
      setErro(r.disponivel ? null : r.erro || "Indisponível.");
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível carregar o dispositivo."));
    }
  }, [versionId]);

  useEffect(() => {
    setDisp(null);
    void carregar();
  }, [carregar]);

  async function anotar() {
    if (!disp || !nota.trim()) return;
    setSalvando(true);
    try {
      await anotarNoAcervo({ texto: nota.trim(), document_id: disp.document_id, dispositivo_id: disp.dispositivo_id });
      setNota("");
      await carregar();
      onAnotado?.();
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível salvar a anotação."));
    } finally {
      setSalvando(false);
    }
  }

  if (erro) return <Aviso tom="critico" titulo="Dispositivo">{erro}</Aviso>;
  if (!disp) return <Vazio>Carregando o dispositivo…</Vazio>;
  const emb = disp.embedding;
  const gate = disp.como_o_gate_ve;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-xs text-tinta-3">{(disp.hierarquia.ancestrais ?? []).join(" › ") || disp.norma}</p>
          <h3 className="m-0 font-titulo text-lg font-semibold text-tinta">
            {disp.rotulo} <span className="font-codigo text-xs font-normal text-tinta-3">{disp.dispositivo_id}</span>
          </h3>
        </div>
        <SeloJuridico status={disp.status} />
      </div>

      <div className="whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 p-3 text-sm leading-[1.6] text-tinta">{disp.texto}</div>

      <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(min(100%,200px),1fr))] gap-3 text-sm">
        <div>
          <dt className="text-xs text-tinta-3">Versão</dt>
          <dd className="m-0 text-tinta">v{disp.versao} · desde {quando(disp.valid_from)}{disp.valid_from_origem === "observado" ? " (data em que a fonte foi lida)" : ""}</dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-3">Última verificação</dt>
          <dd className="m-0 text-tinta">{quando(disp.ultima_verificacao)}</dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-3">Hash do texto</dt>
          <dd className="m-0 font-codigo text-xs text-tinta" title={disp.content_hash}>{hashCurto(disp.content_hash)}</dd>
        </div>
        <div>
          <dt className="text-xs text-tinta-3">Fonte oficial</dt>
          <dd className="m-0">
            {disp.url ? (
              <a href={disp.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-acao underline">
                abrir <ExternalLink size={12} aria-hidden />
              </a>
            ) : "—"}
          </dd>
        </div>
      </dl>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,260px),1fr))] gap-3">
        <div className="rounded-campo border border-borda p-3">
          <p className="m-0 mb-2 text-xs font-bold uppercase tracking-[0.06em] text-tinta-3">Embedding do artigo</p>
          {!emb ? (
            <Selo tom="atencao" simbolo="!">Sem trecho no RAG</Selo>
          ) : (
            <div className="space-y-1 text-sm">
              {emb.invalidado_em ? (
                <Selo tom="neutro" simbolo="⊘">Fora da busca desde {quando(emb.invalidado_em)}</Selo>
              ) : emb.tem_embedding ? (
                <Selo tom="ok" simbolo="✓">Vetor atual</Selo>
              ) : (
                <Selo tom="atencao" simbolo="!">Pendente de vetor</Selo>
              )}
              <p className="m-0 text-xs text-tinta-3">
                {emb.modelo ? `${emb.modelo} · ${emb.dimensoes} dimensões` : "modelo não registrado"} · gerado {quando(emb.gerado_em)}
              </p>
              <p className="m-0 font-codigo text-xs text-tinta-3" title={emb.content_hash ?? ""}>hash do trecho {hashCurto(emb.content_hash)}</p>
            </div>
          )}
        </div>
        <div className="rounded-campo border border-borda p-3">
          <p className="m-0 mb-2 text-xs font-bold uppercase tracking-[0.06em] text-tinta-3">Como o Citation Gate vê</p>
          <div className="space-y-1 text-sm">
            <p className="m-0 font-codigo text-xs text-tinta">{gate.chave} · {gate.authority_id}</p>
            <div className="flex flex-wrap gap-2">
              {gate.vigente_hoje ? <Selo tom="ok" simbolo="✓">Vigente hoje</Selo> : <Selo tom="critico" simbolo="✕">Não vigente hoje</Selo>}
              {gate.verificada ? (
                <Selo tom="ok" simbolo="✓">Verificação dentro da validade</Selo>
              ) : (
                <Selo tom="atencao" simbolo="!">Verificação vencida — o gate não aprova</Selo>
              )}
            </div>
          </div>
        </div>
      </div>

      <div>
        <p className="m-0 mb-2 text-xs font-bold uppercase tracking-[0.06em] text-tinta-3">Versões ({disp.versoes.length})</p>
        <ul className="m-0 list-none space-y-2 p-0">
          {disp.versoes.map((v) => (
            <li key={v.id} className="rounded-campo border border-borda">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
                onClick={() => setVersaoAberta(versaoAberta === v.id ? null : v.id)}
                aria-expanded={versaoAberta === v.id}
              >
                <span>
                  <strong>v{v.versao}</strong> · {quando(v.valid_from)} → {v.valid_until ? quando(v.valid_until) : "atual"}
                  <span className="ml-2 font-codigo text-xs text-tinta-3">{hashCurto(v.content_hash)}</span>
                </span>
                <SeloJuridico status={v.valid_until ? (v.status === "VIGENTE" ? "ALTERADA" : v.status) : v.status} />
              </button>
              {versaoAberta === v.id && (
                <div className="whitespace-pre-wrap border-t border-borda bg-papel-2 px-3 py-2 text-sm leading-[1.6]">{v.texto}</div>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <p className="m-0 mb-2 text-xs font-bold uppercase tracking-[0.06em] text-tinta-3">Anotações</p>
        {disp.anotacoes.length === 0 && <p className="m-0 mb-2 text-sm text-tinta-3">Nenhuma anotação.</p>}
        <ul className="m-0 mb-2 list-none space-y-2 p-0">
          {disp.anotacoes.map((a) => (
            <li key={a.id} className="rounded-campo border border-borda bg-papel-2 px-3 py-2 text-sm">
              {a.texto}
              <span className="mt-1 block text-xs text-tinta-3">{a.autor || "—"} · {quando(a.criado_em)}</span>
            </li>
          ))}
        </ul>
        <div className="flex gap-2">
          <Campo placeholder="Anotar (ex.: conferido com o DOU)" value={nota} onChange={(e) => setNota(e.target.value)} aria-label="Nova anotação" />
          <Botao variante="secundario" carregando={salvando} textoCarregando="Salvando…" disabled={!nota.trim()} onClick={() => void anotar()}>
            Anotar
          </Botao>
        </div>
      </div>
    </div>
  );
}

function agrupar(arvore: NoArvoreAcervo[]): { contexto: string; nos: NoArvoreAcervo[] }[] {
  const grupos: { contexto: string; nos: NoArvoreAcervo[] }[] = [];
  for (const no of arvore) {
    const contexto = (no.contexto ?? []).join(" › ");
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.contexto === contexto) ultimo.nos.push(no);
    else grupos.push({ contexto, nos: [no] });
  }
  return grupos;
}

function DetalheNorma({
  documentId,
  versaoInicial,
  config,
  onVoltar,
}: {
  documentId: string;
  versaoInicial: number | null;
  config: ConfiguracaoAcervo | null;
  onVoltar: () => void;
}) {
  const [norma, setNorma] = useState<NormaDetalhe | null>(null);
  const [envelope, setEnvelope] = useState<EnvelopeAcervo | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [selecionado, setSelecionado] = useState<number | null>(versaoInicial);
  const [filtro, setFiltro] = useState("");
  const [acao, setAcao] = useState<"verificar" | "reindexar" | null>(null);
  const [mensagem, setMensagem] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const r = await normaDoAcervo(documentId);
      setEnvelope(r);
      setNorma(r.norma ?? null);
      setErro(null);
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível carregar a norma."));
    }
  }, [documentId]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const grupos = useMemo(() => {
    if (!norma) return [];
    const f = filtro.trim().toLowerCase().replace(/^art\.?\s*/, "");
    const nos = f
      ? norma.arvore.filter((n) => n.rotulo.toLowerCase().includes(f) || n.dispositivo_id.toLowerCase().includes(f))
      : norma.arvore;
    return agrupar(nos);
  }, [norma, filtro]);

  async function executar(tipo: "verificar" | "reindexar") {
    const pergunta =
      tipo === "verificar"
        ? `Verificar ${norma?.nome} agora na fonte oficial? Só o que mudou ganha versão e embedding novos.`
        : `Reindexar ${norma?.nome}? Todos os ${numero(norma?.artigos)} artigos terão o embedding refeito — isso tem custo de API.`;
    if (!window.confirm(pergunta)) return;
    setAcao(tipo);
    setMensagem(null);
    try {
      await (tipo === "verificar" ? verificarNormaAgora(documentId) : reindexarNorma(documentId));
      setMensagem(tipo === "verificar" ? "Verificação enfileirada. Acompanhe em Atualizações." : "Reindexação enfileirada.");
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível enfileirar."));
    } finally {
      setAcao(null);
    }
  }

  const acoesLigadas = !!config?.sincronizacao_ativa;
  return (
    <div className="space-y-5">
      <Botao variante="texto" onClick={onVoltar} className="inline-flex items-center gap-2">
        <ArrowLeft size={16} aria-hidden />
        Voltar para a legislação
      </Botao>
      <AvisoDeEnvelope envelope={envelope} />
      {erro && <Aviso tom="critico" titulo="Erro">{erro}</Aviso>}
      {mensagem && <Aviso tom="ok" titulo="Pronto">{mensagem}</Aviso>}
      {!norma && !erro && <Vazio>Carregando a norma…</Vazio>}
      {norma && (
        <>
          <Cartao>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="m-0 text-xs font-bold uppercase tracking-[0.1em] text-tinta-3">{norma.tipo} · {norma.orgao}</p>
                <h2 className="m-0 font-titulo text-xl font-semibold text-tinta">{norma.nome}</h2>
                <p className="m-0 mt-1 text-sm text-tinta-3">{norma.nome_oficial}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <SeloStatus selo={norma.selo} />
                  {norma.desatualizada && norma.ultima_verificacao && <Selo tom="atencao" simbolo="!">Sem verificação recente</Selo>}
                </div>
                {norma.ultimo_erro && <p className="m-0 mt-2 text-sm text-critico">{norma.ultimo_erro}</p>}
              </div>
              <div className="flex flex-col items-end gap-2">
                <div className="flex gap-2">
                  <Botao
                    variante="primario"
                    pequeno
                    disabled={!acoesLigadas}
                    carregando={acao === "verificar"}
                    textoCarregando="Enfileirando…"
                    onClick={() => void executar("verificar")}
                  >
                    <RefreshCcw size={14} aria-hidden />
                    Verificar agora
                  </Botao>
                  <Botao
                    variante="perigo"
                    pequeno
                    disabled={!acoesLigadas}
                    carregando={acao === "reindexar"}
                    textoCarregando="Enfileirando…"
                    onClick={() => void executar("reindexar")}
                  >
                    Reindexar
                  </Botao>
                </div>
                {!acoesLigadas && (
                  <span className="max-w-[300px] text-right text-xs text-tinta-3">
                    Ações desligadas: a sincronização está desativada neste ambiente (ACERVO_SINCRONIZACAO_ATIVA=0).
                  </span>
                )}
              </div>
            </div>
            <dl className="m-0 mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(100%,170px),1fr))] gap-3 text-sm">
              {[
                ["Artigos", numero(norma.artigos)],
                ["Dispositivos", numero(norma.dispositivos)],
                ["Revogados", numero(norma.revogados)],
                ["Versões antigas", numero(norma.versoes_historicas)],
                ["Última verificação", quando(norma.ultima_verificacao)],
                ["Última alteração", quando(norma.ultima_atualizacao)],
                ["Próxima verificação", acoesLigadas ? quando(norma.proxima_verificacao) : "—"],
                ["Encoding", norma.encoding || "—"],
              ].map(([k, v]) => (
                <div key={k} className="rounded-campo border border-borda bg-papel-2 px-3 py-2">
                  <dt className="text-xs text-tinta-3">{k}</dt>
                  <dd className="m-0 font-semibold tabular-nums text-tinta">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="m-0 mt-3 text-xs text-tinta-3">
              Hash do documento <span className="font-codigo" title={norma.content_hash}>{hashCurto(norma.content_hash)}</span> · parser {norma.parser || "—"} ·{" "}
              {norma.url && (
                <a href={norma.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-acao underline">
                  {norma.fonte || "fonte oficial"} <ExternalLink size={11} aria-hidden />
                </a>
              )}
            </p>
          </Cartao>

          <div className="grid min-w-0 grid-cols-[minmax(280px,380px)_minmax(0,1fr)] items-start gap-5 max-[1000px]:grid-cols-1">
            <Cartao titulo="Dispositivos" subtitulo={`${numero(norma.arvore.length)} artigos na redação atual`} className="min-w-0">
              <Campo placeholder="Ir para artigo (ex.: 482)" value={filtro} onChange={(e) => setFiltro(e.target.value)} aria-label="Filtrar artigos" />
              <div className="mt-3 max-h-[640px] overflow-y-auto pr-1">
                {grupos.length === 0 && <Vazio>Nenhum artigo encontrado.</Vazio>}
                {grupos.map((g, i) => (
                  <div key={`${g.contexto}-${i}`} className="mb-2">
                    {g.contexto && (
                      <p className="sticky top-0 z-[1] m-0 bg-papel py-1 text-[11px] font-bold uppercase tracking-[0.05em] text-tinta-3">{g.contexto}</p>
                    )}
                    <ul className="m-0 list-none p-0">
                      {g.nos.map((no) => (
                        <NoDaArvore key={no.id} no={no} selecionado={selecionado} onSelecionar={setSelecionado} nivel={0} />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Cartao>
            <Cartao className="min-w-0">
              {selecionado ? (
                <PainelDispositivo versionId={selecionado} />
              ) : (
                <Vazio>Escolha um dispositivo na árvore para ver o texto atual, as versões, o embedding e o hash.</Vazio>
              )}
            </Cartao>
          </div>

          {norma.alertas.length > 0 && (
            <Cartao titulo="Alertas desta norma">
              <ListaAlertas alertas={norma.alertas} onResolvido={() => void carregar()} />
            </Cartao>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ jurisprudência */

function ListaJurisprudencia({ destaque }: { destaque: string | null }) {
  const [busca, setBusca] = useState("");
  const [itens, setItens] = useState<JurisprudenciaAcervo[] | null>(null);
  const [envelope, setEnvelope] = useState<EnvelopeAcervo | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [importando, setImportando] = useState(false);
  const [json, setJson] = useState("");
  const [resultado, setResultado] = useState<string | null>(null);
  const [mostrarImportacao, setMostrarImportacao] = useState(false);

  const carregar = useCallback(async () => {
    try {
      const r = await jurisprudenciaDoAcervo({ busca });
      setEnvelope(r);
      setItens(r.itens ?? []);
      setErro(null);
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível carregar a jurisprudência."));
    }
  }, [busca]);

  useEffect(() => {
    const id = window.setTimeout(() => void carregar(), 250);
    return () => window.clearTimeout(id);
  }, [carregar]);

  async function importar() {
    let lista: unknown;
    try {
      lista = JSON.parse(json);
    } catch {
      setErro("O conteúdo não é um JSON válido.");
      return;
    }
    if (!Array.isArray(lista) || lista.length === 0) {
      setErro("O JSON deve ser uma lista de súmulas/OJs.");
      return;
    }
    if (!window.confirm(`Importar ${lista.length} item(ns)? Tudo entra como "aguardando verificação".`)) return;
    setImportando(true);
    setResultado(null);
    try {
      const r = await importarJurisprudencia(lista);
      setResultado(`${r.novas} novas · ${r.alteradas} alteradas · ${r.inalteradas} sem mudança · ${r.superadas} superadas`);
      setJson("");
      await carregar();
    } catch (e) {
      const dados = e instanceof ApiError ? (e.dados as { detail?: { mensagem?: string; invalidos?: { item: number; erro: string }[] } }) : null;
      const invalidos = dados?.detail?.invalidos;
      setErro(invalidos ? `${dados?.detail?.mensagem} ${invalidos.map((i) => `item ${i.item}: ${i.erro}`).join("; ")}` : mensagemDeErro(e, "Falha na importação."));
    } finally {
      setImportando(false);
    }
  }

  return (
    <Cartao
      titulo="Jurisprudência"
      subtitulo="Súmulas, OJs e súmulas vinculantes. O que não é coletado automaticamente entra por importação e fica aguardando verificação."
    >
      <div className="mb-4 flex flex-wrap gap-3">
        <Campo className="min-w-[240px] flex-1" placeholder="Buscar por número, tribunal ou texto…" value={busca} onChange={(e) => setBusca(e.target.value)} aria-label="Buscar jurisprudência" />
        <Botao variante="secundario" onClick={() => setMostrarImportacao(!mostrarImportacao)}>
          {mostrarImportacao ? "Fechar importação" : "Importar JSON"}
        </Botao>
      </div>
      {mostrarImportacao && (
        <div className="mb-4 space-y-2 rounded-campo border border-borda bg-papel-2 p-3">
          <p className="m-0 text-xs text-tinta-3">
            Lista de objetos com <code className="font-codigo">tipo</code>, <code className="font-codigo">tribunal</code>,{" "}
            <code className="font-codigo">numero</code>, <code className="font-codigo">texto</code>, <code className="font-codigo">status</code>,{" "}
            <code className="font-codigo">fonte_oficial</code> e <code className="font-codigo">url</code> (obrigatórios: fonte oficial e URL).
          </p>
          <Campo area value={json} onChange={(e) => setJson(e.target.value)} placeholder='[{"tipo": "sumula", "tribunal": "TST", "numero": "…", …}]' aria-label="JSON da importação" />
          <Botao variante="primario" pequeno carregando={importando} textoCarregando="Importando…" disabled={!json.trim()} onClick={() => void importar()}>
            Importar
          </Botao>
        </div>
      )}
      <AvisoDeEnvelope envelope={envelope} />
      {erro && <Aviso tom="critico" titulo="Erro">{erro}</Aviso>}
      {resultado && <Aviso tom="ok" titulo="Importado">{resultado}</Aviso>}
      {itens && itens.length === 0 && <Vazio>Nenhuma súmula ou OJ no acervo ainda.</Vazio>}
      {itens && itens.length > 0 && (
        <div className="max-w-full overflow-x-auto rounded-cartao border border-borda">
          <Tabela className="min-w-[860px]">
            <thead>
              <tr>
                {["Título", "Situação jurídica", "Verificação", "Sucessora", "Última verificação", "Fonte"].map((t) => (
                  <Th key={t}>{t}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {itens.map((j) => (
                <TrZebra key={j.id} className={destaque === j.id ? "outline outline-2 outline-acao" : ""}>
                  <Td className="min-w-[260px]">
                    <strong className="block">{j.titulo}</strong>
                    <span className="line-clamp-2 text-xs text-tinta-3">{j.texto}</span>
                  </Td>
                  <Td>
                    {["superado", "cancelado", "revogado"].includes(j.status_juridico) ? (
                      <Selo tom="neutro" simbolo="⊘">{j.status_juridico}</Selo>
                    ) : j.status_juridico === "suspenso" ? (
                      <Selo tom="atencao" simbolo="!">suspenso</Selo>
                    ) : (
                      <Selo tom="ok" simbolo="✓">vigente</Selo>
                    )}
                  </Td>
                  <Td><SeloStatus selo={j.selo.status === "REVOGADO" ? { ...j.selo, texto: "Inativa" } : j.selo} /></Td>
                  <Td className="font-codigo text-xs">{j.superado_por || "—"}</Td>
                  <Td className="whitespace-nowrap">{quando(j.ultima_verificacao)}</Td>
                  <Td>
                    {j.url ? (
                      <a href={j.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-acao underline">
                        {j.fonte || "abrir"} <ExternalLink size={11} aria-hidden />
                      </a>
                    ) : "—"}
                  </Td>
                </TrZebra>
              ))}
            </tbody>
          </Tabela>
        </div>
      )}
    </Cartao>
  );
}

/* ------------------------------------------------------------------ embeddings */

function Embeddings({ resumo }: { resumo: ResumoAcervo }) {
  const [normas, setNormas] = useState<NormaAcervo[] | null>(null);
  useEffect(() => {
    normasDoAcervo().then((r) => setNormas(r.itens ?? [])).catch(() => setNormas([]));
  }, []);
  const rag = resumo.saude_rag;
  return (
    <Cartao
      titulo="Embeddings"
      subtitulo="Um vetor por artigo. Só é refeito quando o texto do artigo muda; trecho de redação antiga ou revogada sai da busca."
    >
      {rag && (
        <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))] gap-3">
          <CartaoNumero icone={<Boxes size={14} aria-hidden />} rotulo="Com vetor" valor={numero(rag.chunks_com_embedding)} />
          <CartaoNumero icone={<Boxes size={14} aria-hidden />} rotulo="Pendentes" valor={numero(rag.chunks_pendentes)} apoio="fora da busca até ganhar vetor" />
          <CartaoNumero icone={<Boxes size={14} aria-hidden />} rotulo="Invalidados" valor={numero(rag.chunks_invalidados)} apoio="redação antiga ou revogada" />
          <CartaoNumero
            icone={<Boxes size={14} aria-hidden />}
            rotulo="Modelo"
            valor={rag.modelo_configurado || "—"}
            apoio={`${rag.dimensoes_configuradas} dimensões · no banco: ${rag.modelos_no_banco.join(", ") || "sem registro"}`}
          />
        </div>
      )}
      {normas && (
        <div className="max-w-full overflow-x-auto rounded-cartao border border-borda">
          <Tabela className="min-w-[760px]">
            <thead>
              <tr>
                {["Norma", "Trechos", "Com vetor", "Pendentes", "Invalidados", "Cobertura"].map((t) => (
                  <Th key={t}>{t}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {normas.map((n) => {
                const ativos = n.embeddings.chunks_com_embedding + n.embeddings.chunks_pendentes;
                return (
                  <TrZebra key={n.id}>
                    <Td><strong>{n.nome}</strong></Td>
                    <Td className="tabular-nums">{numero(n.embeddings.chunks)}</Td>
                    <Td className="tabular-nums">{numero(n.embeddings.chunks_com_embedding)}</Td>
                    <Td className="tabular-nums">{numero(n.embeddings.chunks_pendentes)}</Td>
                    <Td className="tabular-nums">{numero(n.embeddings.chunks_invalidados)}</Td>
                    <Td><Cobertura percentual={ativos ? Math.round((1000 * n.embeddings.chunks_com_embedding) / ativos) / 10 : 0} /></Td>
                  </TrZebra>
                );
              })}
            </tbody>
          </Tabela>
        </div>
      )}
    </Cartao>
  );
}

/* ------------------------------------------------------------------ atualizações e alertas */

function ListaAlertas({ alertas, onResolvido }: { alertas: AlertaAcervo[]; onResolvido: () => void }) {
  const [resolvendo, setResolvendo] = useState<number | null>(null);
  async function resolver(a: AlertaAcervo) {
    if (!window.confirm(`Marcar como resolvido: "${a.titulo}"?`)) return;
    setResolvendo(a.id);
    try {
      await resolverAlertaDoAcervo(a.id);
      onResolvido();
    } finally {
      setResolvendo(null);
    }
  }
  if (alertas.length === 0) return <Vazio>Nenhum alerta aberto.</Vazio>;
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {alertas.map((a) => {
        const sev = SEVERIDADE[a.severidade] ?? SEVERIDADE.media;
        return (
          <li key={a.id} className="flex flex-wrap items-start justify-between gap-3 rounded-campo border border-borda px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <Selo tom={sev.tom} simbolo={sev.simbolo}>{sev.texto}</Selo>
                <span className="font-codigo text-xs text-tinta-3">{a.tipo}</span>
                <span className="text-xs text-tinta-3">{quando(a.criado_em)}</span>
              </span>
              <span className="mt-1 block text-sm font-semibold text-tinta">{a.titulo}</span>
              {a.detalhe && <span className="block text-xs text-tinta-3">{a.detalhe}</span>}
            </span>
            <Botao variante="secundario" pequeno carregando={resolvendo === a.id} textoCarregando="Resolvendo…" onClick={() => void resolver(a)}>
              Resolver
            </Botao>
          </li>
        );
      })}
    </ul>
  );
}

function Atualizacoes() {
  const [sincs, setSincs] = useState<SincronizacaoAcervo[] | null>(null);
  const [alertas, setAlertas] = useState<AlertaAcervo[]>([]);
  const carregar = useCallback(async () => {
    const [s, a] = await Promise.all([sincronizacoesDoAcervo(), alertasDoAcervo()]);
    setSincs(s.itens ?? []);
    setAlertas(a.itens ?? []);
  }, []);
  useEffect(() => {
    void carregar().catch(() => setSincs([]));
  }, [carregar]);

  const SELO_SINC: Record<string, SeloAcervo> = {
    ATUALIZADO: { status: "ATUALIZADO", cor: "verde", texto: "Alterações gravadas" },
    SEM_ALTERACAO: { status: "SEM_ALTERACAO", cor: "verde", texto: "Sem alteração" },
    ERRO: { status: "ERRO", cor: "vermelho", texto: "Erro" },
    EM_ANDAMENTO: { status: "EM_ANDAMENTO", cor: "azul", texto: "Em andamento" },
  };

  return (
    <div className="space-y-5">
      <Cartao titulo="Alertas abertos" subtitulo="Dispositivo alterado ou revogado, súmula superada, fonte fora do ar, skill citando norma antiga.">
        <ListaAlertas alertas={alertas} onResolvido={() => void carregar()} />
      </Cartao>
      <Cartao titulo="Sincronizações" subtitulo="Cada leitura da fonte oficial: o que mudou, quanto custou em embeddings e quanto demorou.">
        {sincs && sincs.length === 0 && <Vazio>Nenhuma sincronização registrada.</Vazio>}
        {sincs && sincs.length > 0 && (
          <div className="max-w-full overflow-x-auto rounded-cartao border border-borda">
            <Tabela className="min-w-[980px]">
              <thead>
                <tr>
                  {["Norma", "Início", "Status", "Novos", "Alterados", "Revogados", "Removidos", "Vetores (gerados/mantidos/fora)", "~Tokens", "Duração", "Origem"].map((t) => (
                    <Th key={t}>{t}</Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sincs.map((s) => (
                  <TrZebra key={s.id}>
                    <Td><strong>{s.document_id}</strong></Td>
                    <Td className="whitespace-nowrap">{quando(s.iniciada_em)}</Td>
                    <Td>
                      <SeloStatus selo={SELO_SINC[s.status] ?? { status: s.status, cor: "amarelo", texto: s.status }} />
                      {s.erro && <span className="mt-1 block max-w-[220px] truncate text-xs text-critico" title={s.erro}>{s.erro}</span>}
                    </Td>
                    <Td className="tabular-nums">{numero(s.dispositivos_novos)}</Td>
                    <Td className="tabular-nums">{numero(s.dispositivos_alterados)}</Td>
                    <Td className="tabular-nums">{numero(s.dispositivos_revogados)}</Td>
                    <Td className="tabular-nums">{numero(s.dispositivos_removidos)}</Td>
                    <Td className="tabular-nums">
                      {numero(s.embeddings_gerados)} / {numero(s.embeddings_mantidos)} / {numero(s.embeddings_invalidados)}
                    </Td>
                    <Td className="tabular-nums">{numero(s.tokens_embeddings_aprox)}</Td>
                    <Td className="tabular-nums">{s.duracao_ms != null ? `${(s.duracao_ms / 1000).toLocaleString("pt-BR")} s` : "—"}</Td>
                    <Td>{s.origem}{s.solicitado_por ? ` · ${s.solicitado_por}` : ""}</Td>
                  </TrZebra>
                ))}
              </tbody>
            </Tabela>
          </div>
        )}
      </Cartao>
    </div>
  );
}

function Problemas({ onAbrirNorma }: { onAbrirNorma: (id: string) => void }) {
  const [itens, setItens] = useState<ProblemaAcervo[] | null>(null);
  useEffect(() => {
    problemasDoAcervo().then((r) => setItens(r.itens ?? [])).catch(() => setItens([]));
  }, []);
  return (
    <Cartao titulo="Problemas" subtitulo="O que impede o acervo de servir como fonte confiável, do mais grave ao mais leve.">
      {itens && itens.length === 0 && <Vazio>Nenhum problema encontrado.</Vazio>}
      <ul className="m-0 list-none space-y-2 p-0">
        {(itens ?? []).map((p, i) => {
          const sev = SEVERIDADE[p.severidade] ?? SEVERIDADE.media;
          return (
            <li key={`${p.tipo}-${p.norma}-${i}`} className="flex flex-wrap items-center justify-between gap-3 rounded-campo border border-borda px-3 py-2">
              <span className="flex min-w-0 flex-wrap items-center gap-2">
                <Selo tom={sev.tom} simbolo={sev.simbolo}>{sev.texto}</Selo>
                <span className="font-codigo text-xs text-tinta-3">{p.tipo}</span>
                <span className="text-sm text-tinta">{p.titulo}</span>
              </span>
              {p.norma && (
                <Botao variante="texto" onClick={() => onAbrirNorma(p.norma)}>
                  abrir norma
                </Botao>
              )}
            </li>
          );
        })}
      </ul>
    </Cartao>
  );
}

/* ------------------------------------------------------------------ tela */

export default function AcervoJuridico({ onVoltar }: { onVoltar: () => void }) {
  const [aba, setAba] = useState<Aba>("geral");
  const [resumo, setResumo] = useState<ResumoAcervo | null>(null);
  const [config, setConfig] = useState<ConfiguracaoAcervo | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [normaAberta, setNormaAberta] = useState<{ id: string; versao: number | null } | null>(null);
  const [destaqueJuris, setDestaqueJuris] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const [r, c] = await Promise.all([resumoDoAcervo(), configuracaoDoAcervo()]);
      setResumo(r);
      setConfig(c);
      setErro(null);
    } catch (e) {
      setErro(mensagemDeErro(e, "Não foi possível carregar o acervo."));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  /* Link do trace da peça (`?autoridade=ndv:123`): abre direto o dispositivo ou a súmula citada. */
  useEffect(() => {
    const busca = new URLSearchParams(window.location.search);
    const autoridade = busca.get("autoridade");
    if (!autoridade) return;
    busca.delete("autoridade");
    window.history.replaceState(null, "", `${window.location.pathname}?${busca.toString()}`);
    resolverAutoridadeDoAcervo(autoridade)
      .then((r) => {
        const destino = r.destino;
        if (destino?.tipo === "dispositivo") {
          setAba("legislacao");
          setNormaAberta({ id: destino.document_id, versao: destino.version_id });
        } else if (destino?.tipo === "jurisprudencia") {
          setAba("jurisprudencia");
          setDestaqueJuris(destino.authority_id);
        } else {
          setErro(`A autoridade ${autoridade} não está no acervo.`);
        }
      })
      .catch((e) => setErro(mensagemDeErro(e, "Não foi possível abrir a autoridade citada.")));
  }, []);

  function abrirNorma(id: string) {
    setAba("legislacao");
    setNormaAberta({ id, versao: null });
  }

  return (
    <div className="min-w-0 space-y-6">
      <Botao variante="texto" onClick={onVoltar} className="inline-flex items-center gap-2">
        <ArrowLeft size={16} aria-hidden />
        Voltar para a carteira
      </Botao>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-2 mt-0 font-ui text-xs font-bold uppercase tracking-[0.12em] text-tinta-3">Escritório</p>
          <h1 className="m-0 mb-[6px] flex items-center gap-2 font-titulo text-xl font-semibold text-tinta">
            <BookOpenCheck size={20} aria-hidden />
            Acervo Jurídico
          </h1>
          <p className="m-0 max-w-[75ch] leading-[1.5] text-tinta-3">
            As leis, súmulas e precedentes que a IA usa para fundamentar as peças: a versão vigente de cada artigo, o
            histórico de redações, os embeddings da busca e os alertas de atualização.
          </p>
        </div>
        <Botao variante="secundario" pequeno carregando={carregando} textoCarregando="Atualizando…" onClick={() => void carregar()}>
          <RefreshCcw size={14} aria-hidden />
          Atualizar
        </Botao>
      </header>

      {erro && <Aviso tom="critico" titulo="Atenção">{erro}</Aviso>}
      <AvisoDeEnvelope envelope={resumo} />
      {config?.armazenamento === "json-local" && (
        <Aviso tom="info" titulo="Acervo local de desenvolvimento">
          Lendo de um arquivo JSON (ACERVO_ARMAZENAMENTO_JSON), não do pgvector.
        </Aviso>
      )}

      <BarraAbas aria-label="Seções do acervo">
        {ABAS.map((a) => (
          <BotaoAba
            key={a.id}
            ativa={aba === a.id}
            onClick={() => {
              setAba(a.id);
              if (a.id !== "legislacao") setNormaAberta(null);
            }}
          >
            {a.rotulo}
          </BotaoAba>
        ))}
      </BarraAbas>

      {carregando && !resumo && <p className="m-0 text-tinta-3">Carregando…</p>}

      {resumo?.migracao_aplicada && (
        <>
          {aba === "geral" && <VisaoGeral resumo={resumo} />}
          {aba === "legislacao" &&
            (normaAberta ? (
              <DetalheNorma
                key={`${normaAberta.id}-${normaAberta.versao ?? ""}`}
                documentId={normaAberta.id}
                versaoInicial={normaAberta.versao}
                config={config}
                onVoltar={() => setNormaAberta(null)}
              />
            ) : (
              <ListaNormas onAbrir={abrirNorma} />
            ))}
          {aba === "jurisprudencia" && <ListaJurisprudencia destaque={destaqueJuris} />}
          {aba === "embeddings" && <Embeddings resumo={resumo} />}
          {aba === "atualizacoes" && <Atualizacoes />}
          {aba === "problemas" && <Problemas onAbrirNorma={abrirNorma} />}
        </>
      )}
    </div>
  );
}
