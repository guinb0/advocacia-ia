"use client";

import { useEffect, useState } from "react";

import {
  Aviso,
  Botao,
  Campo,
  CampoSeletor,
  Cartao,
  Selo,
  Vazio,
} from "@/components/ui/Basicos";
import {
  buscarAlertasMovimentacao,
  buscarOperacao,
  type AlertaMovimentacao,
  type ColaboradorOperacional,
  type DirecaoOrdem,
  type OrdemEquipe,
  type PainelOperacao,
} from "@/lib/operacao";

function dataHora(valor: string | null): string {
  if (!valor) return "não informada";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(data);
}

export default function Operacao() {
  const [dados, setDados] = useState<PainelOperacao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [pagina, setPagina] = useState(1);
  const [ordem, setOrdem] = useState<OrdemEquipe>("entrevistas");
  const [direcao, setDirecao] = useState<DirecaoOrdem>("desc");

  async function carregar() {
    setCarregando(true);
    try {
      setDados(
        await buscarOperacao({ busca: buscaAplicada, pagina, ordem, direcao }),
      );
      setErro(null);
    } catch (falha) {
      setErro(
        falha instanceof Error
          ? falha.message
          : "Não foi possível carregar a operação.",
      );
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    void carregar();
  }, [buscaAplicada, pagina, ordem, direcao]);

  function filtrar(evento: React.FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const proximaBusca = busca.trim();
    setPagina(1);
    if (proximaBusca === buscaAplicada) {
      void carregar();
      return;
    }
    setBuscaAplicada(proximaBusca);
  }

  function limparBusca() {
    setBusca("");
    setPagina(1);
    if (!buscaAplicada) {
      void carregar();
      return;
    }
    setBuscaAplicada("");
  }

  function ordenar(campo: OrdemEquipe) {
    setPagina(1);
    if (campo === ordem) {
      setDirecao(direcao === "asc" ? "desc" : "asc");
      return;
    }
    setOrdem(campo);
    setDirecao(campo === "colaborador" ? "asc" : "desc");
  }

  function inverterDirecao() {
    setPagina(1);
    setDirecao(direcao === "asc" ? "desc" : "asc");
  }

  return (
    <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="m-0 font-titulo text-xl font-bold text-tinta">
            Operação da equipe
          </h1>
          <Botao
            variante="secundario"
            pequeno
            disabled={carregando}
            onClick={() => void carregar()}
          >
            {carregando ? "Atualizando..." : "Atualizar"}
          </Botao>
        </div>
        <p className="m-0 max-w-[70ch] text-base leading-[1.55] text-tinta-2">
          Acompanhe o volume registrado, as entrevistas em curso e os pontos que
          ainda precisam de conferência.
        </p>
      </header>

      {erro && (
        <Aviso tom="critico" titulo="A operação não pôde ser carregada">
          {erro}
        </Aviso>
      )}
      {carregando && !dados && (
        <Vazio>Carregando os registros operacionais...</Vazio>
      )}

      {dados && (
        <>
          <section
            aria-label="Resumo da operação"
            className="grid grid-cols-2 gap-3 lg:grid-cols-4"
          >
            <Indicador
              destaque
              rotulo="Em atendimento"
              valor={dados.resumo.em_atividade}
            />
            <Indicador rotulo="Entrevistas" valor={dados.resumo.entrevistas} />
            <Indicador rotulo="Ligações" valor={dados.resumo.ligacoes} />
            <Indicador
              rotulo="Petições solicitadas"
              valor={dados.resumo.peticoes_solicitadas}
            />
          </section>

          <section
            aria-label="Registros complementares"
            className="grid grid-cols-2 gap-x-3 gap-y-2 border-y border-borda py-3 sm:grid-cols-4"
          >
            <Resumo rotulo="Colaboradores" valor={dados.resumo.colaboradores} />
            <Resumo
              rotulo="Google confirmado"
              valor={dados.resumo.google_confirmado}
            />
            <Resumo
              rotulo="Auditorias manuais"
              valor={dados.resumo.auditorias}
            />
            <Resumo
              rotulo="Revisões concluídas"
              valor={dados.resumo.revisoes}
            />
          </section>

          <Aviso tom="info" titulo="Critérios do painel">
            O período é de {dados.periodo.dias} dias. Entrevistas em andamento
            tiveram batida nos últimos {dados.atividade.janela_minutos} minutos.
            Auditoria do roteiro só aparece após conferência manual na
            Supervisão.
          </Aviso>

          <AlertasMovimentacao alertas={dados.alertas} />

          <Cartao
            titulo="Equipe"
            subtitulo="Os números refletem somente o que foi registrado no sistema."
          >
            <form
              className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end"
              onSubmit={filtrar}
            >
              <label className="grid flex-1 gap-[6px] text-sm font-semibold text-tinta">
                Filtrar por nome
                <Campo
                  value={busca}
                  placeholder="Digite o nome do colaborador"
                  onChange={(evento) => setBusca(evento.target.value)}
                />
              </label>
              <div className="flex gap-2">
                <Botao
                  variante="secundario"
                  type="submit"
                  disabled={carregando}
                >
                  Buscar
                </Botao>
                <Botao
                  variante="discreto"
                  type="button"
                  disabled={carregando || (!busca && !buscaAplicada)}
                  onClick={limparBusca}
                >
                  Limpar
                </Botao>
              </div>
            </form>

            <div className="mb-4 grid gap-2 lg:hidden">
              <label className="grid gap-[6px] text-sm font-semibold text-tinta">
                Ordenar equipe por
                <CampoSeletor
                  value={ordem}
                  onChange={(evento) =>
                    ordenar(evento.target.value as OrdemEquipe)
                  }
                >
                  {CAMPOS_DE_ORDENACAO.map((campo) => (
                    <option key={campo.valor} value={campo.valor}>
                      {campo.rotulo}
                    </option>
                  ))}
                </CampoSeletor>
              </label>
              <Botao variante="secundario" onClick={inverterDirecao}>
                {direcao === "asc" ? "Crescente" : "Decrescente"}
              </Botao>
            </div>

            {dados.colaboradores.length === 0 ? (
              <Vazio>
                {buscaAplicada
                  ? "Nenhum colaborador encontrado para esse filtro."
                  : "Nenhum colaborador ou registro operacional disponível."}
              </Vazio>
            ) : (
              <>
                <div className="grid gap-3 lg:hidden">
                  {dados.colaboradores.map((colaborador) => (
                    <CartaoColaborador
                      key={colaborador.id || colaborador.nome}
                      colaborador={colaborador}
                    />
                  ))}
                </div>
                <div className="hidden overflow-x-auto lg:block">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr
                        className={
                          "border-b border-borda text-left text-xs font-semibold uppercase " +
                          "tracking-[0.03em] text-tinta-3"
                        }
                      >
                        <CabecalhoOrdenavel
                          campo="colaborador"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Colaborador
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="atividade"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Atividade
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="entrevistas"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Entrevistas
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="google"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Google
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="roteiro"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Roteiro
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="ligacoes"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Ligações
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="revisoes"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Revisões
                        </CabecalhoOrdenavel>
                        <CabecalhoOrdenavel
                          campo="peticoes"
                          ordem={ordem}
                          direcao={direcao}
                          aoOrdenar={ordenar}
                        >
                          Petições
                        </CabecalhoOrdenavel>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.colaboradores.map((colaborador) => (
                        <tr
                          key={colaborador.id || colaborador.nome}
                          className="border-b border-borda align-top last:border-b-0"
                        >
                          <td className="px-3 py-3 font-semibold text-tinta">
                            {colaborador.nome}
                          </td>
                          <td className="px-3 py-3 text-tinta-2">
                            {colaborador.atividades.length === 0 ? (
                              <Selo tom="neutro">Sem entrevista em curso</Selo>
                            ) : (
                              colaborador.atividades.map((atividade) => (
                                <div
                                  key={`${atividade.cliente}-${atividade.ultima_batida_em}`}
                                  className="mb-1 last:mb-0"
                                >
                                  <Selo tom="info" simbolo="→">
                                    {atividade.cliente}
                                  </Selo>
                                  <span className="mt-1 block font-codigo text-xs text-tinta-3">
                                    {dataHora(atividade.ultima_batida_em)}
                                  </span>
                                </div>
                              ))
                            )}
                          </td>
                          <td className="px-3 py-3 tabular-nums text-tinta">
                            {colaborador.entrevistas}
                          </td>
                          <td className="px-3 py-3 tabular-nums text-tinta-2">
                            {colaborador.google_confirmado} confirmado
                            <span className="mt-1 block text-xs text-tinta-3">
                              {colaborador.google_sem_registro} sem registro
                            </span>
                          </td>
                          <td className="px-3 py-3 text-tinta-2">
                            {colaborador.roteiro_percentual === null
                              ? "Não auditado"
                              : `${colaborador.roteiro_percentual}%`}
                            <span className="mt-1 block text-xs text-tinta-3">
                              {colaborador.auditorias} auditorias ·{" "}
                              {colaborador.entrevistas_nao_auditadas} pendentes
                            </span>
                          </td>
                          <td className="px-3 py-3 font-codigo tabular-nums text-tinta">
                            {colaborador.ligacoes}
                          </td>
                          <td className="px-3 py-3 tabular-nums text-tinta-2">
                            {colaborador.revisoes}
                            <span className="mt-1 block text-xs text-tinta-3">
                              {colaborador.revisoes_abertas} abertas
                            </span>
                          </td>
                          <td className="px-3 py-3 tabular-nums text-tinta-2">
                            {colaborador.peticoes_solicitadas}
                            <span className="mt-1 block text-xs text-tinta-3">
                              {colaborador.peticoes_concluidas} concluídas ·{" "}
                              {colaborador.peticoes_falhas} falhas
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {dados.paginacao.total > 0 && (
              <nav
                aria-label="Paginação da equipe"
                className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-borda pt-4"
              >
                <span className="text-sm text-tinta-2">
                  {intervaloDaPagina(dados.paginacao)} de{" "}
                  {dados.paginacao.total} colaborador(es)
                </span>
                <div className="flex gap-2">
                  <Botao
                    variante="secundario"
                    pequeno
                    disabled={carregando || dados.paginacao.pagina === 1}
                    onClick={() => setPagina(dados.paginacao.pagina - 1)}
                  >
                    Anterior
                  </Botao>
                  <Botao
                    variante="secundario"
                    pequeno
                    disabled={
                      carregando ||
                      dados.paginacao.pagina === dados.paginacao.paginas
                    }
                    onClick={() => setPagina(dados.paginacao.pagina + 1)}
                  >
                    Próxima
                  </Botao>
                </div>
              </nav>
            )}
          </Cartao>

          <Cartao
            titulo="Ranking de ligações"
            subtitulo="Posições empatadas são mantidas."
          >
            {dados.ranking_ligacoes.length === 0 ? (
              <Vazio>Não há ligações registradas no período.</Vazio>
            ) : (
              <ol className="m-0 grid list-none gap-2 p-0">
                {dados.ranking_ligacoes.map((colaborador, indice) => (
                  <li
                    key={
                      colaborador.id ||
                      `${colaborador.posicao}-${colaborador.nome}-${indice}`
                    }
                    className="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 rounded-campo border border-borda bg-papel-2 px-3 py-2"
                  >
                    <strong className="font-codigo text-sm tabular-nums text-tinta-2">
                      {colaborador.posicao}º
                    </strong>
                    <span className="min-w-0 truncate font-semibold text-tinta">
                      {colaborador.nome}
                    </span>
                    <span className="font-codigo text-sm tabular-nums text-tinta-2">
                      {colaborador.ligacoes} ligação(ões)
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Cartao>
          <Aviso tom="atencao" titulo="Leitura responsável">
            {dados.aviso}
          </Aviso>
        </>
      )}
    </div>
  );
}

const CAMPOS_DE_ORDENACAO: Array<{ valor: OrdemEquipe; rotulo: string }> = [
  { valor: "colaborador", rotulo: "Colaborador" },
  { valor: "atividade", rotulo: "Atividade em curso" },
  { valor: "entrevistas", rotulo: "Entrevistas" },
  { valor: "google", rotulo: "Google confirmado" },
  { valor: "roteiro", rotulo: "Cobertura do roteiro" },
  { valor: "ligacoes", rotulo: "Ligações" },
  { valor: "revisoes", rotulo: "Revisões concluídas" },
  { valor: "revisoes_abertas", rotulo: "Revisões em aberto" },
  { valor: "peticoes", rotulo: "Petições solicitadas" },
  { valor: "falhas_peticao", rotulo: "Falhas de petição" },
];

function AlertasMovimentacao({
  alertas,
}: {
  alertas: PainelOperacao["alertas"];
}) {
  return (
    <Cartao
      titulo="Alertas de movimentação"
      subtitulo="Considera ligações, entrevistas, auditorias, revisões e solicitações de petição registradas no sistema."
    >
      <div className="grid gap-3 lg:grid-cols-2">
        <GrupoDeAlerta
          titulo="Sem movimentação hoje"
          alerta={alertas.sem_movimentacao_hoje}
          periodo="hoje"
          tom="atencao"
        />
        <GrupoDeAlerta
          titulo="Sem movimentação há 7 dias"
          alerta={alertas.sem_movimentacao_7_dias}
          periodo="7-dias"
          tom="critico"
        />
      </div>
    </Cartao>
  );
}

function GrupoDeAlerta({
  titulo,
  alerta,
  periodo,
  tom,
}: {
  titulo: string;
  alerta: AlertaMovimentacao;
  periodo: "hoje" | "7-dias";
  tom: "atencao" | "critico";
}) {
  const [listaCompleta, setListaCompleta] = useState<AlertaMovimentacao | null>(
    null,
  );
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function carregarLista(pagina: number) {
    setCarregando(true);
    try {
      setListaCompleta(await buscarAlertasMovimentacao(periodo, pagina));
      setErro(null);
    } catch (falha) {
      setErro(
        falha instanceof Error
          ? falha.message
          : "Não foi possível carregar a lista completa.",
      );
    } finally {
      setCarregando(false);
    }
  }

  if (!alerta.total) {
    return (
      <section className="rounded-campo border border-borda bg-papel-2 p-3">
        <h2 className="m-0 text-sm font-semibold text-tinta">{titulo}</h2>
        <Selo tom="ok" simbolo="✓">
          Nenhum alerta
        </Selo>
      </section>
    );
  }

  return (
    <section className="rounded-campo border border-borda bg-papel-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold text-tinta">{titulo}</h2>
        <Selo tom={tom} simbolo={tom === "critico" ? "✕" : "!"}>
          {alerta.total} colaborador(es)
        </Selo>
      </div>
      <ul className="mb-0 mt-3 grid list-none gap-2 p-0">
        {alerta.colaboradores.map((colaborador, indice) => (
          <li
            key={colaborador.id || `${colaborador.nome}-${indice}`}
            className="border-b border-borda pb-2 text-sm last:border-b-0 last:pb-0"
          >
            <strong className="block text-tinta">{colaborador.nome}</strong>
            <span className="text-xs text-tinta-3">
              Última movimentação: {dataHora(colaborador.ultima_movimentacao)}
            </span>
          </li>
        ))}
      </ul>
      {erro && <p className="mb-0 mt-3 text-sm text-critico">{erro}</p>}
      {!listaCompleta && alerta.total > alerta.colaboradores.length && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-tinta-3">
            Mais {alerta.total - alerta.colaboradores.length} colaborador(es)
            com este alerta.
          </span>
          <Botao
            variante="texto"
            pequeno
            disabled={carregando}
            onClick={() => void carregarLista(1)}
          >
            {carregando ? "Carregando..." : "Ver lista completa"}
          </Botao>
        </div>
      )}
      {listaCompleta && (
        <ModalListaAlertas
          titulo={titulo}
          alerta={listaCompleta}
          carregando={carregando}
          aoFechar={() => setListaCompleta(null)}
          aoMudarPagina={(pagina) => void carregarLista(pagina)}
        />
      )}
    </section>
  );
}

function ModalListaAlertas({
  titulo,
  alerta,
  carregando,
  aoFechar,
  aoMudarPagina,
}: {
  titulo: string;
  alerta: AlertaMovimentacao;
  carregando: boolean;
  aoFechar: () => void;
  aoMudarPagina: (pagina: number) => void;
}) {
  const idDoTitulo = `alertas-${titulo.replaceAll(" ", "-").toLowerCase()}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-tinta/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={idDoTitulo}
      onMouseDown={aoFechar}
    >
      <div
        className="flex max-h-full w-full max-w-[620px] flex-col rounded-cartao border border-borda-forte bg-papel shadow-modal"
        onMouseDown={(evento) => evento.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-borda px-4 py-3">
          <div>
            <h2 id={idDoTitulo} className="m-0 font-titulo text-xl text-tinta">
              {titulo}
            </h2>
            <p className="mb-0 mt-1 text-sm text-tinta-2">
              {alerta.total} colaborador(es) com alerta
            </p>
          </div>
          <Botao variante="secundario" pequeno onClick={aoFechar}>
            Fechar
          </Botao>
        </header>
        <ul className="m-0 grid max-h-[55vh] list-none gap-2 overflow-y-auto p-4">
          {alerta.colaboradores.map((colaborador, indice) => (
            <li
              key={colaborador.id || `${colaborador.nome}-${indice}`}
              className="rounded-campo border border-borda bg-papel-2 px-3 py-2 text-sm"
            >
              <strong className="block text-tinta">{colaborador.nome}</strong>
              <span className="text-xs text-tinta-3">
                Última movimentação: {dataHora(colaborador.ultima_movimentacao)}
              </span>
            </li>
          ))}
        </ul>
        <nav className="flex flex-wrap items-center justify-between gap-3 border-t border-borda px-4 py-3">
          <span className="text-sm text-tinta-2">
            {intervaloDoAlerta(alerta)} de {alerta.total} colaborador(es)
          </span>
          <div className="flex gap-2">
            <Botao
              variante="secundario"
              pequeno
              disabled={carregando || alerta.pagina === 1}
              onClick={() => aoMudarPagina(alerta.pagina - 1)}
            >
              Anterior
            </Botao>
            <Botao
              variante="secundario"
              pequeno
              disabled={carregando || alerta.pagina === alerta.paginas}
              onClick={() => aoMudarPagina(alerta.pagina + 1)}
            >
              Próxima
            </Botao>
          </div>
        </nav>
      </div>
    </div>
  );
}

function CabecalhoOrdenavel({
  campo,
  ordem,
  direcao,
  aoOrdenar,
  children,
}: {
  campo: OrdemEquipe;
  ordem: OrdemEquipe;
  direcao: DirecaoOrdem;
  aoOrdenar: (campo: OrdemEquipe) => void;
  children: string;
}) {
  const ativo = ordem === campo;
  const textoDaDirecao = direcao === "asc" ? "crescente" : "decrescente";

  return (
    <th
      aria-sort={
        ativo ? (direcao === "asc" ? "ascending" : "descending") : "none"
      }
      className="px-3 py-2"
    >
      <button
        type="button"
        className="inline-flex items-center gap-1 font-semibold text-tinta-3 underline-offset-2 hover:text-tinta hover:underline"
        onClick={() => aoOrdenar(campo)}
      >
        {children}
        <span aria-hidden="true">
          {ativo ? (direcao === "asc" ? "↑" : "↓") : "↕"}
        </span>
        {ativo && <span className="sr-only">Ordenação {textoDaDirecao}</span>}
      </button>
    </th>
  );
}

function Indicador({
  destaque,
  rotulo,
  valor,
}: {
  destaque?: boolean;
  rotulo: string;
  valor: number;
}) {
  return (
    <div
      className={`rounded-campo border px-4 py-3 ${
        destaque ? "border-acao-borda bg-acao-clara" : "border-borda bg-papel-2"
      }`}
    >
      <span className="block text-xs font-semibold uppercase tracking-[0.04em] text-tinta-3">
        {rotulo}
      </span>
      <strong className="mt-1 block font-titulo text-2xl tabular-nums text-tinta">
        {valor}
      </strong>
    </div>
  );
}

function Resumo({ rotulo, valor }: { rotulo: string; valor: number }) {
  return (
    <div className="min-w-0">
      <strong className="block font-codigo text-lg tabular-nums text-tinta">
        {valor}
      </strong>
      <span className="block text-xs leading-snug text-tinta-3">{rotulo}</span>
    </div>
  );
}

function CartaoColaborador({
  colaborador,
}: {
  colaborador: ColaboradorOperacional;
}) {
  const emAtendimento = colaborador.atividades.length > 0;

  return (
    <article className="rounded-campo border border-borda bg-papel-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="m-0 min-w-0 text-base font-semibold text-tinta">
          {colaborador.nome}
        </h2>
        <Selo
          tom={emAtendimento ? "info" : "neutro"}
          simbolo={emAtendimento ? "→" : undefined}
        >
          {emAtendimento ? "Em atendimento" : "Sem atendimento"}
        </Selo>
      </div>

      {emAtendimento && (
        <div className="mt-3 grid gap-2">
          {colaborador.atividades.map((atividade) => (
            <div
              key={`${atividade.cliente}-${atividade.ultima_batida_em}`}
              className="rounded-campo border border-acao-borda bg-acao-clara px-3 py-2"
            >
              <strong className="block text-sm text-tinta">
                {atividade.cliente}
              </strong>
              <span className="block text-xs text-tinta-2">
                Última atualização: {dataHora(atividade.ultima_batida_em)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 border-y border-borda py-3">
        <Resumo rotulo="Entrevistas" valor={colaborador.entrevistas} />
        <Resumo rotulo="Ligações" valor={colaborador.ligacoes} />
        <Resumo rotulo="Revisões concluídas" valor={colaborador.revisoes} />
        <Resumo
          rotulo="Petições solicitadas"
          valor={colaborador.peticoes_solicitadas}
        />
      </div>

      <dl className="m-0 mt-3 grid gap-3 text-sm">
        <LinhaDetalhe
          rotulo="Google Meu Negócio"
          valor={`${colaborador.google_confirmado} confirmado(s) · ${colaborador.google_sem_registro} sem registro`}
        />
        <LinhaDetalhe
          rotulo="Auditoria do roteiro"
          valor={
            colaborador.roteiro_percentual === null
              ? "Não auditado"
              : `${colaborador.roteiro_percentual}% coberto`
          }
          detalhe={`${colaborador.auditorias} auditoria(s) · ${colaborador.entrevistas_nao_auditadas} não auditada(s)`}
        />
        <LinhaDetalhe
          rotulo="Revisões em aberto"
          valor={`${colaborador.revisoes_abertas} aberta(s)`}
        />
        <LinhaDetalhe
          rotulo="Geração de petições"
          valor={`${colaborador.peticoes_concluidas} concluída(s) · ${colaborador.peticoes_falhas} falha(s)`}
        />
      </dl>
    </article>
  );
}

function LinhaDetalhe({
  rotulo,
  valor,
  detalhe,
}: {
  rotulo: string;
  valor: string;
  detalhe?: string;
}) {
  return (
    <div className="grid gap-1">
      <dt className="text-xs font-semibold text-tinta-3">{rotulo}</dt>
      <dd className="m-0 text-tinta">{valor}</dd>
      {detalhe && <dd className="m-0 text-xs text-tinta-3">{detalhe}</dd>}
    </div>
  );
}

function intervaloDaPagina(paginacao: PainelOperacao["paginacao"]): string {
  const inicio = (paginacao.pagina - 1) * paginacao.tamanho + 1;
  const fim = Math.min(paginacao.pagina * paginacao.tamanho, paginacao.total);
  return `${inicio}-${fim}`;
}

function intervaloDoAlerta(alerta: AlertaMovimentacao): string {
  const inicio = (alerta.pagina - 1) * alerta.tamanho + 1;
  const fim = Math.min(alerta.pagina * alerta.tamanho, alerta.total);
  return `${inicio}-${fim}`;
}
