"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AUTH_ATIVA, useSessao } from "@/lib/auth";
import type { LinhaCarteira, Severidade } from "@/lib/useCarteira";
import { useCarteira } from "@/lib/useCarteira";
import type { EstadoModelo } from "@/lib/useExtracao";
import { useModelo } from "@/lib/useExtracao";
import estilos from "./Carteira.module.css";

const TEXTO_MODELO: Record<EstadoModelo, string> = {
  verificando: "verificando modelo",
  carregando: "carregando modelo",
  pronto: "modelo pronto",
  indisponivel: "modelo carrega no 1º envio",
};

type Filtro = "todos" | "critico" | "atencao" | "pedido" | "pronto";

const CLASSE_SEVERIDADE: Record<Severidade, string> = {
  critico: estilos.critico,
  atencao: estilos.atencao,
  pronto: estilos.pronto,
  neutro: estilos.neutro,
};

const CLASSE_CARIMBO: Record<Severidade, string> = {
  critico: estilos.carimboCritico,
  atencao: estilos.carimboAtencao,
  pronto: estilos.carimboPronto,
  neutro: estilos.carimboNeutro,
};

const CLASSE_LINHA: Partial<Record<Severidade, string>> = {
  critico: estilos.linhaCritica,
  atencao: estilos.linhaAtencao,
};

const HOJE_FORMATO = new Intl.DateTimeFormat("pt-BR", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
});

interface Props {
  onAbrir: (casoId: string) => void;
  onNovoCaso: () => void;
  onAnalisarAvulso: () => void;
}

export default function Carteira({ onAbrir, onNovoCaso, onAnalisarAvulso }: Props) {
  const { linhas, triagem, chegandoAgora, pedidos, carregando, erro } = useCarteira();
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

  // Mantém a linha do cursor visível quando a navegação passa da dobra.
  useEffect(() => {
    const item = listaRef.current?.children[selecionado] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selecionado]);

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topbar}>
        <div className={estilos.marcaGrupo}>
          <span className={estilos.marca}>ACERVO</span>
          <nav className={estilos.nav}>
            <button
              type="button"
              className={`${estilos.navItem} ${filtro !== "pedido" ? estilos.navAtivo : ""}`}
              onClick={() => setFiltro("todos")}
            >
              CARTEIRA
            </button>
            <button type="button" className={estilos.navItem} onClick={onNovoCaso}>
              CASOS
            </button>
            <button type="button" className={estilos.navItem} onClick={onAnalisarAvulso}>
              DOCUMENTOS
            </button>
            <button
              type="button"
              className={`${estilos.navItem} ${filtro === "pedido" ? estilos.navAtivo : ""}`}
              onClick={() => alternarFiltro("pedido")}
            >
              PEDIDOS
            </button>
          </nav>
        </div>
        <div className={estilos.topbarDireita}>
          <button type="button" className={estilos.busca}>
            buscar · ⌘K
          </button>
          <span
            className={`${estilos.modelo} ${estadoModelo === "pronto" ? estilos.pronto : ""}`}
            title="Estado do modelo de OCR que lê os documentos enviados"
          >
            {TEXTO_MODELO[estadoModelo]}
          </span>
          <span className={estilos.data}>{hoje}</span>
          {AUTH_ATIVA && (
            <button
              type="button"
              className={estilos.sair}
              onClick={sessao.sair}
              title={`Sessão de ${sessao.nome || sessao.usuario}`}
            >
              {sessao.usuario} · sair
            </button>
          )}
        </div>
      </header>
      <div className={estilos.filete} />

      <div className={estilos.cabecalho}>
        <div>
          <h1 className={estilos.titulo}>Mesa do dia</h1>
          <p className={estilos.linhaFina}>
            {triagem.travados > 0
              ? `${triagem.travados} ${triagem.travados === 1 ? "caso exige" : "casos exigem"} decisão sua hoje. O resto anda sozinho.`
              : "Nenhum caso travado hoje. O resto anda sozinho."}
          </p>
        </div>

        <div className={estilos.triagem}>
          <Triagem
            numero={triagem.travados}
            rotulo="casos travados esperando decisão sua"
            severidade="critico"
            ativo={filtro === "critico"}
            onClick={() => alternarFiltro("critico")}
          />
          <Triagem
            numero={triagem.aConferir}
            rotulo="documentos a conferir (ilegível ou trocado)"
            severidade="atencao"
            ativo={filtro === "atencao"}
            onClick={() => alternarFiltro("atencao")}
          />
          <Triagem
            numero={triagem.pedidosProntos}
            rotulo="pedidos ao cliente prontos para enviar"
            severidade="pronto"
            ativo={filtro === "pedido"}
            onClick={() => alternarFiltro("pedido")}
          />
          <Triagem
            numero={triagem.completos}
            rotulo="instrução completa — pronto para a inicial"
            severidade="neutro"
            ativo={filtro === "pronto"}
            onClick={() => alternarFiltro("pronto")}
          />
        </div>
      </div>

      <div className={estilos.corpo}>
        <section>
          <div className={estilos.duplo}>
            <div className={estilos.secaoTitulo}>
              <span className={estilos.rotuloSecao}>FILA POR GRAVIDADE</span>
              <span className={estilos.contagemSecao}>
                {triagem.ativos} {triagem.ativos === 1 ? "caso ativo" : "casos ativos"} · ordenado
                por risco de travar
              </span>
            </div>
          </div>

          {erro && <div className={estilos.erro}>{erro}</div>}

          {carregando && linhas.length === 0 ? (
            <div aria-live="polite">
              <span className={estilos.mensagem}>Carregando a carteira…</span>
              <div className={estilos.esqueleto} />
              <div className={estilos.esqueleto} />
              <div className={estilos.esqueleto} />
            </div>
          ) : visiveis.length === 0 ? (
            <p className={estilos.mensagem}>
              {linhas.length === 0
                ? "Nenhum caso ainda. Crie o primeiro para começar a cobrar documentos."
                : "Nenhum caso neste filtro. Clique no número de novo para ver todos."}
            </p>
          ) : (
            <ul className={estilos.fila} ref={listaRef}>
              {visiveis.map((linha, indice) => (
                <li key={linha.caso.id}>
                  <LinhaCaso
                    linha={linha}
                    indice={indice}
                    selecionada={indice === selecionado}
                    onAbrir={() => onAbrir(linha.caso.id)}
                    onFocar={() => setSelecionado(indice)}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className={estilos.lateral}>
          <div className={estilos.bloco}>
            <span className={estilos.rotuloSecao}>PEDIDOS PRONTOS PARA ENVIAR</span>
            {pedidos.length === 0 ? (
              <p className={estilos.mensagem}>Nada a cobrar no momento.</p>
            ) : (
              <>
                <div className={estilos.blocoLista}>
                  {pedidos.map((pedido) => (
                    <button
                      key={pedido.casoId}
                      type="button"
                      className={estilos.pedido}
                      onClick={() => onAbrir(pedido.casoId)}
                    >
                      <span className={estilos.pedidoCliente}>{pedido.cliente}</span>
                      <span className={estilos.pedidoContagem}>
                        {pedido.faltantes} faltantes
                        {pedido.reenvios > 0 && ` · ${pedido.reenvios} reenvios`}
                      </span>
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className={estilos.acaoLote}
                  onClick={() => pedidos[0] && onAbrir(pedidos[0].casoId)}
                >
                  Revisar e enviar os {pedidos.length} →
                </button>
              </>
            )}
          </div>

          <div className={estilos.bloco}>
            <span className={estilos.rotuloSecao}>CHEGANDO AGORA</span>
            {chegandoAgora.length === 0 ? (
              <p className={estilos.mensagem}>Nenhum arquivo recebido ainda.</p>
            ) : (
              <div className={estilos.feed} aria-live="polite">
                {chegandoAgora.map(({ entrega, estagio, severidade }) => (
                  <div key={entrega.id} className={estilos.feedItem}>
                    <span className={estilos.feedArquivo}>{entrega.arquivo}</span>
                    <span className={`${estilos.feedEstagio} ${CLASSE_SEVERIDADE[severidade]}`}>
                      {estagio}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>

      <footer className={estilos.atalhos}>
        <span>
          <span className={estilos.tecla}>↑↓</span> navegar
        </span>
        <span>
          <span className={estilos.tecla}>⏎</span> abrir caso
        </span>
        <span>
          <span className={estilos.tecla}>C</span> conferir
        </span>
        <span>
          <span className={estilos.tecla}>P</span> pedido
        </span>
        <span>
          <span className={estilos.tecla}>N</span> novo caso
        </span>
      </footer>
    </div>
  );
}

function Triagem({
  numero,
  rotulo,
  severidade,
  ativo,
  onClick,
}: {
  numero: number;
  rotulo: string;
  severidade: Severidade;
  ativo: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`${estilos.triagemItem} ${ativo ? estilos.triagemAtivo : ""}`}
      onClick={onClick}
      aria-pressed={ativo}
    >
      <span className={`${estilos.triagemNumero} ${CLASSE_SEVERIDADE[severidade]}`}>{numero}</span>
      <span className={estilos.triagemRotulo}>{rotulo}</span>
    </button>
  );
}

function LinhaCaso({
  linha,
  indice,
  selecionada,
  onAbrir,
  onFocar,
}: {
  linha: LinhaCarteira;
  indice: number;
  selecionada: boolean;
  onAbrir: () => void;
  onFocar: () => void;
}) {
  const { progresso } = linha.situacao;

  return (
    <button
      type="button"
      className={[
        estilos.linha,
        CLASSE_LINHA[linha.severidade] ?? "",
        selecionada ? estilos.linhaSelecionada : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={onAbrir}
      onFocus={onFocar}
    >
      <span className={`${estilos.indice} ${CLASSE_SEVERIDADE[linha.severidade]}`}>
        {String(indice + 1).padStart(2, "0")}
      </span>

      <span className={estilos.miolo}>
        <span className={estilos.cliente}>
          {linha.caso.cliente} <span className={estilos.categoria}>— {linha.categoriaNome}</span>
        </span>
        <span className={`${estilos.situacao} ${CLASSE_SEVERIDADE[linha.severidade]}`}>
          {linha.frase}
        </span>
      </span>

      <span className={estilos.progresso}>
        {progresso.obrigatorios_entregues}/{progresso.obrigatorios_total}
      </span>

      <span
        className={`${estilos.carimbo} ${CLASSE_CARIMBO[linha.severidade]} ${
          CLASSE_SEVERIDADE[linha.severidade]
        }`}
      >
        {linha.acao.rotulo}
      </span>
    </button>
  );
}
