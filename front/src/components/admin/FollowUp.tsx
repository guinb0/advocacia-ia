"use client";

/**
 * Relatório de follow-up: clientes com documento obrigatório pendente, com nome,
 * telefone, o que falta e o alerta de quando é preciso LIGAR (o WhatsApp
 * automático não está resolvendo). Retrato operacional para o atendimento —
 * não é ranking de cliente. Ver `carteira.relatorio_follow_up`.
 *
 * A TELA É UMA FILA DE TRABALHO, NÃO UMA TABELA DE CONSULTA.
 *
 * A versão anterior mostrava tudo numa tabela de seis colunas. Funcionava para
 * ler, mas quem usa isto não vem consultar: vem trabalhar a fila de cima para
 * baixo, ligando cliente por cliente. Daí o formato atual — lista priorizada à
 * esquerda, cliente selecionado à direita — que mantém o próximo da fila e o
 * detalhe de quem está sendo atendido na mesma tela, sem modal no meio do
 * caminho.
 *
 * O que a tela NÃO faz, de propósito: marcar documento como recebido. O desenho
 * previa caixas de seleção ali, mas não existe rota que registre isso — caixa
 * que não persiste é pior que ausência dela, porque some no F5 sem avisar. A
 * lista de pendências é leitura; quem recebe documento usa o dossiê do caso.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { History, MessageCircle, Phone, RefreshCw, Search } from "lucide-react";

import {
  callHistory,
  registerCall,
  relatorioFollowUp,
  type Call,
  type ClienteFollowUp,
  type RelatorioFollowUp,
} from "@/lib/api";
import {
  Aviso,
  BarraAbas,
  Botao,
  BotaoAba,
  Campo,
  CampoSeletor,
  LinkBotao,
  Selo,
  Vazio,
} from "@/components/ui/Basicos";

/* "ligados" existe porque a fila os ESCONDIA.
 *
 * Registrar a ligação tira o caso da aba "Ligar" — é o objetivo —, mas antes ele
 * não reaparecia em lugar nenhum reconhecível: sumia da fila e, em "Todos", o
 * cartão não dizia que alguém já tinha ligado nem quando. Quem trabalhou a fila
 * de manhã não conseguia ver à tarde o que já tinha feito. */
type Filtro = "ligar" | "ligados" | "sem_telefone" | "todos";
type Ordem = "parado" | "faltantes" | "nome";

export default function FollowUp() {
  const [dados, setDados] = useState<RelatorioFollowUp | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [filtro, setFiltro] = useState<Filtro>("ligar");
  const [busca, setBusca] = useState("");
  const [ordem, setOrdem] = useState<Ordem>("parado");
  const [histories, setHistories] = useState<Record<string, Call[]>>({});
  const [openCaseId, setOpenCaseId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState<string | null>(null);
  const [historyErrors, setHistoryErrors] = useState<Record<string, string>>({});
  const [confirmingCaseId, setConfirmingCaseId] = useState<string | null>(null);
  const [confirmationErrors, setConfirmationErrors] = useState<Record<string, string>>({});

  const recarregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await relatorioFollowUp());
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível carregar o relatório.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  useEffect(() => {
    if (!openCaseId) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenCaseId(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [openCaseId]);

  const clientes = useMemo(() => dados?.clientes ?? [], [dados]);
  const semTelefone = useMemo(() => clientes.filter((c) => !c.telefone).length, [clientes]);
  const jaLigados = useMemo(() => clientes.filter((c) => c.ultima_ligacao).length, [clientes]);

  /* A média entra na terceira caixa do topo. Só dos que TÊM pendência — que é a
   * lista inteira aqui —, e arredondada: "12,4 dias parado" sugere uma precisão
   * que o dado (dias corridos) não tem. */
  const diasParadoMedio = useMemo(() => {
    if (clientes.length === 0) return 0;
    const soma = clientes.reduce((total, c) => total + (c.dias_parado || 0), 0);
    return Math.round(soma / clientes.length);
  }, [clientes]);

  const lista = useMemo(() => {
    const termo = busca.trim().toLocaleLowerCase();
    const filtrada = clientes.filter((c) => {
      if (filtro === "ligar" && !c.precisa_ligar) return false;
      if (filtro === "ligados" && !c.ultima_ligacao) return false;
      if (filtro === "sem_telefone" && c.telefone) return false;
      if (!termo) return true;
      // Busca por cliente OU por documento: quem procura "CNIS" quer ver de quem
      // está faltando o CNIS, não precisa lembrar o nome de ninguém.
      return (
        c.cliente.toLocaleLowerCase().includes(termo) ||
        c.documentos_faltantes.some((doc) => doc.toLocaleLowerCase().includes(termo))
      );
    });
    const ordenada = [...filtrada];
    if (ordem === "parado") ordenada.sort((a, b) => b.dias_parado - a.dias_parado);
    if (ordem === "faltantes") ordenada.sort((a, b) => b.faltantes_total - a.faltantes_total);
    if (ordem === "nome") ordenada.sort((a, b) => a.cliente.localeCompare(b.cliente, "pt-BR"));
    return ordenada;
  }, [clientes, filtro, busca, ordem]);

  const selectedClient = clientes.find((client) => client.caso_id === openCaseId) ?? null;

  async function openHistory(casoId: string) {
    setOpenCaseId(casoId);
    if (histories[casoId] || loadingHistory === casoId) {
      return;
    }
    setLoadingHistory(casoId);
    setHistoryErrors((current) => ({ ...current, [casoId]: "" }));
    try {
      const history = await callHistory(casoId);
      setHistories((current) => ({ ...current, [casoId]: history.calls }));
    } catch (e) {
      setHistoryErrors((current) => ({
        ...current,
        [casoId]: e instanceof Error ? e.message : "Não foi possível carregar o histórico.",
      }));
    } finally {
      setLoadingHistory(null);
    }
  }

  async function confirmCall(casoId: string) {
    if (confirmingCaseId) {
      return;
    }
    setConfirmingCaseId(casoId);
    setConfirmationErrors((current) => ({ ...current, [casoId]: "" }));
    try {
      const call = await registerCall(casoId);
      setHistories((current) => (
        current[casoId]
          ? { ...current, [casoId]: [call, ...current[casoId]] }
          : current
      ));
      await recarregar();
    } catch (e) {
      setConfirmationErrors((current) => ({
        ...current,
        [casoId]: e instanceof Error ? e.message : "Não foi possível registrar a ligação.",
      }));
    } finally {
      setConfirmingCaseId(null);
    }
  }

  return (
    <div className="grid min-w-0 gap-5">
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-5">
        <div className="min-w-0 max-w-[62ch]">
          <h1 className="m-0 font-titulo text-[1.75rem] font-semibold leading-[1.15] text-tinta">
            Documentos pendentes
          </h1>
          <p className="mt-2 mb-0 text-sm leading-[1.55] text-tinta-3">
            Fila de trabalho dos clientes com documento obrigatório em falta. A prioridade
            sobe quando o follow-up por WhatsApp não está resolvendo.
          </p>
        </div>
        {dados && (
          <div className="flex flex-none flex-wrap gap-2">
            <Indicador rotulo="Com pendência" valor={dados.total} />
            <Indicador rotulo="Precisam ligar" valor={dados.precisam_ligar} destaque />
            <Indicador rotulo="Dias parado (méd.)" valor={diasParadoMedio} />
          </div>
        )}
      </header>

      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <BarraAbas role="tablist" aria-label="Filtro da fila">
          <BotaoAba ativa={filtro === "ligar"} onClick={() => setFiltro("ligar")}>
            Precisa ligar <span className="tabular-nums opacity-70">{dados?.precisam_ligar ?? 0}</span>
          </BotaoAba>
          <BotaoAba ativa={filtro === "ligados"} onClick={() => setFiltro("ligados")}>
            Já ligados <span className="tabular-nums opacity-70">{jaLigados}</span>
          </BotaoAba>
          <BotaoAba ativa={filtro === "sem_telefone"} onClick={() => setFiltro("sem_telefone")}>
            Sem telefone <span className="tabular-nums opacity-70">{semTelefone}</span>
          </BotaoAba>
          <BotaoAba ativa={filtro === "todos"} onClick={() => setFiltro("todos")}>
            Todos <span className="tabular-nums opacity-70">{dados?.total ?? 0}</span>
          </BotaoAba>
        </BarraAbas>

        <div className="relative ml-auto min-w-[220px] flex-1 sm:max-w-[320px]">
          <Search
            size={16}
            strokeWidth={2}
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3"
          />
          <Campo
            className="min-h-10 pl-9 text-sm"
            type="search"
            value={busca}
            aria-label="Buscar cliente ou documento"
            placeholder="Buscar cliente ou documento"
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>

        <CampoSeletor
          className="min-h-10 w-auto text-sm"
          value={ordem}
          aria-label="Ordem da fila"
          onChange={(e) => setOrdem(e.target.value as Ordem)}
        >
          <option value="parado">Ordem: mais parado</option>
          <option value="faltantes">Ordem: mais documentos</option>
          <option value="nome">Ordem: nome</option>
        </CampoSeletor>

        <Botao variante="secundario" pequeno onClick={() => void recarregar()} disabled={carregando}>
          <RefreshCw size={14} strokeWidth={2} aria-hidden />
          {carregando ? "Atualizando…" : "Atualizar"}
        </Botao>
      </div>

      {dados?.regra && (
        <p className="m-0 border-l-[3px] border-acao-borda bg-acao-clara px-4 py-3 text-[13px] leading-[1.55] text-tinta-2">
          <strong className="text-tinta">Comece pelo topo.</strong> A fila está ordenada por
          urgência — clique num cliente para ver o que falta e o histórico de ligações.{" "}
          <span className="text-tinta-3">
            {dados.regra} {dados.aviso}
          </span>
        </p>
      )}

      {erro ? (
        <Aviso tom="critico" titulo="Erro">{erro}</Aviso>
      ) : carregando && !dados ? (
        <Vazio>Carregando o relatório…</Vazio>
      ) : lista.length === 0 ? (
        <Vazio>
          {busca.trim()
            ? `Nenhum cliente encontrado para “${busca.trim()}”.`
            : filtro === "ligar"
              ? "Nenhum cliente precisa de ligação agora."
              : filtro === "ligados"
                ? "Nenhuma ligação registrada ainda."
                : filtro === "sem_telefone"
                  ? "Todo cliente com pendência tem telefone cadastrado."
                  : "Nenhum cliente com pendência agora."}
        </Vazio>
      ) : (
        <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
          <ol className="m-0 grid list-none gap-3 p-0">
            {lista.map((cliente, indice) => (
              <ItemDaFila
                key={cliente.caso_id}
                cliente={cliente}
                posicao={indice + 1}
                selecionado={cliente.caso_id === openCaseId}
                registrando={confirmingCaseId === cliente.caso_id}
                bloqueado={confirmingCaseId !== null}
                erroConfirmacao={confirmationErrors[cliente.caso_id]}
                onSelecionar={() => void openHistory(cliente.caso_id)}
                onLigar={() => void confirmCall(cliente.caso_id)}
              />
            ))}
          </ol>

          <PainelDoCliente
            cliente={selectedClient}
            calls={selectedClient ? histories[selectedClient.caso_id] : undefined}
            carregandoHistorico={loadingHistory === selectedClient?.caso_id}
            erroHistorico={selectedClient ? historyErrors[selectedClient.caso_id] : undefined}
            erroConfirmacao={selectedClient ? confirmationErrors[selectedClient.caso_id] : undefined}
            registrando={confirmingCaseId === selectedClient?.caso_id}
            bloqueado={confirmingCaseId !== null}
            onLigar={() => selectedClient && void confirmCall(selectedClient.caso_id)}
          />
        </div>
      )}
    </div>
  );
}

/** Um cliente na fila. O cartão inteiro seleciona; "Ligar agora" registra a ligação.
 *
 * Os dois são irmãos, nunca aninhados: botão dentro de botão é HTML inválido e o
 * clique no de dentro sobe para o de fora, registrando ligação sem querer. */
function ItemDaFila({
  cliente,
  posicao,
  selecionado,
  registrando,
  bloqueado,
  erroConfirmacao,
  onSelecionar,
  onLigar,
}: {
  cliente: ClienteFollowUp;
  posicao: number;
  selecionado: boolean;
  registrando: boolean;
  bloqueado: boolean;
  erroConfirmacao?: string;
  onSelecionar: () => void;
  onLigar: () => void;
}) {
  const mostrados = cliente.documentos_faltantes.slice(0, 3);
  const restantes = cliente.faltantes_total - mostrados.length;

  return (
    <li
      className={
        "overflow-hidden rounded-cartao border bg-papel transition-[border-color,box-shadow] duration-150 " +
        (selecionado
          ? "border-acao shadow-[0_0_0_3px_var(--acao-clara)]"
          : "border-borda-forte hover:border-borda-campo")
      }
    >
      <div className="flex min-w-0 flex-wrap items-stretch">
        <button
          type="button"
          aria-pressed={selecionado}
          onClick={onSelecionar}
          className={
            "min-w-0 flex-1 cursor-pointer border-0 bg-transparent p-4 text-left " +
            "border-l-[3px] " +
            (cliente.precisa_ligar ? "border-l-critico" : "border-l-transparent") +
            " focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-foco"
          }
        >
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <span
              className="grid size-6 flex-none place-items-center rounded-campo bg-papel-3 font-codigo text-[11px] font-semibold tabular-nums text-tinta-2"
              aria-label={`Posição ${posicao} na fila`}
            >
              {posicao}
            </span>
            <strong className="min-w-0 font-titulo text-base font-semibold text-tinta [overflow-wrap:anywhere]">
              {cliente.cliente || "Cliente sem nome"}
            </strong>
            {cliente.telefone ? (
              <span className="rounded-pill border border-borda bg-papel-2 px-[10px] py-[2px] font-codigo text-xs tabular-nums text-tinta-2">
                {cliente.telefone}
              </span>
            ) : (
              <Selo tom="critico" simbolo="!">sem telefone</Selo>
            )}
          </div>

          <p className="mt-2 mb-0 text-[13px] leading-[1.5] text-tinta-2">
            Parado há <strong className="tabular-nums text-tinta">{cliente.dias_parado}</strong>{" "}
            {cliente.dias_parado === 1 ? "dia" : "dias"} · faltam{" "}
            <strong className="tabular-nums text-tinta">{cliente.faltantes_total}</strong>{" "}
            {cliente.faltantes_total === 1 ? "documento" : "documentos"}
            {mostrados.length > 0 ? ":" : "."}
          </p>

          {mostrados.length > 0 && (
            <ul className="mt-2 flex list-none flex-wrap gap-[6px] p-0">
              {mostrados.map((documento) => (
                <li
                  key={documento}
                  className="max-w-full truncate rounded-pill border border-borda bg-papel-2 px-[10px] py-[3px] text-xs text-tinta-2"
                  title={documento}
                >
                  {documento}
                </li>
              ))}
              {restantes > 0 && (
                <li className="rounded-pill px-1 py-[3px] text-xs tabular-nums text-tinta-3">
                  +{restantes}
                </li>
              )}
            </ul>
          )}
        </button>

        <div className="flex min-w-[190px] flex-none flex-col justify-center gap-2 border-l border-borda bg-papel-2 p-4">
          {cliente.precisa_ligar ? (
            <>
              <span className="text-xs font-semibold text-critico">Ligar para o cliente</span>
              {cliente.motivo_ligacao && (
                <span className="text-xs leading-[1.45] text-tinta-3">{cliente.motivo_ligacao}</span>
              )}
            </>
          ) : cliente.ultima_ligacao ? (
            /* O que a fila escondia: houve ligação, quem fez e quando. Antes o
              * cartão caía no selo genérico "no prazo" e o trabalho já feito
              * ficava invisível. */
            <>
              <Selo tom="ok">
                {cliente.dias_desde_ligacao === 0
                  ? "ligado hoje"
                  : cliente.dias_desde_ligacao === 1
                    ? "ligado ontem"
                    : cliente.dias_desde_ligacao != null
                      ? `ligado há ${cliente.dias_desde_ligacao} dias`
                      : "ligado"}
              </Selo>
              <span className="text-xs leading-[1.45] text-tinta-3">
                por {cliente.ultima_ligacao.atendente_nome || "atendente não identificado"}
              </span>
            </>
          ) : (
            <Selo tom={cliente.follow_up_ativo ? "ok" : "neutro"}>
              {cliente.follow_up_ativo ? "follow-up ativo" : "no prazo"}
            </Selo>
          )}

          <Botao
            variante={cliente.precisa_ligar ? "primario" : "secundario"}
            pequeno
            className="justify-center whitespace-nowrap"
            disabled={bloqueado}
            onClick={onLigar}
          >
            <Phone size={14} strokeWidth={2} aria-hidden />
            {registrando ? "Registrando…" : "Ligar agora"}
          </Botao>

          {erroConfirmacao && (
            <span className="text-[11px] leading-[1.4] text-critico">{erroConfirmacao}</span>
          )}
        </div>
      </div>
    </li>
  );
}

/** O cliente selecionado: o que falta, os botões de contato e o histórico.
 *
 * Substitui o modal de histórico — a fila continua visível ao lado, então quem
 * acaba de ligar já enxerga o próximo sem fechar nada. */
function PainelDoCliente({
  cliente,
  calls,
  carregandoHistorico,
  erroHistorico,
  erroConfirmacao,
  registrando,
  bloqueado,
  onLigar,
}: {
  cliente: ClienteFollowUp | null;
  calls: Call[] | undefined;
  carregandoHistorico: boolean;
  erroHistorico: string | undefined;
  erroConfirmacao: string | undefined;
  registrando: boolean;
  bloqueado: boolean;
  onLigar: () => void;
}) {
  if (!cliente) {
    return (
      <aside className="rounded-cartao border border-borda-forte bg-papel-2 p-5 lg:sticky lg:top-4">
        <p className="m-0 text-sm leading-[1.55] text-tinta-3">
          Clique num cliente da fila para ver o que falta, registrar a ligação e abrir o
          histórico de contatos.
        </p>
      </aside>
    );
  }

  return (
    <aside className="grid gap-4 rounded-cartao border border-borda-forte bg-papel p-5 lg:sticky lg:top-4">
      <div className="min-w-0">
        <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.12em] text-tinta-3">
          Cliente selecionado
        </p>
        <h2 className="mt-1 mb-0 font-titulo text-xl font-semibold leading-[1.2] text-tinta [overflow-wrap:anywhere]">
          {cliente.cliente || "Cliente sem nome"}
        </h2>
        <p className="mt-1 mb-0 font-codigo text-sm tabular-nums text-tinta-2">
          {cliente.telefone || <span className="font-ui text-critico">sem telefone cadastrado</span>}
        </p>
        {cliente.motivo_ligacao && (
          <p className="mt-2 mb-0 text-[13px] leading-[1.5] text-tinta-3">{cliente.motivo_ligacao}</p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Botao
          variante="primario"
          className="flex-1 justify-center whitespace-nowrap"
          disabled={bloqueado}
          onClick={onLigar}
        >
          <Phone size={15} strokeWidth={2} aria-hidden />
          {registrando ? "Registrando…" : "Registrar ligação"}
        </Botao>
        {cliente.telefone && (
          <LinkBotao
            variante="secundario"
            className="whitespace-nowrap"
            href={linkWhatsapp(cliente.telefone)}
            target="_blank"
            rel="noreferrer"
          >
            <MessageCircle size={15} strokeWidth={2} aria-hidden />
            WhatsApp
          </LinkBotao>
        )}
      </div>

      {erroConfirmacao && <Aviso tom="critico" titulo="Erro">{erroConfirmacao}</Aviso>}

      <section className="border-t border-borda pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="m-0 text-[11px] font-semibold uppercase tracking-[0.12em] text-tinta-3">
            O que falta chegar
          </h3>
          <span className="font-codigo text-xs tabular-nums text-tinta-3">
            {cliente.faltantes_total} pendente{cliente.faltantes_total === 1 ? "" : "s"}
          </span>
        </div>
        {cliente.documentos_faltantes.length === 0 ? (
          <p className="mt-2 mb-0 text-sm text-tinta-3">Nenhum documento obrigatório em falta.</p>
        ) : (
          <ul className="mt-3 grid list-none gap-2 p-0">
            {cliente.documentos_faltantes.map((documento) => (
              <li key={documento} className="flex items-start gap-2 text-sm leading-[1.45] text-tinta-2">
                <span className="mt-[6px] size-[6px] flex-none rounded-full bg-atencao-marca" aria-hidden />
                <span className="min-w-0 [overflow-wrap:anywhere]">{documento}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="border-t border-borda pt-4">
        <h3 className="m-0 mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-tinta-3">
          <History size={14} strokeWidth={2} aria-hidden />
          Ligações registradas
        </h3>
        {carregandoHistorico ? (
          <p className="m-0 text-sm text-tinta-3">Carregando histórico…</p>
        ) : erroHistorico ? (
          <Aviso tom="critico" titulo="Não foi possível abrir o histórico">{erroHistorico}</Aviso>
        ) : !calls || calls.length === 0 ? (
          <p className="m-0 text-sm text-tinta-3">Nenhuma ligação registrada para este cliente.</p>
        ) : (
          <ol className="m-0 grid list-none gap-2 p-0">
            {calls.map((call) => (
              <li
                key={call.id}
                className="rounded-campo border border-borda bg-papel-2 px-3 py-2"
              >
                <strong className="block text-[13px] font-semibold text-tinta">
                  {call.atendente_nome}
                </strong>
                <time
                  className="mt-[2px] block font-codigo text-xs tabular-nums text-tinta-3"
                  dateTime={call.realizada_em}
                >
                  {formatDateTime(call.realizada_em)}
                </time>
              </li>
            ))}
          </ol>
        )}
      </section>
    </aside>
  );
}

/** `wa.me` exige só dígitos e com DDI. O número do cadastro vem mascarado, e sem
 *  DDI quando é brasileiro — daí a normalização antes de montar o link. */
function linkWhatsapp(telefone: string): string {
  const digitos = telefone.replace(/\D/g, "");
  const comDdi = digitos.length <= 11 ? `55${digitos}` : digitos;
  return `https://wa.me/${comDdi}`;
}

function formatDateTime(value: string): string {
  const data = new Date(value);
  if (Number.isNaN(data.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(data);
}

function Indicador({ rotulo, valor, destaque }: { rotulo: string; valor: number; destaque?: boolean }) {
  return (
    <div
      className={
        "min-w-[124px] rounded-cartao border px-4 py-3 " +
        (destaque ? "border-atencao-borda bg-atencao-claro" : "border-borda-forte bg-papel")
      }
    >
      <strong
        className={
          "block font-titulo text-[1.6rem] font-semibold leading-none tabular-nums " +
          (destaque ? "text-atencao" : "text-tinta")
        }
      >
        {valor}
      </strong>
      <span className="mt-[6px] block text-[11px] font-semibold uppercase tracking-[0.08em] text-tinta-3">
        {rotulo}
      </span>
    </div>
  );
}
