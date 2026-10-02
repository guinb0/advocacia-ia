"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Copy, ExternalLink } from "lucide-react";

import SugestoesDeAcao from "@/components/atendimento/SugestoesDeAcao";
import { Aviso, Botao, Campo, RotuloCampo, Selo } from "@/components/ui/Basicos";
import {
  confirmarAcoesAtendimento,
  concluirQualificacaoAtendimento,
  enviarAvaliacaoAtendimento,
  finalizarAtendimento,
  iniciarAnaliseAtendimento,
  obterAnaliseAtendimento,
  obterAvaliacaoAtendimento,
  seguirParaAnalise,
  type AcaoConfirmada,
  type AnaliseAtendimento,
  type Atendimento,
  type CasoDoAtendimento,
  type EntradaAnalise,
  type EstadoAtendimento,
  type EstadoAvaliacao,
} from "@/lib/api/atendimentos";
import { formatarTelefone } from "@/lib/formato";
import type { Categoria } from "@/lib/types";

/* O que vem depois da entrevista, guiado pelo estado que o servidor guarda.
 *
 * A tela não decide em que etapa está: pergunta ao atendimento. Recarregar a
 * aba, abrir em outra máquina ou clicar duas vezes cai na mesma etapa — e a
 * criação dos casos é idempotente no servidor. */

const ETAPAS: { estado: EstadoAtendimento[]; rotulo: string }[] = [
  { estado: ["ENTREVISTA_FINALIZADA", "ANALISE_JURIDICA"], rotulo: "Análise jurídica" },
  { estado: ["AGUARDANDO_CONFIRMACAO_ACOES"], rotulo: "Ações" },
  { estado: ["QUALIFICACAO"], rotulo: "Qualificação" },
  { estado: ["AVALIACAO_ESCRITORIO"], rotulo: "Avaliação" },
  { estado: ["DOCUMENTACAO_PENDENTE", "CONCLUIDA"], rotulo: "Documentação" },
];

const INTERVALO_ANALISE_MS = 3_000;
const INTERVALO_AVALIACAO_MS = 6_000;

const ROTULO_AVALIACAO: Record<EstadoAvaliacao["status"], { texto: string; tom: "neutro" | "info" | "ok" | "critico" }> = {
  pendente: { texto: "não enviada", tom: "neutro" },
  enviado: { texto: "enviada", tom: "info" },
  entregue: { texto: "entregue", tom: "ok" },
  lido: { texto: "lida", tom: "ok" },
  falhou: { texto: "falhou", tom: "critico" },
};

function Passos({ estado }: { estado: EstadoAtendimento }) {
  const atual = ETAPAS.findIndex((e) => e.estado.includes(estado));
  return (
    <ol className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Etapas do pós-entrevista">
      {ETAPAS.map((etapa, i) => (
        <li
          key={etapa.rotulo}
          aria-current={i === atual ? "step" : undefined}
          className={`rounded-pill border px-3 py-1 text-xs font-semibold ${
            i < atual
              ? "border-ok-borda bg-ok-claro text-ok"
              : i === atual
                ? "border-acao bg-acao text-white"
                : "border-borda bg-papel-2 text-tinta-3"
          }`}
        >
          {i < atual ? "✓ " : `${i + 1}. `}
          {etapa.rotulo}
        </li>
      ))}
    </ol>
  );
}

function CasosCriados({
  casos,
  portais,
  onAbrirCaso,
}: {
  casos: CasoDoAtendimento[];
  portais: Record<string, CasoDoAtendimento["portal"]>;
  onAbrirCaso?: (casoId: string) => void;
}) {
  const [copiado, setCopiado] = useState<string | null>(null);
  if (!casos.length) return null;
  const copiar = (id: string, texto: string) => {
    void navigator.clipboard?.writeText(texto).then(() => {
      setCopiado(id);
      window.setTimeout(() => setCopiado(null), 1500);
    });
  };
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {casos.map((caso) => {
        const portal = portais[caso.id];
        const url = portal?.url ?? caso.portal_url;
        return (
          <li key={caso.id} className="rounded-campo border border-borda bg-papel px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="text-sm text-tinta">{caso.acao || caso.categoria}</strong>
              <div className="flex flex-wrap gap-1">
                {caso.rascunho_ia && <Selo tom="atencao">Gerado por IA — requer revisão</Selo>}
                <Selo tom="neutro">{caso.origem === "manual" ? "manual" : caso.origem === "triagem" ? "triagem" : "IA"}</Selo>
              </div>
            </div>
            {url && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-tinta-2">
                <span className="truncate">Portal: {url}</span>
                <button type="button" className="inline-flex items-center gap-1 text-acao" onClick={() => copiar(caso.id, url)}>
                  <Copy aria-hidden className="size-3" /> {copiado === caso.id ? "copiado" : "copiar"}
                </button>
              </div>
            )}
            {portal?.senha && (
              <div className="mt-1 text-xs text-tinta-2">
                Senha: <strong className="font-mono text-tinta">{portal.senha}</strong>{" "}
                <span className="text-atencao">— {portal.aviso}</span>
              </div>
            )}
            {onAbrirCaso && (
              <Botao variante="texto" className="mt-1" onClick={() => onAbrirCaso(caso.id)}>
                Abrir caso <ExternalLink aria-hidden className="size-3" />
              </Botao>
            )}
          </li>
        );
      })}
    </ul>
  );
}

interface Props {
  atendimentoId: string;
  categorias: Categoria[];
  /** O que vai para a análise — lido na hora, para pegar a cauda da conversa. */
  montarEntrada: () => EntradaAnalise;
  /** Formulário de cadastro; `aoConfirmar` avança a etapa de qualificação. */
  renderCadastro: (aoConfirmar: () => void, ocupado: boolean) => ReactNode;
  /** Grava entrevista, qualificação e vínculos em cada caso criado. */
  onQualificar: (casos: CasoDoAtendimento[]) => Promise<Record<string, unknown> | null>;
  telefoneInicial?: string;
  cliente?: string;
  onAbrirCaso?: (casoId: string) => void;
}

export default function FluxoPosEntrevista({
  atendimentoId,
  categorias,
  montarEntrada,
  renderCadastro,
  onQualificar,
  telefoneInicial = "",
  cliente = "",
  onAbrirCaso,
}: Props) {
  const [atendimento, setAtendimento] = useState<Atendimento | null>(null);
  const [analise, setAnalise] = useState<AnaliseAtendimento | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [portais, setPortais] = useState<Record<string, CasoDoAtendimento["portal"]>>({});
  const [avaliacao, setAvaliacao] = useState<EstadoAvaliacao | null>(null);
  const [telefone, setTelefone] = useState(formatarTelefone(telefoneInicial));
  const iniciou = useRef(false);
  const entrada = useRef(montarEntrada);
  entrada.current = montarEntrada;

  const estado = atendimento?.estado;

  const atualizar = useCallback(async () => {
    const r = await obterAnaliseAtendimento(atendimentoId);
    setAtendimento(r.atendimento);
    setAnalise(r.analise);
    return r;
  }, [atendimentoId]);

  const comecarAnalise = useCallback(
    async (refazer = false) => {
      setErro(null);
      try {
        const r = await iniciarAnaliseAtendimento(atendimentoId, { ...entrada.current(), refazer });
        setAnalise(r.analise);
        setAtendimento(r.atendimento);
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não foi possível iniciar a análise.");
      }
    },
    [atendimentoId],
  );

  useEffect(() => {
    let vivo = true;
    void (async () => {
      try {
        let r = await atualizar();
        if (!vivo) return;
        if (r.atendimento.estado === "ENTREVISTA_FINALIZADA") {
          await seguirParaAnalise(atendimentoId, false);
          r = await atualizar();
        }
        if (!iniciou.current && r.atendimento.estado === "ANALISE_JURIDICA" && (!r.analise || r.analise.status === "falhou")) {
          iniciou.current = true;
          await comecarAnalise();
        }
      } catch (e) {
        if (vivo) setErro(e instanceof Error ? e.message : "Não foi possível carregar o atendimento.");
      }
    })();
    return () => {
      vivo = false;
    };
  }, [atendimentoId, atualizar, comecarAnalise]);

  const analisando = estado === "ANALISE_JURIDICA" && (!analise || analise.status === "pendente" || analise.status === "processando");
  useEffect(() => {
    if (!analisando) return;
    const t = window.setInterval(() => void atualizar().catch(() => undefined), INTERVALO_ANALISE_MS);
    return () => window.clearInterval(t);
  }, [analisando, atualizar]);

  useEffect(() => {
    if (estado !== "AVALIACAO_ESCRITORIO") return;
    let vivo = true;
    const ler = () =>
      void obterAvaliacaoAtendimento(atendimentoId)
        .then((a) => vivo && setAvaliacao(a))
        .catch(() => undefined);
    ler();
    const t = window.setInterval(ler, INTERVALO_AVALIACAO_MS);
    return () => {
      vivo = false;
      window.clearInterval(t);
    };
  }, [estado, atendimentoId]);

  async function executar<T>(acao: () => Promise<T>, mensagem: string): Promise<T | null> {
    setOcupado(true);
    setErro(null);
    try {
      return await acao();
    } catch (e) {
      setErro(e instanceof Error ? e.message : mensagem);
      return null;
    } finally {
      setOcupado(false);
    }
  }

  const confirmarAcoes = (acoes: AcaoConfirmada[], documentos: string[]) =>
    void executar(async () => {
      const r = await confirmarAcoesAtendimento(atendimentoId, {
        acoes,
        documentos_declarados: documentos,
        cliente,
        telefone: telefoneInicial,
      });
      const novos = Object.fromEntries(r.casos.filter((c) => c.portal).map((c) => [c.id, c.portal]));
      setPortais((atual) => ({ ...atual, ...novos }));
      setAtendimento(r.atendimento);
    }, "Não foi possível criar os casos.");

  const qualificar = () =>
    void executar(async () => {
      const casos = atendimento?.casos ?? [];
      const dados = await onQualificar(casos);
      setAtendimento(await concluirQualificacaoAtendimento(atendimentoId, dados));
    }, "Não foi possível concluir a qualificação.");

  const enviarAvaliacao = (forcar: boolean) =>
    void executar(async () => {
      const r = await enviarAvaliacaoAtendimento(atendimentoId, telefone, forcar);
      setAvaliacao(r.avaliacao);
      if (!r.enviado && r.status !== "ja_enviado") {
        setErro(r.motivo || `Envio não realizado (${r.status}).`);
      }
    }, "Não foi possível enviar o link de avaliação.");

  const finalizar = (pular: boolean) => {
    if (pular && !window.confirm("Finalizar sem enviar o link de avaliação do Google?")) return;
    void executar(async () => {
      setAtendimento(await finalizarAtendimento(atendimentoId, pular));
    }, "Não foi possível finalizar o atendimento.");
  };

  if (!atendimento) {
    return (
      <div className="mt-6">
        {erro ? (
          <Aviso tom="critico" titulo="Atendimento indisponível">
            {erro}{" "}
            <Botao variante="texto" onClick={() => void atualizar().catch(() => undefined)}>
              Tentar de novo
            </Botao>
          </Aviso>
        ) : (
          <Aviso tom="neutro" titulo="Carregando o atendimento…" />
        )}
      </div>
    );
  }

  const casos = atendimento.casos ?? [];
  const docs = atendimento.documentos;

  return (
    <div className="mt-6 space-y-4" id="fluxo-pos-entrevista">
      <Passos estado={atendimento.estado} />
      {erro && <Aviso tom="critico" titulo="Algo não deu certo">{erro}</Aviso>}

      {(estado === "ANALISE_JURIDICA" || estado === "ENTREVISTA_FINALIZADA") && (
        <section className="rounded-cartao border border-borda-forte bg-papel p-5 shadow-cartao">
          <h3 className="m-0 text-lg font-semibold text-tinta">Análise jurídica em andamento</h3>
          <p className="mb-0 mt-1 max-w-[70ch] text-sm leading-[1.6] text-tinta-2">
            Cruzando a entrevista com os tipos de caso, os critérios e o acervo jurídico. As sugestões aparecem aqui sozinhas.
          </p>
          {analise?.status === "falhou" ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Aviso tom="atencao" titulo="A análise falhou">{analise.erro || "Tente de novo."}</Aviso>
              <Botao variante="primario" onClick={() => void comecarAnalise(true)}>
                Tentar novamente
              </Botao>
            </div>
          ) : (
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-papel-3" aria-label="Analisando">
              <i className="block h-full w-1/3 animate-pulse rounded-full bg-acao" />
            </div>
          )}
          {!analise && !analisando && (
            <Botao variante="secundario" className="mt-3" onClick={() => void comecarAnalise()}>
              Iniciar análise
            </Botao>
          )}
        </section>
      )}

      {estado === "AGUARDANDO_CONFIRMACAO_ACOES" && (
        <SugestoesDeAcao
          key={analise?.id ?? "sem-analise"}
          analise={analise}
          categorias={categorias}
          confirmando={ocupado}
          onConfirmar={confirmarAcoes}
          onRefazer={() => void comecarAnalise(true)}
        />
      )}

      {estado === "QUALIFICACAO" && (
        <>
          <section className="rounded-cartao border border-ok-borda bg-ok-claro p-4">
            <strong className="text-sm text-tinta">
              {casos.length > 1 ? `${casos.length} casos criados` : "Caso criado"} — envie o link e a senha ao cliente.
            </strong>
            <div className="mt-2">
              <CasosCriados casos={casos} portais={portais} />
            </div>
          </section>
          {renderCadastro(qualificar, ocupado)}
        </>
      )}

      {estado === "AVALIACAO_ESCRITORIO" && (
        <section className="rounded-cartao border border-borda-forte bg-papel p-5 shadow-cartao">
          <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-acao">Avaliação do escritório</span>
          <h3 className="mt-1 text-lg font-semibold text-tinta">Link de avaliação no Google</h3>
          <p className="mb-0 mt-1 max-w-[70ch] text-sm leading-[1.6] text-tinta-2">
            Peça ao cliente, ainda na chamada, que avalie o escritório. O link vai pelo WhatsApp e o status é acompanhado aqui.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div className="min-w-[220px]">
              <RotuloCampo htmlFor="telefone-avaliacao">WhatsApp do cliente</RotuloCampo>
              <Campo
                id="telefone-avaliacao"
                inputMode="tel"
                value={telefone}
                placeholder="(DDD) 00000-0000"
                onChange={(e) => setTelefone(formatarTelefone(e.target.value))}
              />
            </div>
            {avaliacao && avaliacao.status !== "pendente" ? (
              <Botao variante="secundario" onClick={() => enviarAvaliacao(true)} carregando={ocupado}>
                Reenviar link
              </Botao>
            ) : (
              <Botao variante="primario" onClick={() => enviarAvaliacao(false)} carregando={ocupado} disabled={!telefone.trim()}>
                Enviar link de avaliação
              </Botao>
            )}
            <span className="pb-2">
              <Selo tom={ROTULO_AVALIACAO[avaliacao?.status ?? "pendente"].tom}>
                Avaliação {ROTULO_AVALIACAO[avaliacao?.status ?? "pendente"].texto}
              </Selo>
            </span>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-borda pt-4">
            <Botao
              variante="primario"
              onClick={() => finalizar(false)}
              disabled={!avaliacao || avaliacao.status === "pendente"}
              carregando={ocupado}
            >
              Finalizar atendimento
            </Botao>
            <Botao variante="discreto" onClick={() => finalizar(true)} disabled={ocupado}>
              Finalizar sem avaliação
            </Botao>
            <span className="text-xs text-tinta-3">Ao finalizar, a equipe de Documentação é avisada.</span>
          </div>
        </section>
      )}

      {(estado === "DOCUMENTACAO_PENDENTE" || estado === "CONCLUIDA") && (
        <section className="rounded-cartao border border-ok-borda bg-papel p-5 shadow-cartao">
          <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-ok">Atendimento finalizado</span>
          <h3 className="mt-1 text-lg font-semibold text-tinta">
            {estado === "CONCLUIDA" ? "A Documentação já assumiu" : "A equipe de Documentação foi avisada"}
          </h3>
          <div className="mt-3">
            <CasosCriados casos={casos} portais={portais} onAbrirCaso={onAbrirCaso} />
          </div>
          {docs && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div>
                <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-ok">Disponíveis</span>
                <ul className="m-0 mt-1 pl-[18px] text-xs leading-[1.55] text-tinta-2">
                  {docs.disponiveis.length ? docs.disponiveis.map((d) => <li key={`${d.nome}-${d.origem}`}>{d.nome}</li>) : <li>Nenhum</li>}
                </ul>
              </div>
              <div>
                <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-atencao">Faltantes</span>
                <ul className="m-0 mt-1 pl-[18px] text-xs leading-[1.55] text-tinta-2">
                  {docs.faltantes.length ? docs.faltantes.map((d) => <li key={`${d.nome}-${d.origem}`}>{d.nome}</li>) : <li>Nenhum</li>}
                </ul>
              </div>
            </div>
          )}
        </section>
      )}

      {(estado === "CANCELADA" || estado === "CLIENTE_FALTOU") && (
        <Aviso tom="atencao" titulo="Atendimento encerrado">
          Este atendimento está como {estado === "CANCELADA" ? "cancelado" : "falta do cliente"}.
        </Aviso>
      )}
    </div>
  );
}
