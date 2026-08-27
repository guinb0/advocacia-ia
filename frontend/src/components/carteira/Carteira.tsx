"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AUTH_ATIVA, useSessao } from "@/lib/auth";
import type { TomSelo } from "@/lib/formato";
import type { LinhaCarteira, Severidade } from "@/lib/useCarteira";
import { useCarteira } from "@/lib/useCarteira";
import type { EstadoModelo } from "@/lib/useExtracao";
import { useModelo } from "@/lib/useExtracao";
import { Aviso, Botao, Selo } from "@/components/ui/Basicos";

/* Estado da leitura automática, em português de quem usa. "modelo pronto" e
 * "modelo carrega no 1º envio" diziam respeito ao PaddleOCR, não ao trabalho. */
const TEXTO_LEITURA: Record<EstadoModelo, { texto: string; corPonto: string }> = {
  verificando: { texto: "Verificando a leitura automática", corPonto: "bg-atencao-marca" },
  carregando: { texto: "Preparando a leitura automática", corPonto: "bg-atencao-marca" },
  pronto: { texto: "Leitura automática pronta", corPonto: "bg-ok" },
  indisponivel: { texto: "Leitura inicia no primeiro envio", corPonto: "bg-tinta-3" },
};

type Filtro = "todos" | "critico" | "atencao" | "pedido" | "pronto";

/** Frase que explica, na faixa acima da lista, o filtro que está aplicado. */
const DESCRICAO_FILTRO: Record<Exclude<Filtro, "todos">, string> = {
  critico: "casos travados esperando uma decisão sua",
  atencao: "casos com documento a conferir",
  pedido: "casos com pedido pronto para enviar ao cliente",
  pronto: "casos com a instrução completa",
};

/** Tom do selo por gravidade — o mesmo vocabulário dos primitivos globais. */
const TOM_POR_SEVERIDADE: Record<Severidade, TomSelo> = {
  critico: "critico",
  atencao: "atencao",
  pronto: "ok",
  neutro: "info",
};

/* Cada gravidade pinta apenas a faixa lateral e o disco do símbolo do cartão de
 * triagem — nunca o texto inteiro, que precisa continuar em tinta legível. */
const BORDA_TRIAGEM: Record<Severidade, string> = {
  critico: "var(--critico)",
  atencao: "var(--atencao-marca)",
  pronto: "var(--ok)",
  neutro: "var(--acao)",
};
const SIMBOLO_TRIAGEM: Record<Severidade, string> = {
  critico: "bg-critico-claro text-critico",
  atencao: "bg-atencao-claro text-atencao",
  pronto: "bg-ok-claro text-ok",
  neutro: "bg-acao-clara text-acao",
};

/** Cor da faixa lateral da linha da fila. Réplica exata do CSS original: a
 * cor de gravidade (quando há uma) sempre vence a cor de "selecionada pelo
 * teclado" — só pronto/neutro (sem gravidade própria) mostram o azul de ação
 * quando selecionados. */
function corBordaLinha(severidade: Severidade, selecionada: boolean): string {
  if (severidade === "critico") return "var(--critico)";
  if (severidade === "atencao") return "var(--atencao-marca)";
  return selecionada ? "var(--acao)" : "transparent";
}

const HOJE_FORMATO = new Intl.DateTimeFormat("pt-BR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

interface Props {
  onAbrir: (casoId: string) => void;
  onNovoCaso: () => void;
  onAnalisarAvulso: () => void;
  onInvestigar: () => void;
  onUsuarios: () => void;
  onEntrevista: () => void;
  onSupervisao: () => void;
  onDados: () => void;
  onPanorama: () => void;
  onSaudeAgente: () => void;
  onModelosDePeticao: () => void;
}

export default function Carteira({
  onAbrir,
  onNovoCaso,
  onAnalisarAvulso,
  onInvestigar,
  onUsuarios,
  onEntrevista,
  onSupervisao,
  onDados,
  onPanorama,
  onSaudeAgente,
  onModelosDePeticao,
}: Props) {
  const { linhas, triagem, chegandoAgora, pedidos, carregando, erro, paginacao, irPara } =
    useCarteira();
  const estadoModelo = useModelo();
  const sessao = useSessao();

  /* A rota é prerenderizada: formatar a data no corpo do componente gravaria a
   * data do build no HTML e ela só mudaria no próximo deploy. Só depois de
   * montar é que existe "hoje". */
  const [hoje, setHoje] = useState("");
  useEffect(() => setHoje(HOJE_FORMATO.format(new Date())), []);
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [selecionado, setSelecionado] = useState(0);
  const listaRef = useRef<HTMLUListElement>(null);

  const visiveis = linhas.filter((linha) => {
    if (filtro === "todos") return true;
    if (filtro === "pedido") return linha.situacao.progresso.obrigatorios_pendentes > 0;
    if (filtro === "pronto") return linha.situacao.progresso.pronto;
    return linha.severidade === filtro;
  });

  // Um filtro que encolhe a lista pode deixar o cursor fora dela.
  useEffect(() => {
    setSelecionado((atual) => Math.min(atual, Math.max(0, visiveis.length - 1)));
  }, [visiveis.length]);

  // Página nova, lista nova: o cursor volta para o topo dela.
  useEffect(() => setSelecionado(0), [paginacao.pagina]);

  const alternarFiltro = useCallback((alvo: Filtro) => {
    setFiltro((atual) => (atual === alvo ? "todos" : alvo));
    setSelecionado(0);
  }, []);

  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      // Não sequestrar o teclado enquanto o usuário digita em algum campo.
      const alvo = evento.target as HTMLElement | null;
      if (alvo && /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName)) return;
      if (evento.metaKey || evento.ctrlKey || evento.altKey) return;

      const atual = visiveis[selecionado];
      // Em botão/link o próprio navegador dispara o clique no Enter; tratar aqui
      // também abriria o caso selecionado junto com a ação em foco.
      const emControle = !!alvo?.closest("button, a, [role='tab']");

      if (evento.key === "ArrowDown") {
        evento.preventDefault();
        setSelecionado((i) => Math.min(i + 1, visiveis.length - 1));
      } else if (evento.key === "ArrowUp") {
        evento.preventDefault();
        setSelecionado((i) => Math.max(i - 1, 0));
      } else if (evento.key === "Enter") {
        if (emControle || !atual) return;
        evento.preventDefault();
        onAbrir(atual.caso.id);
      } else if (evento.key === "Escape") {
        setFiltro("todos");
      } else if (evento.key.toLowerCase() === "c") {
        alternarFiltro("atencao");
      } else if (evento.key.toLowerCase() === "p") {
        alternarFiltro("pedido");
      } else if (evento.key.toLowerCase() === "n") {
        onNovoCaso();
      }
    }

    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [visiveis, selecionado, onAbrir, onNovoCaso, alternarFiltro]);

  // Mantém a linha do cursor visível quando a navegação passa da dobra. O
  // backend já entrega apenas os itens da página atual.
  useEffect(() => {
    const item = listaRef.current?.children[selecionado] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selecionado]);

  const leitura = TEXTO_LEITURA[estadoModelo];

  return (
    <div className="min-h-screen bg-fundo">
      <header className="flex justify-between items-center gap-6 px-7 py-3 border-b border-borda bg-papel flex-wrap">
        <div className="flex items-center gap-7 flex-wrap">
          <span className="text-tinta font-titulo text-[1.25rem] font-bold tracking-[-0.01em]">Acervo</span>
          {/* Os módulos saíram daqui e viraram a barra lateral, que existe em
            * TODAS as telas — ver `components/layout/BarraLateral.tsx`. Onze
            * botões nesta faixa quebravam em duas linhas num notebook e
            * empurravam a Mesa do dia para baixo da dobra; num celular
            * ocupavam a tela inteira antes de qualquer conteúdo. O que fica
            * aqui é o estado do sistema, que é desta tela. */}
        </div>

        <div className="flex items-center gap-[14px] flex-wrap">
          <span
            className="inline-flex items-center gap-[7px] text-tinta-3 text-xs"
            title="Situação do programa que lê os documentos enviados"
          >
            <span className={`flex-none w-2 h-2 rounded-full ${leitura.corPonto}`} aria-hidden />
            {leitura.texto}
          </span>
          {hoje && <span className="text-tinta-3 text-xs tabular-nums">{hoje}</span>}
          {AUTH_ATIVA && (
            <Botao variante="discreto" pequeno onClick={sessao.sair}>
              Sair ({sessao.nome || sessao.usuario})
            </Botao>
          )}
        </div>
      </header>

      <div className="flex justify-between items-end gap-6 max-w-[1440px] px-4 sm:px-7 pt-7 flex-wrap">
        <div>
          <h1 className="m-0 text-xl tracking-[-0.01em]">Mesa do dia</h1>
          <p className="mt-[6px] mb-0 max-w-[62ch] text-tinta-2 text-base">
            {triagem.travados > 0
              ? `${triagem.travados} ${triagem.travados === 1 ? "caso exige" : "casos exigem"} uma decisão sua hoje. Os demais seguem andando sozinhos.`
              : "Nenhum caso travado hoje. Os casos seguem andando sozinhos."}
          </p>
        </div>

        {/* A ação principal da tela, em botão sólido. Antes era um item de menu
            em caixa alta, indistinguível dos outros. */}
        <Botao variante="primario" onClick={onNovoCaso}>
          + Novo caso
        </Botao>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3 max-w-[1440px] px-4 sm:px-7 pt-[18px]">
        <CartaoTriagem
          numero={triagem.travados}
          rotulo="Travados"
          ajuda="Esperando uma decisão sua"
          simbolo="✕"
          severidade="critico"
          ativo={filtro === "critico"}
          onClick={() => alternarFiltro("critico")}
        />
        <CartaoTriagem
          numero={triagem.aConferir}
          rotulo="A conferir"
          ajuda="Documento ilegível ou trocado"
          simbolo="!"
          severidade="atencao"
          ativo={filtro === "atencao"}
          onClick={() => alternarFiltro("atencao")}
        />
        <CartaoTriagem
          numero={triagem.pedidosProntos}
          rotulo="Pedidos prontos"
          ajuda="Para enviar ao cliente"
          simbolo="→"
          severidade="neutro"
          ativo={filtro === "pedido"}
          onClick={() => alternarFiltro("pedido")}
        />
        <CartaoTriagem
          numero={triagem.completos}
          rotulo="Completos"
          ajuda="Prontos para a inicial"
          simbolo="✓"
          severidade="pronto"
          ativo={filtro === "pronto"}
          onClick={() => alternarFiltro("pronto")}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_330px] max-[1040px]:grid-cols-1 gap-6 max-w-[1440px] px-4 sm:px-7 pt-[22px] pb-10 items-start">
        <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden" aria-label="Fila de casos">
          <div className="flex justify-between items-baseline gap-4 px-[18px] py-4 border-b border-borda flex-wrap">
            <h2 className="m-0 text-lg">Fila de casos</h2>
            <span className="text-tinta-3 text-xs">
              {triagem.ativos} {triagem.ativos === 1 ? "caso ativo" : "casos ativos"} · o que pode
              travar aparece primeiro
              {paginacao.total > 0 && (
                <> · mostrando {paginacao.primeiro}–{paginacao.ultimo}</>
              )}
            </span>
          </div>

          {/* Filtro aplicado dito em palavras, com o desfazer ao lado. */}
          {filtro !== "todos" && (
            <div className="flex justify-between items-center gap-3 px-[18px] py-[10px] border-b border-acao-borda bg-acao-clara text-acao text-sm font-semibold flex-wrap">
              <span>
                Mostrando {visiveis.length} de {linhas.length} nesta página —{" "}
                {DESCRICAO_FILTRO[filtro]}
              </span>
              <Botao variante="secundario" pequeno onClick={() => setFiltro("todos")}>
                Ver todos os casos
              </Botao>
            </div>
          )}

          {erro && (
            <div className="px-[18px] py-4">
              <Aviso tom="critico" titulo="Não foi possível carregar a carteira">
                {erro}
              </Aviso>
            </div>
          )}

          {carregando && linhas.length === 0 ? (
            <div aria-live="polite">
              <p className="px-[18px] py-8 text-tinta-3 text-sm leading-[1.6] text-center">Carregando os casos…</p>
              <div className="h-[62px] border-b border-borda bg-[linear-gradient(90deg,var(--papel-2),var(--papel-3),var(--papel-2))] [background-size:200%_100%] animate-[brilho_1.4s_ease-in-out_infinite]" />
              <div className="h-[62px] border-b border-borda bg-[linear-gradient(90deg,var(--papel-2),var(--papel-3),var(--papel-2))] [background-size:200%_100%] animate-[brilho_1.4s_ease-in-out_infinite]" />
              <div className="h-[62px] border-b border-borda bg-[linear-gradient(90deg,var(--papel-2),var(--papel-3),var(--papel-2))] [background-size:200%_100%] animate-[brilho_1.4s_ease-in-out_infinite]" />
            </div>
          ) : visiveis.length === 0 ? (
            <div className="px-[18px] py-11 text-center">
              {linhas.length === 0 ? (
                <>
                  <h3 className="mb-[6px] mt-0 text-tinta text-lg">Nenhum caso cadastrado</h3>
                  <p className="mx-auto mb-[18px] mt-0 max-w-[46ch] text-tinta-3 text-sm">
                    Crie o primeiro caso para montar o checklist de documentos e começar a
                    cobrá-los do cliente.
                  </p>
                  <Botao variante="primario" onClick={onNovoCaso}>
                    Criar o primeiro caso
                  </Botao>
                </>
              ) : (
                <>
                  <h3 className="mb-[6px] mt-0 text-tinta text-lg">Nada neste filtro</h3>
                  <p className="mx-auto mb-[18px] mt-0 max-w-[46ch] text-tinta-3 text-sm">
                    {filtro === "todos"
                      ? "Nenhum caso a mostrar."
                      : `Nenhum caso se encaixa em: ${DESCRICAO_FILTRO[filtro]}.`}
                  </p>
                  <Botao variante="secundario" onClick={() => setFiltro("todos")}>
                    Ver todos os casos
                  </Botao>
                </>
              )}
            </div>
          ) : (
            <ul className="list-none m-0 p-0" ref={listaRef}>
              {visiveis.map((linha, indice) => (
                <li key={linha.caso.id} className="last:[&>button]:border-b-0">
                  <LinhaCaso
                    linha={linha}
                    selecionada={indice === selecionado}
                    onAbrir={() => onAbrir(linha.caso.id)}
                    onFocar={() => setSelecionado(indice)}
                  />
                </li>
              ))}
            </ul>
          )}

          {/* A fila carrega 10 casos por vez: a ordem por risco e os contadores
            * do topo são medidos no servidor sobre a carteira inteira, então
            * virar de página não muda o que a triagem diz. */}
          {paginacao.paginas > 1 && (
            <nav
              className="flex justify-between items-center gap-3 px-[18px] py-3 border-t border-borda flex-wrap"
              aria-label="Páginas da fila de casos"
            >
              <span className="text-tinta-3 text-xs" aria-live="polite">
                Página {paginacao.pagina} de {paginacao.paginas} · casos {paginacao.primeiro}–
                {paginacao.ultimo} de {paginacao.total}
              </span>
              <div className="flex items-center gap-2">
                <Botao
                  variante="secundario"
                  pequeno
                  onClick={() => irPara(paginacao.pagina - 1)}
                  disabled={paginacao.pagina <= 1 || carregando}
                >
                  ← Anterior
                </Botao>
                <Botao
                  variante="secundario"
                  pequeno
                  onClick={() => irPara(paginacao.pagina + 1)}
                  disabled={paginacao.pagina >= paginacao.paginas || carregando}
                >
                  Próxima →
                </Botao>
              </div>
            </nav>
          )}
        </section>

        <aside className="flex flex-col gap-[18px]">
          <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden" aria-label="Pedidos prontos para enviar">
            <div className="flex justify-between items-baseline gap-4 px-[18px] py-4 border-b border-borda flex-wrap">
              <h2 className="m-0 text-lg">Pedidos a enviar</h2>
            </div>
            {pedidos.length === 0 ? (
              <p className="px-[18px] py-8 text-tinta-3 text-sm leading-[1.6] text-center">Nada a cobrar no momento.</p>
            ) : (
              <>
                <div className="flex flex-col">
                  {pedidos.map((pedido) => (
                    <button
                      key={pedido.casoId}
                      type="button"
                      className="flex justify-between items-center gap-3 w-full px-[18px] py-3 border-none border-b border-borda bg-transparent text-left [font:inherit] text-inherit cursor-pointer transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3"
                      onClick={() => onAbrir(pedido.casoId)}
                    >
                      <span className="text-tinta text-sm font-semibold">{pedido.cliente}</span>
                      <span className="text-tinta-3 text-xs tabular-nums whitespace-nowrap">
                        {pedido.faltantes} {pedido.faltantes === 1 ? "falta" : "faltam"}
                        {pedido.reenvios > 0 &&
                          ` · ${pedido.reenvios} a conferir`}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="px-[18px] py-[14px] border-t border-borda bg-papel-2">
                  <Botao
                    variante="secundario"
                    bloco
                    pequeno
                    onClick={() => pedidos[0] && onAbrir(pedidos[0].casoId)}
                  >
                    Abrir o primeiro e revisar
                  </Botao>
                </div>
              </>
            )}
          </section>

          <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden" aria-label="Documentos que chegaram agora">
            <div className="flex justify-between items-baseline gap-4 px-[18px] py-4 border-b border-borda flex-wrap">
              <h2 className="m-0 text-lg">Chegando agora</h2>
            </div>
            {chegandoAgora.length === 0 ? (
              <p className="px-[18px] py-8 text-tinta-3 text-sm leading-[1.6] text-center">Nenhum arquivo recebido ainda.</p>
            ) : (
              <div className="flex flex-col" aria-live="polite">
                {chegandoAgora.map(({ entrega, estagio, severidade }) => (
                  <div
                    key={entrega.id}
                    className="flex items-center justify-between gap-[10px] px-[18px] py-[11px] border-b border-borda last:border-b-0"
                  >
                    <span className="min-w-0 text-tinta-2 font-codigo text-xs [overflow-wrap:anywhere]" title={entrega.arquivo}>
                      {entrega.arquivo}
                    </span>
                    <Selo tom={TOM_POR_SEVERIDADE[severidade]}>{estagio}</Selo>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>

      {/* Atalhos: apoio para quem trabalha rápido, não requisito de uso. Toda
          ação daqui também existe como botão na tela. */}
      <footer className="flex gap-[18px] flex-wrap items-center px-7 pt-[14px] pb-7 max-w-[1440px] text-tinta-3 text-xs">
        <span className="font-semibold">Atalhos do teclado (opcionais):</span>
        <span>
          <Tecla>↑↓</Tecla> navegar
        </span>
        <span>
          <Tecla>⏎</Tecla> abrir o caso
        </span>
        <span>
          <Tecla>C</Tecla> filtrar “a conferir”
        </span>
        <span>
          <Tecla>P</Tecla> filtrar “pedidos”
        </span>
        <span>
          <Tecla>N</Tecla> novo caso
        </span>
        <span>
          <Tecla>Esc</Tecla> limpar o filtro
        </span>
      </footer>
    </div>
  );
}

function Tecla({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block min-w-[22px] px-[6px] py-[1px] mr-[5px] border border-borda-forte border-b-2 rounded-[5px] bg-papel text-tinta-2 font-codigo text-[0.75rem] font-semibold text-center">
      {children}
    </span>
  );
}

function CartaoTriagem({
  numero,
  rotulo,
  ajuda,
  simbolo,
  severidade,
  ativo,
  onClick,
}: {
  numero: number;
  rotulo: string;
  ajuda: string;
  simbolo: string;
  severidade: Severidade;
  ativo: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`flex items-start gap-3 px-4 py-[14px] border rounded-cartao text-left cursor-pointer transition-[box-shadow,background-color] duration-[120ms] ease-[ease] ${
        ativo ? "bg-acao-clara shadow-cartao-forte" : "bg-papel shadow-cartao hover:shadow-cartao-forte"
      }`}
      style={
        ativo
          ? { borderColor: "var(--acao)" }
          : { borderColor: "var(--borda-forte)", borderLeftColor: BORDA_TRIAGEM[severidade], borderLeftWidth: 4 }
      }
      onClick={onClick}
      aria-pressed={ativo}
    >
      <span
        className={`flex-none grid place-items-center w-[30px] h-[30px] rounded-full text-sm font-bold ${SIMBOLO_TRIAGEM[severidade]}`}
        aria-hidden
      >
        {simbolo}
      </span>
      <span>
        <span className="block text-tinta font-titulo text-[1.75rem] font-semibold tabular-nums leading-[1.05]">
          {numero}
        </span>
        <span className="block mt-[1px] text-tinta text-sm font-semibold">{rotulo}</span>
        <span className="block mt-[2px] text-tinta-3 text-xs leading-[1.4]">{ajuda}</span>
        <span className="sr-only">
          {ativo ? " — filtro aplicado. Clique para ver todos." : " — clique para filtrar a lista."}
        </span>
      </span>
    </button>
  );
}

function LinhaCaso({
  linha,
  selecionada,
  onAbrir,
  onFocar,
}: {
  linha: LinhaCarteira;
  selecionada: boolean;
  onAbrir: () => void;
  onFocar: () => void;
}) {
  const { progresso } = linha.situacao;
  const pct = Math.max(
    0,
    Math.min(100, Math.round((progresso.obrigatorios_entregues / (progresso.obrigatorios_total || 1)) * 100)),
  );

  return (
    <button
      type="button"
      className={`grid grid-cols-[1fr_auto] max-[620px]:grid-cols-1 gap-x-4 gap-y-[6px] items-center w-full px-[18px] py-[14px] border-none border-b border-borda border-l-4 bg-transparent text-left [font:inherit] text-inherit cursor-pointer transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3 ${
        selecionada ? "bg-acao-clara" : ""
      }`}
      style={{ borderLeftColor: corBordaLinha(linha.severidade, selecionada) }}
      onClick={onAbrir}
      onFocus={onFocar}
    >
      <span className="flex flex-col gap-[3px] min-w-0">
        <span className="text-tinta text-md font-semibold leading-[1.3]">
          {linha.caso.cliente} <span className="text-tinta-3 text-sm font-normal">· {linha.categoriaNome}</span>
        </span>
        <span className="text-tinta-2 text-sm leading-[1.45]">{linha.frase}</span>
      </span>

      <span className="flex items-center gap-[14px] justify-self-end max-[620px]:justify-self-start max-[620px]:flex-wrap">
        <span className="min-w-[132px] text-right max-[620px]:text-left">
          <span className="block text-tinta-2 text-xs tabular-nums">
            {progresso.obrigatorios_entregues} de {progresso.obrigatorios_total} obrigatórios
          </span>
          <span className="h-[6px] mt-[5px] rounded-pill bg-papel-3 overflow-hidden block">
            <i className="block h-full rounded-pill bg-acao" style={{ width: `${pct}%` }} />
          </span>
        </span>

        <Selo tom={TOM_POR_SEVERIDADE[linha.severidade]} simbolo={linha.acao.simbolo}>
          {linha.acao.rotulo}
        </Selo>
      </span>
    </button>
  );
}
