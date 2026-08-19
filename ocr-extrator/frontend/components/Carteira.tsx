"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AUTH_ATIVA, useSessao } from "@/lib/auth";
import { SELO_TOM } from "@/lib/formato";
import type { LinhaCarteira, Severidade } from "@/lib/useCarteira";
import { useCarteira } from "@/lib/useCarteira";
import type { EstadoModelo } from "@/lib/useExtracao";
import { useModelo } from "@/lib/useExtracao";
import estilos from "./Carteira.module.css";

/* Estado da leitura automática, em português de quem usa. "modelo pronto" e
 * "modelo carrega no 1º envio" diziam respeito ao PaddleOCR, não ao trabalho. */
const TEXTO_LEITURA: Record<EstadoModelo, { texto: string; classe: string }> = {
  verificando: { texto: "Verificando a leitura automática", classe: estilos.estadoOcupado },
  carregando: { texto: "Preparando a leitura automática", classe: estilos.estadoOcupado },
  pronto: { texto: "Leitura automática pronta", classe: estilos.estadoPronto },
  indisponivel: { texto: "Leitura inicia no primeiro envio", classe: "" },
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
const TOM_POR_SEVERIDADE: Record<Severidade, keyof typeof SELO_TOM> = {
  critico: "critico",
  atencao: "atencao",
  pronto: "ok",
  neutro: "info",
};

const CLASSE_TRIAGEM: Record<Severidade, string> = {
  critico: estilos.critico,
  atencao: estilos.atencao,
  pronto: estilos.pronto,
  neutro: estilos.neutro,
};

const CLASSE_LINHA: Partial<Record<Severidade, string>> = {
  critico: estilos.linhaCritica,
  atencao: estilos.linhaAtencao,
};

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
}: Props) {
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

  // Mantém a linha do cursor visível quando a navegação passa da dobra.
  useEffect(() => {
    const item = listaRef.current?.children[selecionado] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selecionado]);

  const leitura = TEXTO_LEITURA[estadoModelo];

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topbar}>
        <div className={estilos.marcaGrupo}>
          <span className={estilos.marca}>Acervo</span>
          {/* Módulos. Cada item troca de tela — nenhum deles filtra a lista. */}
          <nav className={estilos.nav} aria-label="Módulos do sistema">
            <button
              type="button"
              className={`${estilos.navItem} ${estilos.navAtivo}`}
              aria-current="page"
            >
              Carteira
            </button>
            {/* Antes da lista de casos: conduzir a entrevista é o trabalho do
              * dia, e abrir caso antigo é a exceção. */}
            <button type="button" className={estilos.navItem} onClick={onEntrevista}>
              Entrevista guiada
            </button>
            <button type="button" className={estilos.navItem} onClick={onNovoCaso}>
              Casos
            </button>
            <button type="button" className={estilos.navItem} onClick={onAnalisarAvulso}>
              Ler um documento
            </button>
            <button type="button" className={estilos.navItem} onClick={onInvestigar}>
              Investigar
            </button>
            {/* Só para advogado: o backend recusa o cadastro a quem não tem o
              * papel, e um item de menu que só dá 403 é pior que item nenhum. */}
            {/* Advogado e secretário: quem lê a recomendação precisa poder
              * conferir de onde ela veio. */}
            <button type="button" className={estilos.navItem} onClick={onDados}>
              Dados
            </button>
            {/* Só o secretário: a supervisão atravessa as entrevistas de todo o
              * escritório, e o backend recusa quem não tem o papel. */}
            {sessao.papeis.includes("secretario") && (
              <button type="button" className={estilos.navItem} onClick={onSupervisao}>
                Supervisão
              </button>
            )}
            {sessao.papeis.includes("advogado") && (
              <button type="button" className={estilos.navItem} onClick={onUsuarios}>
                Usuários
              </button>
            )}
          </nav>
        </div>

        <div className={estilos.topbarDireita}>
          <span
            className={`${estilos.estadoLeitura} ${leitura.classe}`}
            title="Situação do programa que lê os documentos enviados"
          >
            <span className={estilos.pontoEstado} aria-hidden />
            {leitura.texto}
          </span>
          {hoje && <span className={estilos.data}>{hoje}</span>}
          {AUTH_ATIVA && (
            <button
              type="button"
              className="botao botao--discreto botao--pequeno"
              onClick={sessao.sair}
            >
              Sair ({sessao.nome || sessao.usuario})
            </button>
          )}
        </div>
      </header>

      <div className={estilos.cabecalho}>
        <div>
          <h1 className={estilos.titulo}>Mesa do dia</h1>
          <p className={estilos.linhaFina}>
            {triagem.travados > 0
              ? `${triagem.travados} ${triagem.travados === 1 ? "caso exige" : "casos exigem"} uma decisão sua hoje. Os demais seguem andando sozinhos.`
              : "Nenhum caso travado hoje. Os casos seguem andando sozinhos."}
          </p>
        </div>

        {/* A ação principal da tela, em botão sólido. Antes era um item de menu
            em caixa alta, indistinguível dos outros. */}
        <button type="button" className="botao botao--primario" onClick={onNovoCaso}>
          + Novo caso
        </button>
      </div>

      <div className={estilos.triagem}>
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

      <div className={estilos.corpo}>
        <section className={estilos.painel} aria-label="Fila de casos">
          <div className={estilos.painelCabecalho}>
            <h2 className={estilos.painelTitulo}>Fila de casos</h2>
            <span className={estilos.painelAjuda}>
              {triagem.ativos} {triagem.ativos === 1 ? "caso ativo" : "casos ativos"} · o que pode
              travar aparece primeiro
            </span>
          </div>

          {/* Filtro aplicado dito em palavras, com o desfazer ao lado. */}
          {filtro !== "todos" && (
            <div className={estilos.faixaFiltro}>
              <span>
                Mostrando {visiveis.length} de {linhas.length} — {DESCRICAO_FILTRO[filtro]}
              </span>
              <button
                type="button"
                className="botao botao--secundario botao--pequeno"
                onClick={() => setFiltro("todos")}
              >
                Ver todos os casos
              </button>
            </div>
          )}

          {erro && (
            <div className={estilos.caixaMensagem}>
              <div className="aviso aviso--critico" role="alert">
                <span className="avisoSimbolo" aria-hidden>
                  ✕
                </span>
                <div>
                  <strong>Não foi possível carregar a carteira</strong>
                  <br />
                  {erro}
                </div>
              </div>
            </div>
          )}

          {carregando && linhas.length === 0 ? (
            <div aria-live="polite">
              <p className={estilos.mensagem}>Carregando os casos…</p>
              <div className={estilos.esqueleto} />
              <div className={estilos.esqueleto} />
              <div className={estilos.esqueleto} />
            </div>
          ) : visiveis.length === 0 ? (
            <div className={estilos.mensagemVazia}>
              {linhas.length === 0 ? (
                <>
                  <h3 className={estilos.mensagemVaziaTitulo}>Nenhum caso cadastrado</h3>
                  <p className={estilos.mensagemVaziaTexto}>
                    Crie o primeiro caso para montar o checklist de documentos e começar a
                    cobrá-los do cliente.
                  </p>
                  <button type="button" className="botao botao--primario" onClick={onNovoCaso}>
                    Criar o primeiro caso
                  </button>
                </>
              ) : (
                <>
                  <h3 className={estilos.mensagemVaziaTitulo}>Nada neste filtro</h3>
                  <p className={estilos.mensagemVaziaTexto}>
                    {filtro === "todos"
                      ? "Nenhum caso a mostrar."
                      : `Nenhum caso se encaixa em: ${DESCRICAO_FILTRO[filtro]}.`}
                  </p>
                  <button
                    type="button"
                    className="botao botao--secundario"
                    onClick={() => setFiltro("todos")}
                  >
                    Ver todos os casos
                  </button>
                </>
              )}
            </div>
          ) : (
            <ul className={estilos.fila} ref={listaRef}>
              {visiveis.map((linha, indice) => (
                <li key={linha.caso.id}>
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
        </section>

        <aside className={estilos.lateral}>
          <section className={estilos.painel} aria-label="Pedidos prontos para enviar">
            <div className={estilos.painelCabecalho}>
              <h2 className={estilos.painelTitulo}>Pedidos a enviar</h2>
            </div>
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
                        {pedido.faltantes} {pedido.faltantes === 1 ? "falta" : "faltam"}
                        {pedido.reenvios > 0 &&
                          ` · ${pedido.reenvios} a conferir`}
                      </span>
                    </button>
                  ))}
                </div>
                <div className={estilos.rodapeBloco}>
                  <button
                    type="button"
                    className="botao botao--secundario botao--bloco botao--pequeno"
                    onClick={() => pedidos[0] && onAbrir(pedidos[0].casoId)}
                  >
                    Abrir o primeiro e revisar
                  </button>
                </div>
              </>
            )}
          </section>

          <section className={estilos.painel} aria-label="Documentos que chegaram agora">
            <div className={estilos.painelCabecalho}>
              <h2 className={estilos.painelTitulo}>Chegando agora</h2>
            </div>
            {chegandoAgora.length === 0 ? (
              <p className={estilos.mensagem}>Nenhum arquivo recebido ainda.</p>
            ) : (
              <div className={estilos.feed} aria-live="polite">
                {chegandoAgora.map(({ entrega, estagio, severidade }) => (
                  <div key={entrega.id} className={estilos.feedItem}>
                    <span className={estilos.feedArquivo} title={entrega.arquivo}>
                      {entrega.arquivo}
                    </span>
                    <span className={`selo ${SELO_TOM[TOM_POR_SEVERIDADE[severidade]]}`}>
                      {estagio}
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
      <footer className={estilos.atalhos}>
        <span className={estilos.atalhosRotulo}>Atalhos do teclado (opcionais):</span>
        <span>
          <span className={estilos.tecla}>↑↓</span> navegar
        </span>
        <span>
          <span className={estilos.tecla}>⏎</span> abrir o caso
        </span>
        <span>
          <span className={estilos.tecla}>C</span> filtrar “a conferir”
        </span>
        <span>
          <span className={estilos.tecla}>P</span> filtrar “pedidos”
        </span>
        <span>
          <span className={estilos.tecla}>N</span> novo caso
        </span>
        <span>
          <span className={estilos.tecla}>Esc</span> limpar o filtro
        </span>
      </footer>
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
      className={`${estilos.triagemItem} ${CLASSE_TRIAGEM[severidade]} ${
        ativo ? estilos.triagemAtivo : ""
      }`}
      onClick={onClick}
      aria-pressed={ativo}
    >
      <span className={estilos.triagemSimbolo} aria-hidden>
        {simbolo}
      </span>
      <span>
        <span className={estilos.triagemNumero}>{numero}</span>
        <span className={estilos.triagemRotulo}>{rotulo}</span>
        <span className={estilos.triagemAjuda}>{ajuda}</span>
        <span className="somenteLeitor">
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
      <span className={estilos.miolo}>
        <span className={estilos.cliente}>
          {linha.caso.cliente} <span className={estilos.categoria}>· {linha.categoriaNome}</span>
        </span>
        <span className={estilos.situacao}>{linha.frase}</span>
      </span>

      <span className={estilos.direita}>
        <span className={estilos.progresso}>
          <span className={estilos.progressoTexto}>
            {progresso.obrigatorios_entregues} de {progresso.obrigatorios_total} obrigatórios
          </span>
          <span className={estilos.progressoBarra}>
            <i className={estilos.progressoValor} style={{ width: `${pct}%` }} />
          </span>
        </span>

        <span className={`selo ${SELO_TOM[TOM_POR_SEVERIDADE[linha.severidade]]}`}>
          <span aria-hidden>{linha.acao.simbolo}</span>
          {linha.acao.rotulo}
        </span>
      </span>
    </button>
  );
}
