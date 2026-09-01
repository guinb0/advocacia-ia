"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  type LucideIcon,
} from "lucide-react";

import type { Tela } from "@/app/home/home.model";
import { gruposPermitidos, ICONE_POR_TELA } from "@/components/layout/BarraLateral";
import type { TomSelo } from "@/lib/formato";
import { useSessao } from "@/lib/auth";
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

interface AtalhoCarteira {
  rotulo: string;
  apoio: string;
  Icone: LucideIcon;
  onClick: () => void;
}

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
  onNavegar: (tela: Tela) => void;
}

export default function Carteira({
  onAbrir,
  onNovoCaso,
  onNavegar,
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
  const atalhos: AtalhoCarteira[] = gruposPermitidos(sessao.carregando ? [] : sessao.modulos)
    .flatMap((grupo) => grupo.itens)
    .map((item) => ({
      rotulo: item.rotulo,
      apoio: APOIO_POR_TELA[item.tela] ?? "módulo do sistema",
      Icone: ICONE_POR_TELA[item.tela] ?? Plus,
      onClick: () => onNavegar(item.tela),
    }));

  return (
    <div className="space-y-5">
      <header className="rounded-cartao border border-borda-forte bg-papel p-5 shadow-cartao">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-tinta-3">
              Carteira
            </span>
            <h1 className="mb-0 mt-2 text-xl tracking-[-0.01em]">Mesa do dia</h1>
            <p className="mt-[6px] max-w-[68ch] text-base text-tinta-2">
              {triagem.travados > 0
                ? `${triagem.travados} ${triagem.travados === 1 ? "caso exige" : "casos exigem"} uma decisão sua hoje. Os demais seguem andando sozinhos.`
                : "Nenhum caso travado hoje. Os casos seguem andando sozinhos."}
            </p>
          </div>

          <div className="flex flex-col items-start gap-3 sm:items-end">
            <Botao variante="primario" onClick={onNovoCaso}>
              <Plus size={16} aria-hidden />
              Novo caso
            </Botao>
            <span
              className="inline-flex items-center gap-[7px] text-xs text-tinta-3"
              title="Situação do programa que lê os documentos enviados"
            >
              <span className={`h-2 w-2 flex-none rounded-full ${leitura.corPonto}`} aria-hidden />
              {leitura.texto}
              {hoje && <span className="tabular-nums">· {hoje}</span>}
            </span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,170px),1fr))] gap-3">
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

      <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel p-3 shadow-cartao" aria-label="Módulos disponíveis">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,170px),1fr))] gap-2">
          {atalhos.map((atalho) => (
            <AtalhoOperacional key={atalho.rotulo} {...atalho} />
          ))}
        </div>
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(min(100%,300px),340px)] items-start gap-6 max-[1040px]:grid-cols-1">
        <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden" aria-label="Fila de casos">
          <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-borda px-[18px] py-4">
            <div>
              <h2 className="m-0 text-lg">Fila de casos</h2>
              <p className="mb-0 mt-1 text-xs text-tinta-3">
                {triagem.ativos} {triagem.ativos === 1 ? "caso ativo" : "casos ativos"} · o que pode
                travar aparece primeiro
              </p>
            </div>
            {paginacao.total > 0 && (
              <span className="rounded-pill border border-borda bg-papel-2 px-3 py-1 text-xs text-tinta-3 tabular-nums">
                {paginacao.primeiro}–{paginacao.ultimo} de {paginacao.total}
              </span>
            )}
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
            <>
            <div className="hidden grid-cols-[minmax(0,1.35fr)_minmax(170px,0.65fr)_minmax(220px,0.8fr)] gap-4 border-b border-borda bg-papel-2 px-[18px] py-2 text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3 min-[760px]:grid">
              <span>Caso</span>
              <span>Documentos</span>
              <span>Próxima ação</span>
            </div>
            <ul className="m-0 list-none p-0" ref={listaRef}>
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
            </>
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
          <section className="overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao" aria-label="Resumo da carteira">
            <div className="border-b border-borda px-[18px] py-4">
              <h2 className="m-0 text-lg">Próximo foco</h2>
            </div>
            <div className="grid gap-3 p-[18px] text-sm">
              <LinhaResumo rotulo="Casos travados" valor={triagem.travados} tom="critico" />
              <LinhaResumo rotulo="A conferir" valor={triagem.aConferir} tom="atencao" />
              <LinhaResumo rotulo="Pedidos prontos" valor={triagem.pedidosProntos} tom="info" />
              <LinhaResumo rotulo="Instruções completas" valor={triagem.completos} tom="ok" />
            </div>
          </section>

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
                      className="flex w-full min-w-0 items-center justify-between gap-3 border-none border-b border-borda bg-transparent px-[18px] py-3 text-left [font:inherit] text-inherit transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3"
                      onClick={() => onAbrir(pedido.casoId)}
                    >
                      <span className="min-w-0 truncate text-sm font-semibold text-tinta" title={pedido.cliente}>
                        {pedido.cliente}
                      </span>
                      <span className="shrink-0 truncate text-xs text-tinta-3 tabular-nums">
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
                    className="flex min-w-0 items-center justify-between gap-[10px] border-b border-borda px-[18px] py-[11px] last:border-b-0"
                  >
                    <span className="min-w-0 truncate font-codigo text-xs text-tinta-2" title={entrega.arquivo}>
                      {entrega.arquivo}
                    </span>
                    <span className="min-w-0 max-w-[58%]" title={estagio}>
                      <Selo tom={TOM_POR_SEVERIDADE[severidade]}>{estagio}</Selo>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>

      {/* Atalhos: apoio para quem trabalha rápido, não requisito de uso. Toda
          ação daqui também existe como botão na tela. */}
      <footer className="flex gap-[18px] flex-wrap items-center pt-[2px] text-tinta-3 text-xs">
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

const APOIO_POR_TELA: Partial<Record<Tela, string>> = {
  entrevista: "iniciar atendimento",
  carteira: "mesa do dia",
  agente: "assistente geral",
  casos: "cadastro e lista",
  documentacao: "apoio documental",
  avulso: "análise avulsa",
  investigacao: "fontes e indícios",
  dados: "acervo indexado",
  panorama: "visão analítica",
  supervisao: "entrevistas",
  catalogoRoteiros: "roteiros guiados",
  usuarios: "acessos",
  saudeAgente: "integrações",
  modelosDePeticao: "petições",
};

function AtalhoOperacional({ rotulo, apoio, Icone, onClick }: AtalhoCarteira) {
  return (
    <button
      type="button"
      className="group flex min-h-[58px] min-w-0 items-center gap-3 rounded-[10px] border border-borda bg-papel-2 px-3 py-2 text-left transition-colors hover:border-acao-borda hover:bg-acao-clara"
      onClick={onClick}
    >
      <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-papel text-acao ring-1 ring-borda group-hover:ring-acao-borda">
        <Icone size={17} aria-hidden />
      </span>
      <span className="min-w-0 overflow-hidden">
        <strong className="block truncate text-sm text-tinta" title={rotulo}>{rotulo}</strong>
        <span className="block truncate text-xs text-tinta-3" title={apoio}>{apoio}</span>
      </span>
    </button>
  );
}

function LinhaResumo({
  rotulo,
  valor,
  tom,
}: {
  rotulo: string;
  valor: number;
  tom: TomSelo;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-tinta-2">{rotulo}</span>
      <Selo tom={tom}>{valor}</Selo>
    </div>
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
      <span className="min-w-0 overflow-hidden">
        <span className="block font-titulo text-[1.75rem] font-semibold leading-[1.05] text-tinta tabular-nums">
          {numero}
        </span>
        <span className="mt-[1px] block truncate text-sm font-semibold text-tinta" title={rotulo}>{rotulo}</span>
        <span className="mt-[2px] block truncate text-xs leading-[1.4] text-tinta-3" title={ajuda}>{ajuda}</span>
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
      className={`grid w-full grid-cols-1 items-center gap-x-4 gap-y-[10px] border-none border-b border-l-4 border-borda bg-transparent px-[18px] py-[14px] text-left [font:inherit] text-inherit transition-[background-color] duration-[120ms] ease-[ease] hover:bg-papel-3 min-[760px]:grid-cols-[minmax(0,1.35fr)_minmax(170px,0.65fr)_minmax(220px,0.8fr)] ${
        selecionada ? "bg-acao-clara" : ""
      }`}
      style={{ borderLeftColor: corBordaLinha(linha.severidade, selecionada) }}
      onClick={onAbrir}
      onFocus={onFocar}
    >
      <span className="flex min-w-0 flex-col gap-[3px]">
        <span className="truncate text-md font-semibold leading-[1.3] text-tinta" title={`${linha.caso.cliente} · ${linha.categoriaNome}`}>
          {linha.caso.cliente} <span className="text-sm font-normal text-tinta-3">· {linha.categoriaNome}</span>
        </span>
        <span className="truncate text-sm leading-[1.45] text-tinta-2" title={linha.frase}>{linha.frase}</span>
        <span className="text-xs text-tinta-3 tabular-nums">
          Atualizado {linha.diasParado === 0 ? "hoje" : linha.diasParado === 1 ? "há 1 dia" : `há ${linha.diasParado} dias`}
        </span>
      </span>

      <span className="min-w-0">
        <span className="block text-tinta-2 text-xs tabular-nums">
          {progresso.obrigatorios_entregues} de {progresso.obrigatorios_total} obrigatórios
        </span>
        <span className="mt-[5px] block h-[6px] overflow-hidden rounded-pill bg-papel-3">
          <i className="block h-full rounded-pill bg-acao" style={{ width: `${pct}%` }} />
        </span>
      </span>

      <span className="flex min-w-0 items-center justify-start gap-[10px] min-[760px]:justify-end">
        <span className="shrink-0 text-xs text-tinta-3 tabular-nums">
          {pct}%
        </span>
        <span className="shrink-0">
          <span className="block text-tinta-2 text-xs tabular-nums">
            {progresso.obrigatorios_pendentes} pend.
          </span>
        </span>
        <span className="min-w-0 max-w-full" title={linha.acao.rotulo}>
          <Selo tom={TOM_POR_SEVERIDADE[linha.severidade]} simbolo={linha.acao.simbolo}>
            {linha.acao.rotulo}
          </Selo>
        </span>
      </span>
    </button>
  );
}
