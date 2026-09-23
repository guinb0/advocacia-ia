"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Categoria, SituacaoCaso } from "@/lib/types";
import BaixarDocumentos from "@/components/caso/BaixarDocumentos";
import { Aviso, BarraAbas, BotaoAba, Botao, CampoSeletor, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import { buscarNoConteudoDoCaso, prazosAcervo, tentarNovamenteCaso, type PrazosAcervo } from "@/lib/api";
import ItemChecklistLinha from "@/components/caso/ItemChecklistLinha";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import PainelPortal from "@/components/portal/PainelPortal";
import PedidoCliente from "@/components/caso/PedidoCliente";
import EnvioEmLote from "@/components/caso/EnvioEmLote";
import ResumoDocumentos from "@/components/caso/ResumoDocumentos";
import TriagemDocumentos from "@/components/caso/TriagemDocumentos";
import VisorEntrega from "@/components/caso/VisorEntrega";

type Filtro = "todos" | "pendentes" | "enviados";

function IconeLupa(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

/** Sem acento e em minúsculas: "certidao" acha "Certidão". */
function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** Tudo o que o advogado pode lembrar de um item: nome, número, observação,
 *  tipo do glossário e o nome dos arquivos que já chegaram para ele. */
function textoDoItem(item: SituacaoCaso["itens"][number]): string {
  return normalizar(
    [
      item.nome,
      String(item.numero),
      item.codigo,
      item.observacao,
      item.tipo_documento ?? "",
      ...item.entregas.flatMap((e) => [e.arquivo, e.identificacao_ia ?? ""]),
    ].join(" "),
  );
}

interface Props {
  situacao: SituacaoCaso;
  enviando: string | null;
  erro: string | null;
  onVoltar: () => void;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onEnviarLote: (arquivos: File[]) => Promise<void> | void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
  onReatribuir: (entregaId: string, itens: string[]) => Promise<void> | void;
  /** O checklist está dentro do atendimento, não na tela do caso.
   *
   * Ali a chamada já está na tela e o advogado já entrou na sala do caso ao
   * criá-lo: o painel do portal não pode abrir uma segunda, com câmera e tudo,
   * no meio dos documentos. O link e a senha continuam à vista — eles são para
   * MANDAR ao cliente, que é quem precisa deles. */
  dentroDoAtendimento?: boolean;
  /** Mostra a estatística de prazos do acervo no fim da página.
   *
   * Desligado por padrão porque este mesmo componente desenha o PORTAL DO
   * CLIENTE (`app/portal/[token]/page.tsx`). Lá quem olha é o cliente, e taxa de
   * recurso e duração de processo do escritório não são informação dele — além
   * de a rota exigir papel de advogado, o que renderia um bloco quebrado. */
  mostrarPrazos?: boolean;
  categorias?: Categoria[];
  onTrocarCategoria?: (categoria: string) => Promise<void>;
  /** A busca também procura no CONTEÚDO lido dos arquivos (campos e texto do
   *  OCR), no servidor. Desligado no portal do cliente, que não tem acesso à rota. */
  buscarNoConteudo?: boolean;
}

type AchadosPorItem = Map<string, { arquivo: string; onde: string[] }[]>;

/** "há 2 h", "há 3 dias" — a mesma leitura do cabeçalho no desenho. */
function desde(iso: string): string {
  const minutos = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (!Number.isFinite(minutos) || minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  const dias = Math.floor(horas / 24);
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

export default function Checklist({
  situacao,
  enviando,
  erro,
  onVoltar,
  onEnviar,
  onEnviarLote,
  onRemover,
  onVincularIdentidade,
  onReatribuir,
  dentroDoAtendimento = false,
  mostrarPrazos = false,
  categorias,
  onTrocarCategoria,
  buscarNoConteudo = false,
}: Props) {
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [busca, setBusca] = useState("");
  const campoBusca = useRef<HTMLInputElement>(null);
  const [achados, setAchados] = useState<{ consulta: string; porItem: AchadosPorItem } | null>(null);
  const [buscandoConteudo, setBuscandoConteudo] = useState(false);
  const casoId = situacao.caso.id;
  const [tentandoTodosDeNovo, setTentandoTodosDeNovo] = useState(false);
  const [resultadoTentarTodos, setResultadoTentarTodos] = useState<string | null>(null);

  // Busca no conteúdo dos arquivos: espera a pessoa parar de digitar e cancela
  // a consulta anterior, para a resposta de "ce" não sobrescrever a de "cep".
  useEffect(() => {
    const consulta = busca.trim();
    if (!buscarNoConteudo || consulta.length < 2) {
      setAchados(null);
      setBuscandoConteudo(false);
      return;
    }
    const controle = new AbortController();
    setBuscandoConteudo(true);
    const espera = window.setTimeout(() => {
      buscarNoConteudoDoCaso(casoId, consulta, controle.signal)
        .then((resultado) => {
          const porItem: AchadosPorItem = new Map();
          for (const r of resultado) {
            for (const codigo of r.itens) {
              const lista = porItem.get(codigo) ?? [];
              lista.push({ arquivo: r.arquivo, onde: r.onde });
              porItem.set(codigo, lista);
            }
          }
          setAchados({ consulta, porItem });
        })
        .catch(() => {
          if (!controle.signal.aborted) setAchados(null);
        })
        .finally(() => {
          if (!controle.signal.aborted) setBuscandoConteudo(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(espera);
      controle.abort();
    };
  }, [busca, buscarNoConteudo, casoId]);

  // "/" leva à busca de qualquer ponto da página, como em sites de busca —
  // menos quando a pessoa já está digitando em outro campo.
  useEffect(() => {
    function aoTeclar(e: KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const alvo = e.target as HTMLElement | null;
      if (alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName))) return;
      e.preventDefault();
      campoBusca.current?.focus();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, []);
  const [trocando, setTrocando] = useState(false);
  const [erroTroca, setErroTroca] = useState<string | null>(null);
  /** Entrega aberta no visor. Mora aqui, e não na linha, para o visor poder
   *  passar ao documento seguinte sem fechar e reabrir. */
  const [aberta, setAberta] = useState<string | null>(null);
  const fecharVisor = useCallback(() => setAberta(null), []);
  const { caso, categoria, progresso, itens } = situacao;

  if (!categoria) {
    return (
      <>
        <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
        <Aviso tom="critico" titulo="Categoria indisponível">
          {situacao.erro ?? "O tipo de ação deste caso não pôde ser carregado."}
        </Aviso>
      </>
    );
  }

  const naoResolvidos = itens.filter((i) => i.status !== "entregue").length;

  // Conta erro no checklist E na triagem inteira: documento parado na
  // triagem não tem erro nenhum (leu certo, só não bateu com item do
  // checklist), mas "reanalisar" tenta rotear de novo mesmo assim — o
  // checklist pode ter mudado desde a primeira leitura. Por isso o botão
  // aparece SEMPRE que há qualquer coisa fora do checklist, não só erro.
  const totalParaReanalisar =
    itens.reduce((soma, item) => soma + item.entregas.filter((e) => e.status_proc === "erro").length, 0)
    + (situacao.triagem ?? []).length;

  async function tentarTodosDeNovo() {
    setTentandoTodosDeNovo(true);
    setResultadoTentarTodos(null);
    try {
      const resultado = await tentarNovamenteCaso(casoId);
      setResultadoTentarTodos(
        resultado.falharam.length === 0
          ? `${resultado.reenfileiradas} documento(s) reenviado(s) para leitura.`
          : `${resultado.reenfileiradas} reenviado(s); ${resultado.falharam.length} não puderam ser reenviados (arquivo perdido — peça o reenvio).`,
      );
    } catch (e) {
      setResultadoTentarTodos(e instanceof Error ? e.message : "Não foi possível tentar de novo.");
    } finally {
      setTentandoTodosDeNovo(false);
    }
  }

  // A busca vale para as três abas; as contagens mostram o que ela deixou.
  const termos = normalizar(busca).split(/\s+/).filter(Boolean);
  // Só vale o resultado do servidor que responde à busca que está no campo.
  const noConteudo = achados && achados.consulta === busca.trim() ? achados.porItem : null;
  const encontrados =
    termos.length === 0
      ? itens
      : itens.filter((item) => {
          const texto = textoDoItem(item);
          return termos.every((t) => texto.includes(t)) || Boolean(noConteudo?.has(item.codigo));
        });
  const achadosPendentes = encontrados.filter((i) => i.status !== "entregue").length;
  const achadosEnviados = encontrados.length - achadosPendentes;

  const visiveis = encontrados.filter((item) => {
    if (filtro === "pendentes") return item.status !== "entregue";
    if (filtro === "enviados") return item.status === "entregue";
    return true;
  });

  // A ordem de navegação é a da lista na tela, com a busca e o filtro atuais.
  // Uma CIN que vale para RG e CPF aparece nos dois itens e é visitada uma vez.
  const sequencia: { id: string; arquivo: string; rotulo: string }[] = [];
  const jaNaSequencia = new Set<string>();
  for (const item of visiveis) {
    for (const entrega of item.entregas) {
      if (jaNaSequencia.has(entrega.id)) continue;
      jaNaSequencia.add(entrega.id);
      sequencia.push({ id: entrega.id, arquivo: entrega.arquivo, rotulo: item.nome });
    }
  }
  const posicaoAberta = aberta ? sequencia.findIndex((e) => e.id === aberta) : -1;
  const entregaAberta = posicaoAberta >= 0 ? sequencia[posicaoAberta] : null;

  const filtros: { id: Filtro; nome: string }[] = [
    { id: "todos", nome: `Todos (${encontrados.length})` },
    { id: "pendentes", nome: `Pendentes (${achadosPendentes})` },
    { id: "enviados", nome: `Enviados (${achadosEnviados})` },
  ];

  const pct = Math.max(0, Math.min(100, progresso.percentual_obrigatorios));
  const codigoAtual = categoria.codigo;

  async function trocarCategoria(codigo: string) {
    if (!onTrocarCategoria || codigo === codigoAtual) return;
    const nome = categorias?.find((c) => c.codigo === codigo)?.nome ?? codigo;
    const temDocumentos = itens.some((i) => i.entregas.length > 0) || (situacao.triagem?.length ?? 0) > 0;
    if (
      temDocumentos &&
      !window.confirm(
        `Trocar o tipo do caso para "${nome}" muda o checklist. ` +
          "Documentos que não fizerem parte do novo tipo vão para a triagem, sem ser apagados. Continuar?",
      )
    ) {
      return;
    }
    setTrocando(true);
    setErroTroca(null);
    try {
      await onTrocarCategoria(codigo);
    } catch (e) {
      setErroTroca(e instanceof Error ? e.message : "Não foi possível trocar o tipo do caso.");
    } finally {
      setTrocando(false);
    }
  }

  return (
    <>
      <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <div className="px-6 py-[22px] mb-5 border border-borda-forte rounded-cartao bg-papel shadow-cartao">
        <div className="flex justify-between items-center gap-[14px] mb-[14px] flex-wrap">
          {categorias && categorias.length > 0 && onTrocarCategoria ? (
            <label className="flex items-center gap-2 flex-wrap text-tinta-3 text-xs font-semibold">
              Tipo de ação
              <CampoSeletor
                aria-label="Tipo de ação do caso"
                value={codigoAtual}
                disabled={trocando}
                onChange={(e) => void trocarCategoria(e.target.value)}
              >
                {categorias.map((c) => (
                  <option key={c.codigo} value={c.codigo}>
                    {c.nome}
                  </option>
                ))}
              </CampoSeletor>
              {trocando && <span className="font-normal">Trocando…</span>}
            </label>
          ) : (
            <Selo tom="info">{categoria.nome}</Selo>
          )}
          <span className="text-tinta-3 text-xs tabular-nums">
            atualizado {desde(caso.atualizado_em || caso.criado_em)}
          </span>
        </div>

        {erroTroca && (
          <div className="mb-[14px]">
            <Aviso tom="critico" titulo="O tipo do caso não foi trocado">
              {erroTroca}
            </Aviso>
          </div>
        )}

        <div className="flex justify-between items-end gap-6 flex-wrap">
          <div>
            <h2 className="m-0 text-xl tracking-[-0.01em]">{caso.cliente}</h2>
            <p className="mt-[6px] mb-0 max-w-[68ch] text-tinta-2 text-sm leading-[1.55]">
              {categoria.descricao}
            </p>
          </div>
          <div className="text-right">
            <span className="text-tinta font-titulo text-[2rem] font-semibold tabular-nums leading-none whitespace-nowrap">
              {progresso.obrigatorios_recebidos ?? progresso.obrigatorios_entregues}
              <span className="text-tinta-3 text-[1.25rem]">/{progresso.obrigatorios_total}</span>
            </span>
            <div className="mt-[2px] text-tinta-3 text-xs">documentos obrigatórios recebidos</div>
          </div>
        </div>

        <div
          className="h-2 mt-4 rounded-pill bg-papel-3 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos obrigatórios entregues"
        >
          <i
            className="block h-full rounded-pill bg-acao transition-[width] duration-[240ms] ease-[ease]"
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="flex gap-2 mt-[14px] flex-wrap">
          {(progresso.obrigatorios_recebidos ?? progresso.obrigatorios_entregues) > progresso.obrigatorios_entregues && (
            <Selo tom="atencao" simbolo="!">
              {progresso.obrigatorios_entregues} validados · {(progresso.obrigatorios_recebidos ?? 0) - progresso.obrigatorios_entregues} a conferir
            </Selo>
          )}
          {progresso.obrigatorios_pendentes > 0 && (
            <Selo tom="critico" simbolo="✕">
              {progresso.obrigatorios_pendentes} sem arquivo
            </Selo>
          )}
          {progresso.itens_a_conferir > 0 && (
            <Selo tom="atencao" simbolo="!">
              {progresso.itens_a_conferir} a conferir
            </Selo>
          )}
          {(progresso.em_triagem ?? 0) > 0 && (
            <Selo tom="atencao" simbolo="?">
              {progresso.em_triagem ?? 0} para identificar
            </Selo>
          )}
          <Selo tom="neutro">
            {progresso.opcionais_entregues} de {progresso.opcionais_total} opcionais
          </Selo>
        </div>

        {progresso.pronto && (
          <div className="mt-4">
            <Aviso tom="ok" titulo="Instrução completa">
              Todos os documentos obrigatórios foram entregues e conferidos. O caso está pronto
              para a inicial.
            </Aviso>
          </div>
        )}

        {/* O pacote fica logo abaixo do "instrução completa": é o passo
          * seguinte a ele. Aparece antes disso também, porque baixar o que já
          * chegou é útil no meio do caminho — mas só ganha o botão cheio
          * quando o checklist fecha. A contagem é de ENTREGAS DISTINTAS: uma
          * CIN que atende RG e CPF aparece em dois itens e é um arquivo só. */}
        <BaixarDocumentos
          casoId={caso.id}
          total={new Set(itens.flatMap((i) => i.entregas.map((e) => e.id))).size}
          pronto={progresso.pronto}
        />
      </div>

      {erro && (
        <div className="mb-4">
          <Aviso tom="critico" titulo="Não foi possível concluir a ação">
            {erro}
          </Aviso>
        </div>
      )}

      {/* Card de busca logo abaixo do cabeçalho: é a primeira coisa que o
        * advogado procura quando o checklist é longo. Fica ACIMA do envio em
        * lote, que é uma área de arraste alta e empurrava a lista para fora
        * da primeira tela. */}
      <section
        aria-label="Encontrar documento no checklist"
        className="flex items-center gap-x-5 gap-y-3 flex-wrap px-5 py-4 border border-acao-borda border-l-4 border-l-acao rounded-cartao bg-papel shadow-cartao"
      >
        <div className="flex items-center gap-3 shrink-0">
          <span
            aria-hidden="true"
            className="flex items-center justify-center w-10 h-10 rounded-full bg-acao-clara text-acao"
          >
            <IconeLupa className="w-5 h-5" />
          </span>
          <div>
            <h3 className="m-0 text-tinta font-titulo text-base font-semibold leading-tight">
              Encontrar documento
            </h3>
            <p className="m-0 mt-[2px] text-tinta-3 text-xs">
              {itens.length} {itens.length === 1 ? "item" : "itens"} no checklist
            </p>
          </div>
        </div>

        <label className="relative flex-1 min-w-[240px]">
          <span className="sr-only">Buscar documento no checklist</span>
          <IconeLupa
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-tinta-3"
          />
          <input
            ref={campoBusca}
            type="search"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setBusca("");
            }}
            placeholder={
              buscarNoConteudo
                ? "Nome, número, arquivo ou o que está escrito nele — ex.: RG, CEP, 70000-000"
                : "Digite o nome, o número ou o arquivo — ex.: RG, certidão, comprovante"
            }
            className="w-full min-h-[44px] pl-10 pr-12 py-[10px] border-2 border-borda-campo rounded-campo bg-papel text-tinta text-base placeholder:text-tinta-3 transition-[border-color,box-shadow] duration-[120ms] ease-out hover:border-acao focus:border-acao focus:shadow-[0_0_0_3px_var(--acao-clara)] focus:outline-none"
          />
          {busca && buscandoConteudo && (
            <span className="absolute right-10 top-1/2 -translate-y-1/2 text-tinta-3 text-xs" role="status">
              buscando…
            </span>
          )}
          {!busca && (
            <kbd
              aria-hidden="true"
              title="Atalho: tecle / para buscar"
              className="absolute right-3 top-1/2 -translate-y-1/2 px-[7px] py-[1px] border border-borda rounded bg-papel-2 text-tinta-3 text-xs font-mono"
            >
              /
            </kbd>
          )}
        </label>

        <BarraAbas className="mb-0 shrink-0" aria-label="Filtrar os documentos por situação">
          {filtros.map((f) => (
            <BotaoAba key={f.id} ativa={filtro === f.id} onClick={() => setFiltro(f.id)}>
              {f.nome}
            </BotaoAba>
          ))}
        </BarraAbas>
      </section>

      {visiveis.length === 0 ? (
        termos.length > 0 ? (
          <Vazio className="mt-4">
            {buscandoConteudo
              ? "Procurando também dentro dos arquivos…"
              : `Nenhum documento corresponde a “${busca.trim()}” neste filtro.`}{" "}
            <button type="button" className="underline text-acao" onClick={() => setBusca("")}>
              Limpar busca
            </button>
          </Vazio>
        ) : (
          <Vazio className="mt-4">Nada aqui — tudo resolvido neste filtro.</Vazio>
        )
      ) : (
        <div className="mt-4 border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
          <ul className="list-none m-0 p-0">
            {visiveis.map((item) => (
              <ItemChecklistLinha
                key={item.codigo}
                item={item}
                itensChecklist={itens}
                casoId={caso.id}
                enviando={enviando === item.codigo}
                onEnviar={onEnviar}
                onRemover={onRemover}
                onVincularIdentidade={onVincularIdentidade}
                onReatribuir={onReatribuir}
                dentroDoAtendimento={dentroDoAtendimento}
                achadoNoConteudo={noConteudo?.get(item.codigo)}
                onAbrirEntrega={setAberta}
              />
            ))}
          </ul>
        </div>
      )}

      {/* Some sozinho se o documento aberto deixar a lista (removido, ou fora
        * do filtro depois de uma reclassificação). */}
      {entregaAberta && (
        <VisorEntrega
          entregaId={entregaAberta.id}
          arquivo={entregaAberta.arquivo}
          onFechar={fecharVisor}
          navegacao={{
            posicao: posicaoAberta + 1,
            total: sequencia.length,
            rotulo: entregaAberta.rotulo,
            onAnterior: () => setAberta(sequencia[Math.max(0, posicaoAberta - 1)].id),
            onProximo: () => setAberta(sequencia[Math.min(sequencia.length - 1, posicaoAberta + 1)].id),
          }}
        />
      )}

      <div className="mt-5">
        <EnvioEmLote onEnviar={onEnviarLote} enviando={enviando === "__lote__"} />
      </div>

      {dentroDoAtendimento && (
        <Aviso tom="info" titulo="Classificação automática incorreta?">
          Em cada arquivo recebido, use <strong>Corrigir classificação</strong>. A correção
          ajusta o checklist e passa a orientar as próximas classificações do escritório.
        </Aviso>
      )}

      <div className="mt-5">
        <ResumoDocumentos itens={itens} />
      </div>

      {/* Sempre visível, com ou sem nada pendente: documento na triagem não tem
        * erro (leu certo, só não bateu com item do checklist), então o gatilho
        * certo não é "há erro" — é "existe algo fora do checklist para tentar
        * rotear de novo", e isso pode não estar óbvio para quem olha a tela. */}
      <div className="mt-5">
        <Aviso
          tom={totalParaReanalisar > 0 ? "critico" : "info"}
          titulo={
            totalParaReanalisar > 0
              ? `${totalParaReanalisar} documento(s) fora do checklist ou com falha na leitura`
              : "Reanalisar documentos"
          }
        >
          <div className="flex items-center gap-3 flex-wrap mt-2">
            <BotaoProcesso
              variante="secundario"
              pequeno
              onClick={tentarTodosDeNovo}
              processando={tentandoTodosDeNovo}
              textoProcessando="Reprocessando…"
            >
              Reanalisar documentos
            </BotaoProcesso>
            {resultadoTentarTodos && <span className="text-sm text-tinta-2">{resultadoTentarTodos}</span>}
          </div>
        </Aviso>
      </div>

      <TriagemDocumentos
        entregas={situacao.triagem ?? []}
        itens={itens}
        onAtribuir={onReatribuir}
        onRemover={onRemover}
      />

      <div className="flex flex-col gap-5 mt-5">
        {/* Dentro do atendimento a chamada já está na tela e o advogado já
            entrou na sala do caso — o painel do portal não abre outra. */}
        <PainelPortal casoId={caso.id} semChamada={dentroDoAtendimento} />
        <PedidoCliente casoId={caso.id} progresso={progresso} naoResolvidos={naoResolvidos} />
      </div>

      {mostrarPrazos && <Prazos />}
    </>
  );
}

/* O que os processos parecidos mostram sobre tempo e recurso.
 *
 * Fica no FIM da aba de documentos porque é a pergunta que vem quando a papelada
 * acaba: "e agora, quanto demora?".
 *
 * Deliberadamente magro. O acervo não sustenta "tempo médio de etapa": só 20%
 * dos processos têm mais de uma data, e esses são justamente os que recorreram,
 * ou seja, os mais longos. Por isso o número vai com a AMOSTRA ao lado e
 * rotulado como observado, nunca como previsão — prazo dito ao cliente não pode
 * ser "mais ou menos". Ver `docs/PRAZOS.md` para o que falta ingerir. */
function Prazos() {
  const [d, setD] = useState<PrazosAcervo | null>(null);
  const [falhou, setFalhou] = useState(false);
  useEffect(() => {
    void prazosAcervo()
      .then(setD)
      .catch(() => setFalhou(true));
  }, []);
  /* Falhar CALADO foi um erro meu: o bloco sumia e não havia como saber se era
   * o acervo fora do ar ou se ele nunca tinha sido posto na tela. Agora diz. */
  if (falhou) {
    return (
      <div className="mt-5">
        <Cartao
          titulo="O que os processos parecidos mostram"
          subtitulo="O acervo de precedentes não respondeu — ele fica atrás da VPN. O resto da página funciona normalmente."
        />
      </div>
    );
  }
  if (!d) return null;
  const n = (v: number) => v.toLocaleString("pt-BR");
  return (
    <div className="mt-5">
      <Cartao
        titulo="O que os processos parecidos mostram"
        subtitulo={`Medido em ${n(d.processos)} processos do acervo.`}
      >
        <ul>
          <li>
            <strong>{d.percentual_recurso}%</strong> foram para a segunda instância (
            {n(d.segunda_instancia)} de {n(d.processos)}).
          </li>
          {d.duracao.mediana_dias !== null && (
            <li>
              Do primeiro ao último documento registrado:{" "}
              <strong>{d.duracao.mediana_dias} dias</strong> na mediana,{" "}
              {d.duracao.p90_dias} dias em 9 de cada 10 —{" "}
              <em>
                medido em apenas {d.duracao.processos_medidos} processos, os que têm
                mais de um evento datado
              </em>
              .
            </li>
          )}
        </ul>
        <p className="mb-4 text-tinta-3 text-sm leading-[1.5]">{d.aviso}</p>
      </Cartao>
    </div>
  );
}
