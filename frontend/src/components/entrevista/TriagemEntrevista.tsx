"use client";

import { useEffect, useRef, useState } from "react";

import { analisarEstrategia, gravarEntrevistaAoVivo, triarEntrevista } from "@/lib/api";
import { montarTranscricaoBruta, type TrechoTranscrito } from "@/lib/transcricao";
import type { CasoCriado, Categoria, Estrategia, Triagem } from "@/lib/types";
import CasoEDocumentos from "@/components/caso/CasoEDocumentos";
import { useChamada } from "@/lib/ChamadaContexto";
import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import AvaliacaoGoogle from "@/components/contrato/AvaliacaoGoogle";
import { Aviso, Botao, Campo, RotuloCampo, Selo } from "@/components/ui/Basicos";
import EntrevistaComChamada from "@/components/entrevista/EntrevistaComChamada";
import RelatorioEntrevista from "@/components/entrevista/RelatorioEntrevista";
import PainelContrato from "@/components/contrato/PainelContrato";

const OPCAO_BASE =
  "flex gap-3 items-start w-full px-[14px] py-3 border-none border-b border-borda border-l-4 bg-transparent " +
  "text-inherit [font:inherit] text-left cursor-pointer transition-[background-color] duration-[120ms] ease-[ease]";
const OPCAO_RESTING = "border-l-transparent hover:bg-papel-3";
const OPCAO_ESCOLHIDA = "border-l-ok bg-ok-claro";
const ESTADO_TEXTO = "text-tinta-3 text-xs leading-[1.55]";

/* Painel de insights de processos semelhantes: cartões de métrica + faixas de
 * dado + duas colunas de listas — classes reaproveitadas entre os vários
 * blocos de dados e listas deste painel. */
const METRICAS = "grid grid-cols-2 max-[700px]:grid-cols-1 gap-[10px]";
const METRICA_CARTAO = "p-[12px_14px] border border-borda rounded-campo bg-papel";
const METRICA_VALOR = "block text-tinta font-titulo text-lg font-semibold tabular-nums";
const METRICA_ROTULO = "block mt-[3px] text-tinta-3 text-xs leading-[1.4]";
const FAIXA_DADOS = "py-[11px] border-b border-borda";
const FAIXA_TITULO = "m-0 mb-[5px] text-tinta font-ui text-xs font-bold";
const FAIXA_TEXTO = "m-0 text-tinta-2 text-xs leading-[1.55]";
const COLUNAS_INSIGHTS = "grid grid-cols-2 max-[700px]:grid-cols-1 gap-[22px] mt-4";
const LISTA_INSIGHT = "m-0 pl-[18px]";
const ITEM_INSIGHT = "mb-2 text-tinta-2 text-xs leading-[1.55]";
const PRECEDENTES = "mt-[14px] pt-3 border-t border-borda";

/* Lê a entrevista e sugere a categoria — mas quem escolhe é o advogado.
 *
 * A sugestão nunca é aplicada sozinha: categoria errada é checklist errado, e o
 * escritório passaria a cobrar do cliente documentos que a ação não usa e a
 * ignorar os que ela exige. Por isso cada opção mostra o trecho do relato que a
 * sustentou, e a lista inteira fica clicável, não só a primeira. */
export default function TriagemEntrevista({
  onEscolher,
  onAtendimento,
  categorias,
  onCriarCaso,
}: {
  /** Tipos de ação, para criar o caso sem sair do atendimento. */
  categorias: Categoria[];
  /** Cria o caso e devolve o portal do cliente (link + senha). */
  onCriarCaso: (cliente: string, categoria: string) => Promise<CasoCriado>;
  /** Aplica a categoria (e o nome do cliente, se a entrevista trouxer). */
  onEscolher: (categoria: string, cliente?: string) => void;
  /** Em que ponto o atendimento está. A tela ao redor usa isto para tirar do
   *  caminho o que não é deste cliente (a lista de casos antigos) e para saber
   *  quando pode mostrar a chamada — durante a entrevista ela já está na
   *  coluna da direita, e desenhá-la duas vezes decodificaria o mesmo vídeo em
   *  dois lugares. */
  onAtendimento?: (fase: "nenhum" | "entrevista" | "pos-entrevista") => void;
}) {
  const [texto, setTexto] = useState("");
  const [mostrarRoteiro, setMostrarRoteiro] = useState(false);
  /* A qualificação fica guardada depois que a entrevista fecha: é ela que
   * preenche o contrato, e o relato corrido já não a tem em campos separados. */
  const [qualificacao, setQualificacao] = useState<Record<string, string | string[]> | null>(
    null,
  );
  /* O áudio sobrevive à tela em que foi gravado — pelo mesmo motivo da
   * qualificação. Sem guardar o id aqui, o arquivo continuaria no disco e
   * ninguém teria como pedi-lo: o nome dele é um uuid. */
  const [audioEntrevista, setAudioEntrevista] = useState("");
  /* A etapa do Google Meu Negócio, marcada pelo atendente. Fica AQUI e não na
   * caixa dela: voltar ao roteiro desmonta a caixa, e a marcação sumiria junto
   * — dando a etapa por pendente depois de ela ter sido cumprida. */
  const [avaliacaoConcluida, setAvaliacaoConcluida] = useState(false);
  /* A conversa como o Whisper a ouviu, guardada aqui pelo mesmo motivo da
   * qualificação: ela sobrevive ao fechamento da tela da entrevista, e é o que
   * vai para o caso. Sem isto, a entrevista conduzida pelo roteiro morria com a
   * aba e a supervisão nunca a via (ver `app/supervisao.py`). */
  const [transcricao, setTranscricao] = useState<TrechoTranscrito[]>([]);
  /* O caso, depois de criado aqui embaixo. Guardado para o encerramento poder
   * regravar a transcrição completa: o caso nasce NO MEIO do atendimento, e o
   * fechamento do roteiro — inclusive o pedido da avaliação — vem depois dele. */
  const [casoCriado, setCasoCriado] = useState("");
  /* O atendimento foi ENCERRADO no botão do fim — diferente de "fechei a tela".
   *
   * Encerrado, as etapas não se repetem aqui embaixo: elas já foram feitas lá
   * dentro, e vê-las de novo, zeradas, faz o atendente achar que perdeu tudo.
   * O que fica é o resumo e o próximo passo, que é criar o caso. */
  const [encerrado, setEncerrado] = useState(false);
  const [resultado, setResultado] = useState<Triagem | null>(null);
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [analisando, setAnalisando] = useState(false);
  const [analisandoEstrategia, setAnalisandoEstrategia] = useState(false);
  const [estrategia, setEstrategia] = useState<Estrategia | null>(null);
  const [erroEstrategia, setErroEstrategia] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // A chamada vive na raiz do app; aqui ela serve para a última etapa saber se
  // ainda há cliente na linha, e para oferecer o desligar sem sair da tela.
  const chamada = useChamada();

  /* Avisa a tela de fora em que ponto este atendimento está.
   *
   * O pós-entrevista (avaliação, relatório, contrato) é a MESMA sessão da
   * entrevista, com o cliente ainda na linha — por isso ele também conta como
   * atendimento em curso, e não como "voltou para a tela de casos". */
  const fase = mostrarRoteiro
    ? "entrevista"
    : qualificacao !== null
      ? "pos-entrevista"
      : "nenhum";
  const avisar = useRef(onAtendimento);
  avisar.current = onAtendimento;
  useEffect(() => {
    avisar.current?.(fase);
  }, [fase]);

  /* Manda a entrevista conduzida para o caso.
   *
   * Chamada duas vezes por atendimento — ao criar o caso e ao encerrar — e a
   * rota é PUT justamente por isso: `gravacao_id` é a chave, e a segunda
   * chamada REESCREVE a primeira em vez de criar outra entrevista. Sem isso, a
   * supervisão contaria o dobro do trabalho de quem conduziu.
   *
   * Falhar aqui NÃO pode desfazer o atendimento: o caso foi criado, o cliente
   * está na linha, e os documentos chegam do mesmo jeito. O que se perde é o
   * registro para a supervisão — grave, mas não na frente do cliente. */
  async function guardarEntrevista(
    casoId: string,
    trechos: TrechoTranscrito[],
    gravacaoId: string,
    concluida: boolean,
  ) {
    if (!casoId || !gravacaoId) return;
    try {
      await gravarEntrevistaAoVivo(casoId, {
        gravacao_id: gravacaoId,
        texto: montarTranscricaoBruta(trechos),
        realizada_em: new Date().toISOString().slice(0, 10),
        avaliacao_google: avaliacaoConcluida,
        concluida,
      });
    } catch (e) {
      console.error("Não foi possível guardar a entrevista no caso.", e);
    }
  }

  async function analisar(arquivo?: File) {
    if (!arquivo && !texto.trim()) return;
    const relato = arquivo ? await arquivo.text() : texto;
    setAnalisando(true);
    setAnalisandoEstrategia(true);
    setErro(null);
    setErroEstrategia(null);
    setEstrategia(null);
    setEscolhida(null);
    void analisarEstrategia(relato)
      .then(setEstrategia)
      .catch((e: unknown) =>
        setErroEstrategia(
          e instanceof Error ? e.message : "Não foi possível consultar os processos semelhantes.",
        ),
      )
      .finally(() => setAnalisandoEstrategia(false));
    try {
      const r = await triarEntrevista(texto, arquivo);
      setResultado(r);
      // Confiante aplica direto; ambíguo espera o clique.
      if (r.confiante && r.sugestoes[0]) {
        setEscolhida(r.sugestoes[0].codigo);
        onEscolher(r.sugestoes[0].codigo, r.dados.cliente);
      } else if (r.dados.cliente) {
        onEscolher("", r.dados.cliente);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível analisar a entrevista.");
      setResultado(null);
    } finally {
      setAnalisando(false);
    }
  }

  /* As etapas que vêm DEPOIS das perguntas — avaliação, relatório, documentos.
   *
   * Elas são as mesmas dentro e fora da tela da entrevista, e é por isso que
   * moram numa variável: o escritório pediu "tudo numa paulada só", então
   * durante a entrevista elas ficam logo abaixo do roteiro, na mesma rolagem, e
   * depois de fechada continuam aqui na tela de casos. Duplicar o bloco faria
   * as duas cópias divergirem no primeiro ajuste. */
  const etapasDoAtendimento = qualificacao && (
    <>
      <RelatorioEntrevista respostas={qualificacao} relato={texto} />
      <PainelContrato respostas={qualificacao} />

      {/* E o caso nasce aqui, na mesma rolagem: o portal abre com o cliente
        * ainda na linha, e o checklist recebe o que ele já tem em mãos. */}
      <CasoEDocumentos
        cliente={String(qualificacao.nome ?? "")}
        entrevistaId={audioEntrevista}
        onCasoCriado={(casoId) => {
          setCasoCriado(casoId);
          // Grava já, sem esperar o encerramento: se a aba morrer daqui para a
          // frente, a entrevista conduzida até aqui não se perde.
          return guardarEntrevista(casoId, transcricao, audioEntrevista, encerrado);
        }}
        categorias={categorias}
        sugerida={escolhida ?? undefined}
        onCriar={onCriarCaso}
        emChamada={chamada.estado !== "fora" && chamada.estado !== "encerrada"}
        onEncerrarChamada={chamada.desligar}
      />
    </>
  );

  return (
    <div className="p-4 mb-5 border border-borda rounded-campo bg-papel-2">
      {mostrarRoteiro ? (
        <EntrevistaComChamada
          /* As respostas sobem a cada mudança: é o que deixa as etapas abaixo
           * do roteiro prontas antes de a entrevista fechar. O relato e o id do
           * áudio vêm junto, pelos mesmos motivos de sempre. */
          onRespostas={(respostas, relato, entrevistaId, trechos) => {
            setTexto(relato);
            setQualificacao(respostas);
            setAudioEntrevista(entrevistaId);
            setTranscricao(trechos);
          }}
          onConcluir={(respostas, relato, entrevistaId, trechos) => {
            setTexto(relato);
            setQualificacao(respostas);
            setAudioEntrevista(entrevistaId);
            setTranscricao(trechos);
            setMostrarRoteiro(false);
            setEncerrado(true);
            // Encerrou com o caso já criado: regrava a conversa inteira, agora
            // com o fechamento do roteiro dentro dela, e libera a leitura do
            // agente. Sem caso ainda, quem grava é a criação dele, logo abaixo.
            if (casoCriado) {
              void guardarEntrevista(casoCriado, trechos, entrevistaId, true);
            }
          }}
          onFechar={() => setMostrarRoteiro(false)}
          depois={etapasDoAtendimento}
        />
      ) : (
        <Botao
          variante="secundario"
          className="mb-[14px]"
          onClick={() => {
            // Voltar é continuar: o atendimento deixa de estar encerrado e as
            // etapas voltam a ficar à mão, dentro e fora da tela.
            setEncerrado(false);
            setMostrarRoteiro(true);
          }}
        >
          {qualificacao ? "Voltar ao roteiro" : "Começar entrevista guiada"}
        </Botao>
      )}

      {/* O áudio do que acabou de ser conduzido, antes do contrato: quem sai da
        * entrevista costuma querer conferir uma fala antes de seguir. */}
      {!mostrarRoteiro && audioEntrevista && (
        <AudioDaEntrevista entrevistaId={audioEntrevista} />
      )}

      {/* Encerrado o atendimento, as etapas NÃO se repetem.
        *
        * Elas foram feitas lá dentro, na mesma rolagem da entrevista; mostrá-las
        * de novo, zeradas, faz o atendente achar que perdeu o que já tinha feito
        * — foi o que aconteceu. Fica o resumo e o próximo passo. */}
      {encerrado && !mostrarRoteiro && (
        <div className="mt-5 border-l-[3px] border-ok px-[14px] py-3 bg-papel-2 max-w-[74ch] font-normal text-[12.5px] leading-[1.6] font-ui">
          <strong>Atendimento encerrado.</strong> A gravação foi fechada e a chamada,
          desligada.{" "}
          {avaliacaoConcluida
            ? "A avaliação no Google ficou marcada como concluída."
            : "A avaliação no Google ficou EM ABERTO — se o cliente ainda está na linha, volte ao roteiro."}{" "}
          Agora crie o caso abaixo: é ele que abre o checklist e o portal para o cliente
          enviar os documentos.
        </div>
      )}

      {/* Fechou a tela sem encerrar (ou voltou para continuar): as etapas seguem
        * aqui, porque continuam por fazer. */}
      {!encerrado && !mostrarRoteiro && etapasDoAtendimento}

      <span className="block mb-1 text-tinta text-sm font-bold">Validação após a entrevista — quais ações cabem</span>
      <p className="mb-3 mt-0 max-w-[64ch] text-tinta-3 text-xs leading-[1.55]">
        Analise o relato antes de pedir a avaliação ao cliente. O sistema sugere as ações cabíveis,
        mostra o que sustenta cada uma e compara o caso com a base vetorial. A decisão final é da equipe jurídica.
      </p>

      <RotuloCampo htmlFor="relato-entrevista">Relato da entrevista</RotuloCampo>
      <Campo
        area
        id="relato-entrevista"
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder={
          "Ex.: O cliente é carteiro dos Correios há 8 anos. Durante a entrega foi abordado por dois homens armados…"
        }
      />

      <div className="flex gap-[10px] items-center flex-wrap mt-3">
        <Botao variante="secundario" onClick={() => void analisar()} disabled={analisando || !texto.trim()}>
          {analisando ? "Analisando…" : "Analisar o relato"}
        </Botao>

        <Botao variante="discreto" pequeno onClick={() => inputRef.current?.click()} disabled={analisando}>
          Enviar um arquivo .txt
        </Botao>

        <input
          ref={inputRef}
          type="file"
          accept=".txt,.md,text/plain"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void analisar(f);
            e.target.value = "";
          }}
        />

        {texto.trim() && (
          <span className="ml-auto text-tinta-3 text-xs tabular-nums">{texto.trim().length} caracteres</span>
        )}
      </div>

      {erro && (
        <div className="mt-3">
          <Aviso tom="critico" titulo="Não foi possível analisar">
            {erro}
          </Aviso>
        </div>
      )}

      {resultado && (
        <div className="mt-4 pt-[14px] border-t border-borda">
          <Aviso
            tom={resultado.confiante ? "ok" : "atencao"}
            titulo={
              resultado.confiante
                ? "Sugestão com boa margem de acerto"
                : "Sugestão incerta — confira antes de aceitar"
            }
          >
            {resultado.motivo}
            {resultado.concorrentes && (
              <span className="block mt-[6px] text-xs leading-[1.5]">
                O relato traz um quadro crônico e um acidente ao mesmo tempo. Pode ser mais de uma
                ação — vale abrir os dois casos.
              </span>
            )}
            {resultado.metodo === "pistas" && (
              <span className="block mt-[6px] text-xs leading-[1.5]">
                A classificação saiu de termos encontrados no texto, sem a leitura por
                inteligência artificial, e por isso erra mais.
              </span>
            )}
          </Aviso>

          {resultado.sugestoes.length === 0 ? (
            <p className="py-3 text-tinta-3 text-sm leading-[1.6]">
              Nenhuma sugestão. Escolha o tipo de ação no campo abaixo.
            </p>
          ) : (
            <ul className="list-none mt-3 mb-0 p-0 border border-borda rounded-campo bg-papel overflow-hidden">
              {resultado.sugestoes.map((s, i) => (
                <li key={s.codigo} className="last:[&>button]:border-b-0">
                  <button
                    type="button"
                    className={`${OPCAO_BASE} ${escolhida === s.codigo ? OPCAO_ESCOLHIDA : OPCAO_RESTING}`}
                    onClick={() => {
                      setEscolhida(s.codigo);
                      onEscolher(s.codigo, resultado.dados.cliente);
                    }}
                    aria-pressed={escolhida === s.codigo}
                  >
                    <span className="flex-none w-6 text-tinta-3 font-codigo text-xs tabular-nums pt-[3px]">
                      {i + 1}º
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="flex items-center gap-2 flex-wrap text-tinta text-base font-semibold">
                        {s.nome}
                        {escolhida === s.codigo && (
                          <Selo tom="ok" simbolo="✓">
                            escolhida
                          </Selo>
                        )}
                      </span>
                      {s.evidencias.slice(0, 2).map((ev, k) => (
                        <span
                          key={k}
                          className="block mt-1 text-tinta-2 text-xs italic leading-[1.5] [overflow-wrap:anywhere]"
                        >
                          “{ev}”
                        </span>
                      ))}
                    </span>
                    <span className="flex-none pt-[3px] text-tinta-3 text-xs tabular-nums whitespace-nowrap">
                      {s.pontos} {s.pontos === 1 ? "ponto" : "pontos"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(analisandoEstrategia || estrategia || erroEstrategia) && (
        <section className="mt-[18px] pt-4 border-t border-borda" aria-live="polite">
          <div className="flex justify-between items-baseline gap-3 flex-wrap">
            <span className="block mb-1 text-tinta text-sm font-bold">O que dizem processos semelhantes</span>
            {analisandoEstrategia && <span className={ESTADO_TEXTO}>Buscando semelhantes…</span>}
          </div>

          {erroEstrategia && !analisandoEstrategia && <p className={ESTADO_TEXTO}>{erroEstrategia}</p>}

          {estrategia && (
            <>
              <p className="my-[6px] mb-[14px] text-tinta font-titulo text-md leading-[1.5]">
                {estrategia.resumo}
              </p>

              <div className={METRICAS}>
                <div className={METRICA_CARTAO}>
                  <strong className={METRICA_VALOR}>{estrategia.estatisticas.processos_analisados}</strong>
                  <span className={METRICA_ROTULO}>processos semelhantes</span>
                </div>
                <div className={METRICA_CARTAO}>
                  <strong className={METRICA_VALOR}>{estrategia.estatisticas.desfechos_merito.percentual}%</strong>
                  <span className={METRICA_ROTULO}>procedente ou parcial entre casos julgados no mérito</span>
                </div>
              </div>

              {estrategia.estatisticas.resultados.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Desfechos na amostra</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.resultados.map((i) => `${i.nome}: ${i.quantidade} (${i.percentual}%)`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.varas.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Varas mais presentes</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.varas.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              {estrategia.estatisticas.magistrados.length > 0 && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Magistrados identificados nos documentos</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.estatisticas.magistrados.slice(0, 4).map((i) => `${i.nome} (${i.quantidade})`).join(" · ")}</p>
                </div>
              )}

              <div className={COLUNAS_INSIGHTS}>
                <div>
                  <h4 className={FAIXA_TITULO}>Próximas ações sugeridas</h4>
                  <ul className={LISTA_INSIGHT}>{estrategia.acoes.map((item, i) => <li key={i} className={ITEM_INSIGHT}><strong className="text-tinta">{item.acao} {item.forca && `· força ${item.forca}`}</strong><span className="block text-tinta-3">{item.porque} {item.aplicabilidade && ` Aplicável porque: ${item.aplicabilidade}`} {item.contrapontos && ` Contraponto: ${item.contrapontos}`} {item.precedentes.join(", ")}</span></li>)}</ul>
                </div>
                <div>
                  <h4 className={FAIXA_TITULO}>Riscos e pontos a confirmar</h4>
                  <ul className={LISTA_INSIGHT}>
                    {estrategia.riscos.map((item, i) => <li key={`r-${i}`} className={ITEM_INSIGHT}><strong className="text-tinta">{item.risco} {item.forca && `· força ${item.forca}`}</strong><span className="block text-tinta-3">{item.aplicabilidade && `Aplicável porque: ${item.aplicabilidade}. `}{item.contrapontos && `Contraponto: ${item.contrapontos}. `}{item.precedentes.join(", ")}</span></li>)}
                    {estrategia.lacunas.map((item, i) => <li key={`l-${i}`} className={ITEM_INSIGHT}>{item}</li>)}
                  </ul>
                </div>
              </div>

              {!!estrategia.divergencias?.length && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Divergências entre os processos</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.divergencias.map((d) => `${d.ponto} (favoráveis: ${d.precedentes_favoraveis.join(", ") || "—"}; contrários: ${d.precedentes_contrarios.join(", ") || "—"})`).join(" · ")}</p>
                </div>
              )}

              {!!estrategia.perguntas_criticas?.length && (
                <div className={FAIXA_DADOS}>
                  <h4 className={FAIXA_TITULO}>Perguntas críticas para a entrevista</h4>
                  <p className={FAIXA_TEXTO}>{estrategia.perguntas_criticas.join(" · ")}</p>
                </div>
              )}

              <details className={PRECEDENTES}>
                <summary className="text-acao text-sm font-semibold cursor-pointer">Ver processos usados como referência</summary>
                <ul className={LISTA_INSIGHT}>{estrategia.precedentes.map((p) => <li key={p.indice} className={ITEM_INSIGHT}><strong className="text-tinta">{p.indice}</strong> {p.processo || "processo não informado"} · {p.resultado || "sem desfecho"}{p.vara ? ` · ${p.vara}` : ""}</li>)}</ul>
              </details>
              <p className={`${ESTADO_TEXTO} mt-3`}>{estrategia.estatisticas.aviso} Similaridade mediana: {estrategia.estatisticas.similaridade_amostra.mediana}.</p>
            </>
          )}
        </section>
      )}

      {resultado && qualificacao && (
        <AvaliacaoGoogle
          concluida={avaliacaoConcluida}
          onConcluir={setAvaliacaoConcluida}
          telefone={String(qualificacao.telefone ?? "")}
        />
      )}
    </div>
  );
}
