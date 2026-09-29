"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { Categoria, ItemSituacao, SituacaoCaso } from "@/lib/types";
import { buscarNoConteudoDoCaso, tentarNovamenteCaso, type AnaliseDocumental } from "@/lib/api";
import { Aviso, Botao, CampoSeletor, Selo } from "@/components/ui/Basicos";
import { BotaoProcesso } from "@/components/ui/BotaoProcesso";
import BaixarDocumentos from "@/components/caso/BaixarDocumentos";
import { Prazos } from "@/components/caso/Checklist";
import EnvioEmLote from "@/components/caso/EnvioEmLote";
import ItemChecklistLinha from "@/components/caso/ItemChecklistLinha";
import PainelAnaliseDocumental from "@/components/caso/PainelAnaliseDocumental";
import PedidoCliente from "@/components/caso/PedidoCliente";
import ResumoDocumentos from "@/components/caso/ResumoDocumentos";
import TriagemDocumentos from "@/components/caso/TriagemDocumentos";
import VisorEntrega from "@/components/caso/VisorEntrega";
import PainelPortal from "@/components/portal/PainelPortal";

/* A documentação do caso em QUATRO PASSOS, um de cada vez.
 *
 * A tela antiga empilhava tudo (busca, progresso, envio em lote, checklist inteiro, ficha,
 * reanálise, triagem, portal, pedido ao cliente, prazos e a análise da skill) e o escritório não
 * sabia por onde começar. Aqui a tela diz em que passo o caso está, abre só esse passo e explica
 * em frases curtas o que clicar. O resto continua existindo, recolhido em "ver mais".
 *
 * O componente `Checklist` segue intacto para o portal do cliente e para o atendimento. */

type Passo = "juntar" | "conferir" | "analise" | "baixar";

const PASSOS: { id: Passo; titulo: string; curto: string }[] = [
  { id: "juntar", titulo: "Juntar os documentos", curto: "Juntar documentos" },
  { id: "conferir", titulo: "Conferir o que chegou", curto: "Conferir" },
  { id: "analise", titulo: "Ver a análise dos documentos", curto: "Análise" },
  { id: "baixar", titulo: "Baixar o pacote", curto: "Baixar" },
];

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
  categorias?: Categoria[];
  onTrocarCategoria?: (categoria: string) => Promise<void>;
}

function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function Instrucoes({ passos }: { passos: ReactNode[] }) {
  return (
    <ol className="m-0 mb-4 list-none space-y-2 p-0">
      {passos.map((texto, n) => (
        <li key={n} className="flex items-start gap-3 text-base leading-snug text-tinta">
          <span
            aria-hidden
            className="mt-[1px] grid h-6 w-6 flex-none place-items-center rounded-full border-2 border-acao text-xs font-bold text-acao"
          >
            {n + 1}
          </span>
          <span>{texto}</span>
        </li>
      ))}
    </ol>
  );
}

function ListaDeItens({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-cartao border border-borda-forte bg-papel">
      <ul className="m-0 list-none p-0">{children}</ul>
    </div>
  );
}

function Recolhido({ titulo, children, aberto = false }: { titulo: ReactNode; children: ReactNode; aberto?: boolean }) {
  return (
    <details className="group rounded-cartao border border-borda bg-papel" open={aberto || undefined}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold text-tinta [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-tinta-3 transition-transform group-open:rotate-90">
          ▸
        </span>
        {titulo}
      </summary>
      <div className="border-t border-borda px-4 py-4">{children}</div>
    </details>
  );
}

export default function DocumentacaoGuiada({
  situacao,
  enviando,
  erro,
  onVoltar,
  onEnviar,
  onEnviarLote,
  onRemover,
  onVincularIdentidade,
  onReatribuir,
  categorias,
  onTrocarCategoria,
}: Props) {
  const { caso, categoria, progresso, itens } = situacao;
  const triagem = situacao.triagem ?? [];
  const [escolhido, setEscolhido] = useState<Passo | null>(null);
  const [analise, setAnalise] = useState<{ status: AnaliseDocumental["status"]; pendencias: number }>({
    status: "none",
    pendencias: 0,
  });
  const aoMudarAnalise = useCallback(
    (status: AnaliseDocumental["status"], pendencias: number) => setAnalise({ status, pendencias }),
    [],
  );
  const [aberta, setAberta] = useState<string | null>(null);
  const fecharVisor = useCallback(() => setAberta(null), []);
  const [trocandoTipo, setTrocandoTipo] = useState(false);
  const [mostrarTroca, setMostrarTroca] = useState(false);
  const [erroTroca, setErroTroca] = useState<string | null>(null);
  const [reanalisando, setReanalisando] = useState(false);
  const [resultadoReanalise, setResultadoReanalise] = useState<string | null>(null);

  const pendentesObrigatorios = itens.filter((i) => i.status === "pendente" && i.obrigatorio);
  const pendentesOpcionais = itens.filter((i) => i.status === "pendente" && !i.obrigatorio);
  const aConferir = itens.filter((i) => i.status === "conferir");
  const lendo = itens.filter((i) => i.status === "processando").length;
  const comErro = itens.reduce((soma, i) => soma + i.entregas.filter((e) => e.status_proc === "erro").length, 0);
  const recebidos = itens.filter((i) => i.entregas.length > 0);
  const totalArquivos = new Set([...itens.flatMap((i) => i.entregas.map((e) => e.id)), ...triagem.map((e) => e.id)]).size;

  const feito: Record<Passo, boolean> = {
    juntar: progresso.obrigatorios_pendentes === 0,
    conferir: totalArquivos > 0 && aConferir.length === 0 && triagem.length === 0 && comErro === 0 && lendo === 0,
    analise: analise.status === "ready" && analise.pendencias === 0,
    baixar: false,
  };
  const automatico = PASSOS.find((p) => p.id !== "baixar" && !feito[p.id])?.id ?? "baixar";
  const atual = escolhido ?? automatico;
  const indiceAtual = PASSOS.findIndex((p) => p.id === atual);

  // Visor navega por todos os arquivos recebidos, na ordem do checklist.
  const sequencia: { id: string; arquivo: string; rotulo: string }[] = [];
  const vistos = new Set<string>();
  for (const item of recebidos) {
    for (const entrega of item.entregas) {
      if (vistos.has(entrega.id)) continue;
      vistos.add(entrega.id);
      sequencia.push({ id: entrega.id, arquivo: entrega.arquivo, rotulo: item.nome });
    }
  }
  const posicaoAberta = aberta ? sequencia.findIndex((e) => e.id === aberta) : -1;
  const entregaAberta = posicaoAberta >= 0 ? sequencia[posicaoAberta] : null;

  if (!categoria) {
    return (
      <>
        <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
        <Aviso tom="critico" titulo="Tipo de ação indisponível">
          {situacao.erro ?? "O tipo de ação deste caso não pôde ser carregado."}
        </Aviso>
      </>
    );
  }

  async function trocarCategoria(codigo: string) {
    if (!onTrocarCategoria || codigo === categoria?.codigo) return;
    const nome = categorias?.find((c) => c.codigo === codigo)?.nome ?? codigo;
    if (
      totalArquivos > 0 &&
      !window.confirm(
        `Trocar o tipo do caso para "${nome}" muda a lista de documentos. ` +
          "Os arquivos que não fizerem parte do novo tipo vão para “não reconhecidos”, sem ser apagados. Continuar?",
      )
    ) {
      return;
    }
    setTrocandoTipo(true);
    setErroTroca(null);
    try {
      await onTrocarCategoria(codigo);
      setMostrarTroca(false);
    } catch (e) {
      setErroTroca(e instanceof Error ? e.message : "Não foi possível trocar o tipo do caso.");
    } finally {
      setTrocandoTipo(false);
    }
  }

  async function reanalisar() {
    setReanalisando(true);
    setResultadoReanalise(null);
    try {
      const r = await tentarNovamenteCaso(caso.id);
      setResultadoReanalise(
        r.falharam.length === 0
          ? `Pronto: ${r.reenfileiradas} documento(s) voltaram para a leitura. Espere alguns minutos.`
          : `${r.reenfileiradas} voltaram para a leitura; ${r.falharam.length} não tinham mais o arquivo — peça de novo ao cliente.`,
      );
    } catch (e) {
      setResultadoReanalise(e instanceof Error ? e.message : "Não foi possível mandar ler de novo.");
    } finally {
      setReanalisando(false);
    }
  }

  const linha = (item: ItemSituacao) => (
    <ItemChecklistLinha
      key={item.codigo}
      simples
      item={item}
      itensChecklist={itens}
      casoId={caso.id}
      enviando={enviando === item.codigo}
      onEnviar={onEnviar}
      onRemover={onRemover}
      onVincularIdentidade={onVincularIdentidade}
      onReatribuir={onReatribuir}
      onAbrirEntrega={setAberta}
    />
  );

  const faltam = progresso.obrigatorios_pendentes;

  return (
    <>
      <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      {/* Cabeçalho: de quem é o caso e quanto falta, numa frase. */}
      <div className="mb-4 rounded-cartao border border-borda-forte bg-papel px-6 py-5 shadow-cartao">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="m-0 mr-2 text-xl">{caso.cliente}</h2>
          <Selo tom="info">{categoria.nome}</Selo>
          {categorias && categorias.length > 0 && onTrocarCategoria && !mostrarTroca && (
            <Botao variante="texto" pequeno onClick={() => setMostrarTroca(true)}>
              trocar o tipo de ação
            </Botao>
          )}
        </div>
        {mostrarTroca && categorias && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <CampoSeletor
              aria-label="Tipo de ação do caso"
              value={categoria.codigo}
              disabled={trocandoTipo}
              onChange={(e) => void trocarCategoria(e.target.value)}
            >
              {categorias.map((c) => (
                <option key={c.codigo} value={c.codigo}>
                  {c.nome}
                </option>
              ))}
            </CampoSeletor>
            <Botao variante="texto" pequeno onClick={() => setMostrarTroca(false)}>
              cancelar
            </Botao>
            {trocandoTipo && <span className="text-xs text-tinta-3">Trocando…</span>}
          </div>
        )}
        {erroTroca && (
          <div className="mt-3">
            <Aviso tom="critico" titulo="O tipo do caso não foi trocado">
              {erroTroca}
            </Aviso>
          </div>
        )}

        <p className={`m-0 mt-4 text-lg font-semibold ${faltam > 0 ? "text-tinta" : "text-ok"}`}>
          {faltam > 0
            ? `Faltam ${faltam} ${faltam === 1 ? "documento obrigatório" : "documentos obrigatórios"}`
            : "✓ Todos os documentos obrigatórios chegaram"}
        </p>
        <div
          className="mt-2 h-3 overflow-hidden rounded-pill bg-papel-3"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progresso.percentual_obrigatorios}
          aria-label="Documentos obrigatórios recebidos"
        >
          <i
            className="block h-full rounded-pill bg-acao transition-[width] duration-[240ms]"
            style={{ width: `${Math.max(0, Math.min(100, progresso.percentual_obrigatorios))}%` }}
          />
        </div>
        <p className="m-0 mt-1 text-xs text-tinta-3">
          {progresso.obrigatorios_recebidos ?? progresso.obrigatorios_entregues} de {progresso.obrigatorios_total} obrigatórios
          recebidos
        </p>
      </div>

      {erro && (
        <div className="mb-4">
          <Aviso tom="critico" titulo="Não deu certo">
            {erro}
          </Aviso>
        </div>
      )}

      {/* Trilha: onde o caso está e o que vem depois. Clicar leva a qualquer passo. */}
      <nav aria-label="Passos da documentação" className="mb-4">
        <ol className="m-0 grid list-none grid-cols-4 gap-2 p-0 max-[720px]:grid-cols-2">
          {PASSOS.map((p, n) => {
            const ativo = p.id === atual;
            const ok = feito[p.id];
            return (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setEscolhido(p.id)}
                  aria-current={ativo ? "step" : undefined}
                  className={`flex h-full w-full cursor-pointer items-center gap-3 rounded-campo border-2 px-3 py-3 text-left transition-colors ${
                    ativo ? "border-acao bg-acao-clara" : "border-borda bg-papel hover:border-acao-borda"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`grid h-8 w-8 flex-none place-items-center rounded-full text-sm font-bold ${
                      ok ? "bg-ok text-papel" : ativo ? "bg-acao text-papel" : "border-2 border-borda-forte text-tinta-3"
                    }`}
                  >
                    {ok ? "✓" : n + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-xs text-tinta-3">
                      {ok ? "Feito" : `Passo ${n + 1}`}
                      {p.id === "analise" && analise.status === "ready" && analise.pendencias > 0
                        ? ` · ${analise.pendencias} para resolver`
                        : ""}
                    </span>
                    <span className="block text-sm font-semibold leading-tight text-tinta">{p.curto}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      {/* O passo aberto. */}
      <section
        aria-labelledby="titulo-passo"
        className="rounded-cartao border border-borda-forte border-l-4 border-l-acao bg-papel px-6 py-5 shadow-cartao"
      >
        <p className="m-0 text-xs font-semibold uppercase tracking-wide text-acao">
          Passo {indiceAtual + 1} de {PASSOS.length}
          {atual === automatico && !feito[atual] ? " · é aqui que o caso está" : ""}
        </p>
        <h3 id="titulo-passo" className="m-0 mb-3 mt-1 text-xl font-semibold text-tinta">
          {PASSOS[indiceAtual].titulo}
        </h3>

        {atual === "juntar" && (
          <>
            <Instrucoes
              passos={[
                "Arraste para o quadro abaixo todos os arquivos que o cliente mandou (fotos, PDFs, áudios).",
                "Não precisa dizer qual é qual: o sistema reconhece cada documento sozinho.",
                "Se o cliente ainda vai mandar, abra “Pedir os documentos ao cliente”, lá embaixo.",
              ]}
            />
            <EnvioEmLote onEnviar={onEnviarLote} enviando={enviando === "__lote__"} />

            <div className="mt-5">
              {pendentesObrigatorios.length > 0 ? (
                <>
                  <h4 className="m-0 mb-2 text-base font-semibold text-tinta">
                    Ainda faltam estes ({pendentesObrigatorios.length}):
                  </h4>
                  <ListaDeItens>{pendentesObrigatorios.map(linha)}</ListaDeItens>
                </>
              ) : (
                <Aviso tom="ok" titulo="Todos os documentos obrigatórios chegaram">
                  Pode ir para o passo 2.
                </Aviso>
              )}
            </div>

            <div className="mt-4 space-y-3">
              {pendentesOpcionais.length > 0 && (
                <Recolhido titulo={`Documentos opcionais que ainda não chegaram (${pendentesOpcionais.length})`}>
                  <ListaDeItens>{pendentesOpcionais.map(linha)}</ListaDeItens>
                </Recolhido>
              )}
              <Recolhido titulo="Pedir os documentos ao cliente (WhatsApp ou link)">
                <div className="flex flex-col gap-4">
                  <PedidoCliente
                    casoId={caso.id}
                    progresso={progresso}
                    naoResolvidos={itens.filter((i) => i.status !== "entregue").length}
                  />
                  <PainelPortal casoId={caso.id} />
                </div>
              </Recolhido>
            </div>
          </>
        )}

        {atual === "conferir" && (
          <>
            <Instrucoes
              passos={[
                <>
                  Em cada documento abaixo, clique em <strong>Ver o que foi lido</strong>.
                </>,
                "Veja se o arquivo é mesmo aquele documento e se dá para ler.",
                <>
                  Está no lugar errado? Clique em <strong>Corrigir classificação</strong>. Está ilegível? Clique em{" "}
                  <strong>Remover</strong> e peça outro ao cliente.
                </>,
              ]}
            />

            {lendo > 0 && (
              <div className="mb-4">
                <Aviso tom="info" titulo={`${lendo} documento(s) ainda sendo lidos`}>
                  Espere um pouco. A tela atualiza sozinha quando terminar.
                </Aviso>
              </div>
            )}

            {aConferir.length > 0 && (
              <div className="mb-4">
                <h4 className="m-0 mb-2 text-base font-semibold text-tinta">Confira estes ({aConferir.length}):</h4>
                <ListaDeItens>{aConferir.map(linha)}</ListaDeItens>
              </div>
            )}

            {triagem.length > 0 && (
              <div className="mb-4">
                <h4 className="m-0 mb-1 text-base font-semibold text-tinta">
                  Arquivos que o sistema não reconheceu ({triagem.length})
                </h4>
                <p className="m-0 mb-2 text-sm text-tinta-2">Diga qual documento é cada um, escolhendo na lista.</p>
                <TriagemDocumentos entregas={triagem} itens={itens} onAtribuir={onReatribuir} onRemover={onRemover} />
              </div>
            )}

            {(comErro > 0 || triagem.length > 0) && (
              <div className="mb-4">
                <Aviso tom="atencao" titulo={comErro > 0 ? `${comErro} arquivo(s) deram erro na leitura` : "Quer tentar reconhecer de novo?"}>
                  <p className="m-0">Clique abaixo para o sistema ler esses arquivos outra vez.</p>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <BotaoProcesso
                      variante="secundario"
                      pequeno
                      onClick={reanalisar}
                      processando={reanalisando}
                      textoProcessando="Mandando ler de novo…"
                    >
                      Ler de novo
                    </BotaoProcesso>
                    {resultadoReanalise && <span className="text-sm text-tinta-2">{resultadoReanalise}</span>}
                  </div>
                </Aviso>
              </div>
            )}

            {feito.conferir && (
              <Aviso tom="ok" titulo="Nada para conferir">
                Todos os arquivos foram lidos e estão no lugar certo. Pode ir para o passo 3.
              </Aviso>
            )}
            {totalArquivos === 0 && (
              <Aviso tom="info" titulo="Ainda não chegou nenhum arquivo">
                Volte ao passo 1 e envie os documentos.
              </Aviso>
            )}
          </>
        )}

        {/* A análise fica montada o tempo todo para a trilha saber se ela terminou; começa sozinha
          * quando os obrigatórios chegam ou quando a pessoa abre este passo. */}
        <div hidden={atual !== "analise"}>
          <Instrucoes
            passos={[
              "O sistema lê todos os documentos juntos e procura o que está errado ou faltando.",
              "Faça o que aparecer em “O que fazer agora”, de cima para baixo.",
              "Quando não houver mais nada para fazer, siga para o passo 4.",
            ]}
          />
          <PainelAnaliseDocumental
            casoId={caso.id}
            iniciarSozinho={feito.juntar || atual === "analise"}
            mostrarContinuar={false}
            onStatus={aoMudarAnalise}
          />
        </div>

        {atual === "baixar" && (
          <>
            <Instrucoes
              passos={[
                "Clique no botão abaixo.",
                "O sistema junta todos os documentos num arquivo .zip, na ordem da lista.",
                "O arquivo vai para a pasta Downloads do computador.",
              ]}
            />
            {!progresso.pronto && (
              <div className="mb-3">
                <Aviso tom="atencao" titulo="Ainda falta coisa">
                  Dá para baixar o que já chegou, mas o pacote vai sair incompleto.
                </Aviso>
              </div>
            )}
            {totalArquivos > 0 ? (
              <BaixarDocumentos casoId={caso.id} total={totalArquivos} pronto={progresso.pronto} />
            ) : (
              <Aviso tom="info" titulo="Nenhum arquivo para baixar">
                Envie os documentos no passo 1.
              </Aviso>
            )}
          </>
        )}

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-borda pt-4">
          {indiceAtual > 0 ? (
            <Botao variante="secundario" onClick={() => setEscolhido(PASSOS[indiceAtual - 1].id)}>
              ← Voltar ao passo {indiceAtual}
            </Botao>
          ) : (
            <span />
          )}
          {indiceAtual < PASSOS.length - 1 && (
            <Botao
              variante={feito[atual] ? "primario" : "secundario"}
              onClick={() => setEscolhido(PASSOS[indiceAtual + 1].id)}
            >
              Ir para o passo {indiceAtual + 2}: {PASSOS[indiceAtual + 1].curto} →
            </Botao>
          )}
        </div>
      </section>

      {/* O que não é passo: fica recolhido, à mão de quem procura. */}
      <div className="mt-5 space-y-3">
        <Recolhido titulo={`Ver todos os documentos do caso (${itens.length})`}>
          <TodosOsDocumentos itens={itens} casoId={caso.id} linha={linha} />
        </Recolhido>
        <Recolhido titulo="Ficha do cliente (dados lidos dos documentos)">
          <ResumoDocumentos itens={itens} />
        </Recolhido>
        <Recolhido titulo="Quanto tempo processos parecidos levam">
          <Prazos />
        </Recolhido>
      </div>

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
    </>
  );
}

/** A lista completa, com busca pelo nome e pelo que está escrito dentro dos arquivos. */
function TodosOsDocumentos({
  itens,
  casoId,
  linha,
}: {
  itens: ItemSituacao[];
  casoId: string;
  linha: (item: ItemSituacao) => ReactNode;
}) {
  const [busca, setBusca] = useState("");
  const [noConteudo, setNoConteudo] = useState<{ consulta: string; codigos: Set<string> } | null>(null);

  useEffect(() => {
    const consulta = busca.trim();
    if (consulta.length < 2) {
      setNoConteudo(null);
      return;
    }
    const controle = new AbortController();
    const espera = window.setTimeout(() => {
      buscarNoConteudoDoCaso(casoId, consulta, controle.signal)
        .then((r) => setNoConteudo({ consulta, codigos: new Set(r.flatMap((x) => x.itens)) }))
        .catch(() => {
          if (!controle.signal.aborted) setNoConteudo(null);
        });
    }, 300);
    return () => {
      window.clearTimeout(espera);
      controle.abort();
    };
  }, [busca, casoId]);

  const termos = normalizar(busca).split(/\s+/).filter(Boolean);
  const achadosDentro = noConteudo && noConteudo.consulta === busca.trim() ? noConteudo.codigos : null;
  const visiveis = termos.length
    ? itens.filter((item) => {
        const texto = normalizar(
          [item.nome, item.tipo_documento ?? "", ...item.entregas.map((e) => e.arquivo)].join(" "),
        );
        return termos.every((t) => texto.includes(t)) || Boolean(achadosDentro?.has(item.codigo));
      })
    : itens;

  return (
    <>
      <input
        type="search"
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
        placeholder="Procurar: RG, CPF, laudo, ou algo escrito no documento"
        aria-label="Procurar documento"
        className="mb-3 w-full rounded-campo border-2 border-borda-campo bg-papel px-3 py-2 text-base focus:border-acao focus:outline-none"
      />
      {visiveis.length === 0 ? (
        <p className="m-0 text-sm text-tinta-3">Nenhum documento encontrado com “{busca.trim()}”.</p>
      ) : (
        <ListaDeItens>{visiveis.map(linha)}</ListaDeItens>
      )}
    </>
  );
}
