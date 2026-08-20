"use client";

/**
 * Jurisprudência & Jurimetria — a quarta tela do caso.
 *
 * As quatro respondem perguntas diferentes, e é por isso que são quatro:
 *
 *   checklist  → "o que ainda falta chegar?"
 *   dossiê     → "o que este caso já é?"
 *   painel     → "como este caso se comportou no tempo?"
 *   jurimetria → "o que esperar do mérito, e com que fundamento?"
 *
 * Esta é a única que olha para fora do escritório: os números vêm do acervo de
 * jurisprudência, não dos casos do escritório. Isso muda a régua de honestidade e é o que
 * organiza a tela inteira:
 *
 * - **nenhum percentual aparece sozinho.** Ao lado de cada um vão a amostra ("em 79
 *   processos"), a margem de erro e o recorte que o produziu. Um número solto vira "61% de
 *   chance de ganhar" na conversa com o cliente, e essa frase não se sustenta;
 * - **diferença que a amostra não sustenta é dita, não escondida.** Sai marcada como
 *   "dentro da margem", com a conta no tooltip. Omitir faria quem viu 8 pontos ontem achar
 *   que o sistema mudou de ideia; exibir como achado faria ruído virar tendência;
 * - **o que o acervo não sabe fecha a tela.** A última seção lista, por escrito, as
 *   perguntas que este painel não responde — valor de condenação, taxa de reforma, pedido
 *   deferido. Ausência declarada é informação; ausência omitida é lida como "não houve".
 *
 * Nada aqui é previsão. Todo bloco carrega a frase de natureza que o backend envia, e ela
 * é repetida de propósito: um bloco copiado para uma apresentação viaja sem o topo da tela.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Selo } from "@/components/Basicos";
import { CORES_DE_SERIE, Figura, GraficoDeBarras, GraficoDeLinha, SemDado } from "@/components/graficos";
import { buscarDossie, type Hipotese } from "@/lib/agente";
import {
  buscarContraTese,
  buscarJurimetria,
  buscarLinhasArgumentativas,
  dispararContraTese,
  dispararLinhasArgumentativas,
  leituraDaComparacao,
  percentual,
  pontos,
  rotuloDoDesfecho,
  type ContraArgumento,
  type Jurimetria as Dados,
  type LeituraContraTese,
  type LeituraLinhasArgumentativas,
  type LinhaArgumentativa,
  type PrecedenteCitado,
  type Proporcao,
  type Ranking,
} from "@/lib/jurimetria";
import estilos from "./Jurimetria.module.css";

/* Faixa qualitativa em vez de percentual cru como leitura principal — o número exato
 * continua disponível no `title`, mesma régua de `comparacao.basis` mais abaixo. Um "72% de
 * confiança" solto soa a métrica de calibração de modelo; "relevância moderada" é frase que
 * um advogado já usa. */
function relevancia(fracao: number): { texto: string; tom: "ok" | "atencao" | "neutro" } {
  if (fracao >= 0.75) return { texto: "alta relevância", tom: "ok" };
  if (fracao >= 0.5) return { texto: "relevância moderada", tom: "atencao" };
  return { texto: "relevância baixa", tom: "neutro" };
}

const GRAVIDADE_CONTRA_ARGUMENTO: Record<string, { texto: string; tom: "ok" | "atencao" | "critico"; simbolo: string }> = {
  HIGH: { texto: "ameaça alta", tom: "critico", simbolo: "✕" },
  MEDIUM: { texto: "ameaça média", tom: "atencao", simbolo: "!" },
  LOW: { texto: "ameaça baixa", tom: "ok", simbolo: "•" },
};

/* Cor por desfecho, fixa: a mesma fatia precisa ter a mesma cor no gráfico de rosca, na
 * série anual e em cada ranking. Cor que muda de significado entre seções é pior que
 * nenhuma cor. Acompanhada sempre de palavra — cor nunca carrega sentido sozinha. */
const COR_DO_DESFECHO: Record<string, string> = {
  PROCEDENTE: "var(--ok)",
  PARCIAL: CORES_DE_SERIE[0],
  IMPROCEDENTE: "var(--critico)",
  ACORDO: CORES_DE_SERIE[2],
  EXTINTO: "var(--tinta-3)",
  INDEFINIDO: "var(--tinta-3)",
};

function corDoDesfecho(codigo: string): string {
  return COR_DO_DESFECHO[codigo] ?? "var(--tinta-3)";
}

export default function Jurimetria({
  casoId,
  onVoltar,
  onAbrirDossie,
  onAbrirPainel,
}: {
  casoId: string;
  onVoltar: () => void;
  onAbrirDossie: () => void;
  onAbrirPainel: () => void;
}) {
  const [dados, setDados] = useState<Dados | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [linhas, setLinhas] = useState<LeituraLinhasArgumentativas | null>(null);
  const [contraTese, setContraTese] = useState<LeituraContraTese | null>(null);
  const [hipoteses, setHipoteses] = useState<Hipotese[]>([]);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [avisoAcao, setAvisoAcao] = useState<string | null>(null);

  const carregarLeituras = useCallback(async () => {
    const [linhasResp, contraTeseResp] = await Promise.all([
      buscarLinhasArgumentativas(casoId).catch(() => null),
      buscarContraTese(casoId).catch(() => null),
    ]);
    setLinhas(linhasResp);
    setContraTese(contraTeseResp);
  }, [casoId]);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await buscarJurimetria(casoId));
      await carregarLeituras();
      // A tese a atacar vem da estratégia do caso, não desta tela: aqui só a hipótese já
      // aceita pelo advogado é oferecida — atacar uma proposta ainda não decidida
      // confundiria "o sistema sugeriu" com "o escritório escolheu".
      const dossie = await buscarDossie(casoId).catch(() => null);
      setHipoteses(
        dossie?.agente.estrategia?.hypotheses.filter((item) => item.status === "ACCEPTED") ?? [],
      );
    } catch (falha) {
      // A mensagem do backend distingue "sem pesquisa ainda" de "o acervo não respondeu",
      // e essas duas levam o advogado a ações opostas. Por isso ela é exibida crua.
      setErro(falha instanceof Error ? falha.message : "Falha ao consultar o acervo.");
      setDados(null);
    } finally {
      setCarregando(false);
    }
  }, [casoId, carregarLeituras]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  /* As duas leituras chamam modelo do outro lado (Slow Path): enquanto uma delas estiver
   * `RUNNING`, a tela se atualiza sozinha, mesmo padrão do dossiê para pesquisa e estratégia. */
  const emAndamento = linhas?.status === "RUNNING" || contraTese?.status === "RUNNING";
  useEffect(() => {
    if (!emAndamento) return;
    const timer = setInterval(() => void carregarLeituras(), 5000);
    return () => clearInterval(timer);
  }, [emAndamento, carregarLeituras]);

  async function gerarLinhas() {
    setOcupado("linhas");
    setAvisoAcao(null);
    try {
      await dispararLinhasArgumentativas(casoId);
      await carregarLeituras();
    } catch (falha) {
      setAvisoAcao(falha instanceof Error ? falha.message : "Não foi possível iniciar a leitura.");
    } finally {
      setOcupado(null);
    }
  }

  async function gerarContraTese(hipoteseId: string) {
    setOcupado("contra-tese");
    setAvisoAcao(null);
    try {
      await dispararContraTese(casoId, hipoteseId);
      await carregarLeituras();
    } catch (falha) {
      setAvisoAcao(falha instanceof Error ? falha.message : "Não foi possível iniciar a leitura.");
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div className={estilos.pagina}>
      <div className={estilos.topo}>
        <div className={estilos.navegacao}>
          <button type="button" className="botao botao--secundario botao--pequeno" onClick={onVoltar}>
            ← Voltar para a carteira
          </button>
        </div>
        <div className="abas-modulo">
          <button type="button" className="aba-modulo" onClick={onAbrirDossie}>
            <span className="aba-modulo__titulo">Dossiê do caso →</span>
            <span className="aba-modulo__detalhe">Fatos, pendências e peças do agente</span>
          </button>
          <button type="button" className="aba-modulo" onClick={onAbrirPainel}>
            <span className="aba-modulo__titulo">Painel analítico →</span>
            <span className="aba-modulo__detalhe">
              Tempo de cada etapa e comparação com outros casos
            </span>
          </button>
        </div>
        <h1 className={estilos.titulo}>Jurisprudência e jurimetria</h1>
        <p className={estilos.subtitulo}>
          Como o foro decidiu casos comparáveis a este, medido sobre decisões já proferidas.
          Não é previsão de resultado.
        </p>
      </div>

      {carregando && <div className={estilos.vazio}>Consultando o acervo…</div>}

      {erro && !carregando && (
        <Aviso tom="critico" titulo="O painel não foi calculado">
          {erro}
          <div className={estilos.acaoDoErro}>
            <button type="button" className="botao botao--secundario botao--pequeno" onClick={() => void carregar()}>
              Tentar de novo
            </button>
          </div>
        </Aviso>
      )}

      {dados && !carregando && (
        <Painel
          dados={dados}
          linhas={linhas}
          contraTese={contraTese}
          hipoteses={hipoteses}
          ocupado={ocupado}
          avisoAcao={avisoAcao}
          onGerarLinhas={gerarLinhas}
          onGerarContraTese={gerarContraTese}
        />
      )}
    </div>
  );
}

function Painel({
  dados,
  linhas,
  contraTese,
  hipoteses,
  ocupado,
  avisoAcao,
  onGerarLinhas,
  onGerarContraTese,
}: {
  dados: Dados;
  linhas: LeituraLinhasArgumentativas | null;
  contraTese: LeituraContraTese | null;
  hipoteses: Hipotese[];
  ocupado: string | null;
  avisoAcao: string | null;
  onGerarLinhas: () => void;
  onGerarContraTese: (hipoteseId: string) => void;
}) {
  const referencia = dados.reference;

  return (
    <>
      <Recorte dados={dados} />

      {!dados.reliable && (
        <Aviso tom="atencao" titulo="Amostra pequena demais para leitura">
          O recorte tem {dados.coverage.processes} processo(s), abaixo do mínimo de{" "}
          {dados.minimum_sample}. Os números abaixo valem como contagem, não como tendência.
        </Aviso>
      )}

      {dados.notes.map((nota) => (
        <Aviso key={nota} tom="info">
          {nota}
        </Aviso>
      ))}

      {avisoAcao && (
        <Aviso tom="critico" titulo="A leitura não pôde ser iniciada">
          {avisoAcao}
        </Aviso>
      )}

      <Secao
        numero={1}
        titulo="O que sustenta ganhar aqui"
        explicacao="Fundamento recorrente nas decisões do recorte, favoráveis e desfavoráveis, ancorado nos processos que o sustentam — não é o assunto do CNJ, é a razão de decidir."
      >
        <BlocoLinhasArgumentativas leitura={linhas} ocupado={ocupado} onGerar={onGerarLinhas} />
      </Secao>

      <Secao
        numero={2}
        titulo="O que a outra parte vai alegar"
        explicacao="Hipótese sobre o argumento contrário, construída sobre os julgados que rejeitaram pedido semelhante, com o que pode afastar o caso concreto daquele precedente."
      >
        <BlocoContraTese
          leitura={contraTese}
          hipoteses={hipoteses}
          ocupado={ocupado}
          onGerar={onGerarContraTese}
        />
      </Secao>

      <Secao
        numero={3}
        titulo="Como esses casos terminaram"
        explicacao={
          referencia
            ? `Cada desfecho comparado com o mesmo recorte sem a vara — ${referencia.coverage.processes} processos.`
            : "Distribuição do recorte. Sem referência: este já é o acervo completo."
        }
      >
        <Desfechos linhas={dados.outcomes} />
      </Secao>

      <Secao
        numero={4}
        titulo="Isso está mudando?"
        explicacao="Desfechos por ano da decisão. Ano incompleto sai marcado, e a tendência só é afirmada quando a amostra a sustenta."
      >
        <Serie dados={dados} />
      </Secao>

      {dados.rankings.map((ranking, indice) => (
        <Secao
          key={ranking.dimension}
          numero={5 + indice}
          titulo={`Por ${ranking.label}`}
          explicacao={`Ordenado por volume, nunca por taxa de êxito. ${
            ranking.counts_processes_once
              ? ""
              : "Um processo pode entrar em mais de uma fatia — a coluna não fecha com o total."
          }`}
        >
          <RankingBlocos ranking={ranking} />
        </Secao>
      ))}

      {dados.appellate && (
        <Secao
          numero={5 + dados.rankings.length}
          titulo="Chegaram a instância superior"
          explicacao={dados.appellate.meaning}
        >
          <div className={estilos.heroi}>
            <span className={estilos.valorHeroi}>{percentual(dados.appellate.share)}</span>
            <span className={estilos.detalheHeroi}>
              {dados.appellate.count} de {dados.appellate.total} processos do recorte
              {" · "}margem de {percentual(dados.appellate.margin)}
            </span>
          </div>
        </Secao>
      )}

      <Secao
        numero={6 + dados.rankings.length}
        titulo="O que este painel não responde"
        explicacao="Perguntas frequentes que o acervo não sustenta. Estão aqui porque a ausência de um gráfico é lida como ausência do fato."
      >
        <ul className={estilos.ausencias}>
          {dados.absences.map((item) => (
            <li key={item.question}>
              <strong>{item.question}</strong>
              <span>{item.reason}</span>
            </li>
          ))}
        </ul>
      </Secao>

      <p className={estilos.natureza}>{dados.nature}</p>
    </>
  );
}

/* -------------------------------------------------- leituras de agente */

function BlocoLinhasArgumentativas({
  leitura,
  ocupado,
  onGerar,
}: {
  leitura: LeituraLinhasArgumentativas | null;
  ocupado: string | null;
  onGerar: () => void;
}) {
  if (!leitura) {
    return (
      <div className={estilos.acaoGerar}>
        <p className={estilos.explicacaoSecao}>
          Ainda não pedida. A leitura lê os julgados favoráveis e desfavoráveis do recorte e
          separa o fundamento que se repete em cada lado.
        </p>
        <button
          type="button"
          className="botao botao--primario botao--pequeno"
          disabled={ocupado === "linhas"}
          onClick={onGerar}
        >
          {ocupado === "linhas" ? "Iniciando…" : "Ler fundamentos do recorte"}
        </button>
      </div>
    );
  }

  if (leitura.status === "RUNNING") {
    return <Aviso tom="info">Lendo os julgados do recorte…</Aviso>;
  }

  if (leitura.status === "FAILED") {
    return (
      <Aviso tom="atencao" titulo="A leitura não encontrou o que ler">
        {leitura.failure_reason === "NO_PRECEDENTS_IN_SCOPE"
          ? "Não há julgado de mérito no recorte deste caso — sem um lado favorável ou desfavorável, não há fundamento a extrair."
          : leitura.failure_reason === "AI_PROVIDER_UNAVAILABLE"
            ? "O modelo de leitura não respondeu. Tente novamente em instantes."
            : (leitura.failure_reason ?? "A leitura não pôde ser concluída.")}
      </Aviso>
    );
  }

  if (leitura.lines.length === 0) {
    return <SemDado titulo="Nenhum fundamento recorrente identificado no recorte" />;
  }

  return (
    <ul className={estilos.leituras}>
      {leitura.lines.map((linha, indice) => (
        <CartaoLinha key={indice} linha={linha} />
      ))}
    </ul>
  );
}

function CartaoLinha({ linha }: { linha: LinhaArgumentativa }) {
  const nivel = relevancia(linha.confidence);
  return (
    <li className={estilos.leitura}>
      <div className={estilos.leituraTopo}>
        <p className={estilos.tese}>{linha.thesis}</p>
        <span title={`${percentual(linha.confidence)} — leitura do conjunto recuperado, não probabilidade de êxito`}>
          <Selo tom={linha.side === "GRANTING" ? "ok" : "atencao"}>
            {linha.side === "GRANTING" ? "favorece o pedido" : "favorece a defesa"} · {nivel.texto}
          </Selo>
        </span>
      </div>
      <ProcessosCitados precedentes={linha.precedents} />
      {linha.counter_consideration && (
        <p className={estilos.ressalva}>O que enfraquece: {linha.counter_consideration}</p>
      )}
    </li>
  );
}

function BlocoContraTese({
  leitura,
  hipoteses,
  ocupado,
  onGerar,
}: {
  leitura: LeituraContraTese | null;
  hipoteses: Hipotese[];
  ocupado: string | null;
  onGerar: (hipoteseId: string) => void;
}) {
  const [escolhida, setEscolhida] = useState(hipoteses[0]?.id ?? "");

  if (hipoteses.length === 0 && !leitura) {
    return (
      <p className={estilos.explicacaoSecao}>
        Requer uma tese aceita na Estratégia — sem ela não há o que a contra-tese ataque. Aceite
        uma hipótese no Dossiê e volte aqui.
      </p>
    );
  }

  if (!leitura) {
    return (
      <div className={estilos.acaoGerar}>
        <p className={estilos.explicacaoSecao}>
          Ainda não pedida. Escolha a tese aceita a atacar — a leitura busca de propósito os
          julgados desfavoráveis do recorte e constrói o argumento provável da outra parte.
        </p>
        {hipoteses.length > 1 && (
          <select
            className="campo"
            value={escolhida}
            onChange={(evento) => setEscolhida(evento.target.value)}
          >
            {hipoteses.map((hipotese) => (
              <option key={hipotese.id} value={hipotese.id}>
                {hipotese.statement}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="botao botao--primario botao--pequeno"
          disabled={ocupado === "contra-tese" || !escolhida}
          onClick={() => onGerar(escolhida)}
        >
          {ocupado === "contra-tese" ? "Iniciando…" : "Ler o argumento contrário"}
        </button>
      </div>
    );
  }

  if (leitura.status === "RUNNING") {
    return <Aviso tom="info">Lendo os julgados desfavoráveis do recorte…</Aviso>;
  }

  if (leitura.status === "FAILED") {
    return (
      <Aviso tom="atencao" titulo="A leitura não encontrou o que ler">
        {leitura.failure_reason === "NO_ADVERSE_PRECEDENTS"
          ? "Não há julgado desfavorável no recorte deste caso — sem um lado que rejeitou pedido semelhante, não há o que a outra parte cite daqui."
          : leitura.failure_reason === "AI_PROVIDER_UNAVAILABLE"
            ? "O modelo de leitura não respondeu. Tente novamente em instantes."
            : (leitura.failure_reason ?? "A leitura não pôde ser concluída.")}
      </Aviso>
    );
  }

  if (leitura.counters.length === 0) {
    return <SemDado titulo="Nenhum argumento contrário recorrente identificado" />;
  }

  return (
    <>
      <p className={estilos.explicacaoSecao}>contra: {leitura.thesis}</p>
      <ul className={estilos.leituras}>
        {leitura.counters.map((contra, indice) => (
          <CartaoContraArgumento key={indice} contra={contra} />
        ))}
      </ul>
    </>
  );
}

function CartaoContraArgumento({ contra }: { contra: ContraArgumento }) {
  const gravidade = GRAVIDADE_CONTRA_ARGUMENTO[contra.severity] ?? GRAVIDADE_CONTRA_ARGUMENTO.LOW;
  return (
    <li className={estilos.leitura}>
      <div className={estilos.leituraTopo}>
        <p className={estilos.tese}>{contra.argument}</p>
        <Selo tom={gravidade.tom} simbolo={gravidade.simbolo}>
          {gravidade.texto}
        </Selo>
      </div>
      <ProcessosCitados precedentes={contra.precedents} />
      {contra.distinguishing ? (
        <p className={estilos.distinguishing}>Como afastar: {contra.distinguishing}</p>
      ) : (
        <p className={estilos.ressalva}>
          Sem distinção visível entre este caso e os precedentes citados.
        </p>
      )}
    </li>
  );
}

/** Os processos por extenso — nunca o identificador técnico do acervo. */
function ProcessosCitados({ precedentes }: { precedentes: PrecedenteCitado[] }) {
  if (precedentes.length === 0) return null;
  return (
    <div className={estilos.processos}>
      {precedentes.map((item) => (
        <span key={item.corpus_id} title={[item.court, item.judging_body].filter(Boolean).join(" · ")}>
          {item.process_number}
        </span>
      ))}
    </div>
  );
}

/** O recorte por extenso: sem ele, todo percentual da tela perde o referente. */
function Recorte({ dados }: { dados: Dados }) {
  const cobertura = dados.coverage;
  return (
    <div className={`cartao ${estilos.recorte}`}>
      <div>
        <span className={estilos.rotuloRecorte}>Recorte medido</span>
        <strong className={estilos.valorRecorte}>{dados.scope.label}</strong>
      </div>
      <div className={estilos.numerosRecorte}>
        <span>
          <strong>{cobertura.processes.toLocaleString("pt-BR")}</strong> processos
        </span>
        {cobertura.first_decision && cobertura.last_decision && (
          <span>
            decisões de {cobertura.first_decision.slice(0, 4)} a {cobertura.last_decision.slice(0, 4)}
          </span>
        )}
        {dados.reference && (
          <span>
            referência: {dados.reference.scope.label} ({dados.reference.coverage.processes.toLocaleString("pt-BR")})
          </span>
        )}
      </div>
      {(dados.scope.notes ?? []).length > 0 && (
        <ul className={estilos.notasRecorte}>
          {(dados.scope.notes ?? []).map((nota) => (
            <li key={nota}>{nota}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Desfechos({ linhas }: { linhas: Proporcao[] }) {
  if (linhas.length === 0) {
    return <SemDado titulo="Nenhum processo com desfecho no recorte" />;
  }

  return (
    <>
      <Figura
        titulo="Desfechos do recorte"
        descricao="Um voto por processo, não por documento."
        tabela={{
          colunas: [
            { chave: "desfecho", rotulo: "Desfecho" },
            { chave: "processos", rotulo: "Processos" },
            { chave: "parcela", rotulo: "Parcela" },
            { chave: "diferenca", rotulo: "vs. referência" },
          ],
          linhas: linhas.map((linha) => ({
            desfecho: rotuloDoDesfecho(linha.label),
            processos: linha.count,
            parcela: percentual(linha.share),
            diferenca: linha.comparacao
              ? `${pontos(linha.comparacao.difference_points)}${
                  linha.comparacao.meaningful ? "" : " (dentro da margem)"
                }`
              : "—",
          })),
        }}
      >
        <GraficoDeBarras
          itens={linhas.map((linha) => ({
            rotulo: rotuloDoDesfecho(linha.label),
            valores: [
              {
                nome: "processos",
                valor: Math.round(linha.share * 1000) / 10,
                cor: corDoDesfecho(linha.label),
              },
            ],
            nota: `${linha.count} de ${linha.total} processos · margem de ${percentual(linha.margin)}`,
          }))}
          unidade="%"
        />
      </Figura>

      <ul className={estilos.comparacoes}>
        {linhas.map((linha) => (
          <LinhaDeComparacao key={linha.label} linha={linha} />
        ))}
      </ul>
    </>
  );
}

/** Um desfecho com tudo o que ele precisa carregar: parcela, amostra e ressalva. */
function LinhaDeComparacao({ linha }: { linha: Proporcao }) {
  const leitura = leituraDaComparacao(linha.comparacao);

  return (
    <li className={estilos.comparacao}>
      <div className={estilos.comparacaoTopo}>
        <strong>{rotuloDoDesfecho(linha.label)}</strong>
        <span className={estilos.parcela}>{percentual(linha.share)}</span>
      </div>
      <div className={estilos.comparacaoBase}>
        <span>
          {linha.count} de {linha.total} processos · margem de {percentual(linha.margin)}
        </span>
        {leitura && linha.comparacao && (
          /* O `title` traz a conta: nota sem fórmula visível é chute com aparência de
           * medida, e é essa frase que sustenta a diferença numa reunião. */
          <span title={linha.comparacao.basis}>
            <Selo tom={leitura.tom} simbolo={leitura.simbolo}>
              {pontos(linha.comparacao.difference_points)} · {leitura.palavra}
            </Selo>
          </span>
        )}
      </div>
    </li>
  );
}

function Serie({ dados }: { dados: Dados }) {
  const pontosDoAno = dados.timeline;
  if (pontosDoAno.length === 0) {
    return <SemDado titulo="Sem decisões datadas no recorte" />;
  }

  /* Uma linha por desfecho, com a parcela do ano. Volume absoluto por ano diria mais
   * sobre a ingestão do acervo do que sobre o entendimento do foro. */
  const desfechos = Array.from(
    new Set(pontosDoAno.flatMap((ponto) => ponto.shares.map((item) => item.label))),
  );

  return (
    <>
      <Figura
        titulo="Parcela de cada desfecho por ano"
        descricao="Ano da decisão. Anos incompletos aparecem na tabela marcados."
        legenda={desfechos.map((codigo) => ({
          rotulo: rotuloDoDesfecho(codigo),
          cor: corDoDesfecho(codigo),
          forma: "linha" as const,
        }))}
        tabela={{
          colunas: [
            { chave: "ano", rotulo: "Ano" },
            { chave: "processos", rotulo: "Processos" },
            ...desfechos.map((codigo) => ({ chave: codigo, rotulo: rotuloDoDesfecho(codigo) })),
          ],
          linhas: pontosDoAno.map((ponto) => ({
            ano: ponto.partial ? `${ponto.year} (incompleto)` : String(ponto.year),
            processos: ponto.processes,
            ...Object.fromEntries(
              desfechos.map((codigo) => [
                codigo,
                percentual(ponto.shares.find((item) => item.label === codigo)?.share ?? 0),
              ]),
            ),
          })),
        }}
      >
        <GraficoDeLinha
          rotulos={pontosDoAno.map((ponto) => (ponto.partial ? `${ponto.year}*` : String(ponto.year)))}
          series={desfechos.map((codigo) => ({
            nome: rotuloDoDesfecho(codigo),
            cor: corDoDesfecho(codigo),
            unidade: "%",
            valores: pontosDoAno.map(
              (ponto) =>
                Math.round((ponto.shares.find((item) => item.label === codigo)?.share ?? 0) * 1000) / 10,
            ),
          }))}
          rotuloDoValor={(valor) => `${valor}%`}
        />
      </Figura>

      {pontosDoAno.some((ponto) => ponto.partial) && (
        <p className={estilos.rodapeFigura}>
          * Ano incompleto — ainda corre, ou o acervo termina no meio dele. A queda no
          último ponto é de calendário, não de entendimento.
        </p>
      )}

      {dados.trend ? (
        <div className={estilos.tendencia}>
          <Selo
            tom={dados.trend.direction === "estável" ? "neutro" : "info"}
            simbolo={dados.trend.direction === "alta" ? "▲" : dados.trend.direction === "queda" ? "▼" : "≈"}
          >
            {rotuloDoDesfecho(dados.trend.label)}: {dados.trend.direction}
          </Selo>
          <span>
            {dados.trend.first_year} a {dados.trend.last_year} ·{" "}
            {pontos(dados.trend.comparison.difference_points)}
          </span>
          <span className={estilos.base}>{dados.trend.comparison.basis}</span>
        </div>
      ) : (
        <p className={estilos.rodapeFigura}>
          Sem dois anos completos no recorte, não há série para afirmar tendência.
        </p>
      )}
    </>
  );
}

function RankingBlocos({ ranking }: { ranking: Ranking }) {
  if (ranking.slices.length === 0) {
    return <SemDado titulo="Nenhuma fatia com processos neste eixo" />;
  }

  return (
    <ul className={estilos.fatias}>
      {ranking.slices.map((fatia) => {
        const principal = fatia.shares[0];
        const leitura = leituraDaComparacao(principal?.comparacao);
        return (
          <li key={fatia.value} className={estilos.fatia}>
            <div className={estilos.fatiaTopo}>
              <strong>{fatia.value}</strong>
              <span>{fatia.processes} processos</span>
            </div>
            <div className={estilos.barras}>
              {fatia.shares.map((linha) => (
                <span
                  key={linha.label}
                  className={estilos.segmento}
                  style={{ width: `${linha.share * 100}%`, background: corDoDesfecho(linha.label) }}
                  title={`${rotuloDoDesfecho(linha.label)}: ${linha.count} (${percentual(linha.share)})`}
                />
              ))}
            </div>
            <div className={estilos.fatiaBase}>
              {principal && (
                <span>
                  {rotuloDoDesfecho(principal.label)} {percentual(principal.share)}
                </span>
              )}
              {fatia.small_sample ? (
                <Selo tom="atencao" simbolo="!">
                  amostra pequena
                </Selo>
              ) : (
                leitura &&
                principal?.comparacao && (
                  <span title={principal.comparacao.basis}>
                    <Selo tom={leitura.tom} simbolo={leitura.simbolo}>
                      {pontos(principal.comparacao.difference_points)} · {leitura.palavra}
                    </Selo>
                  </span>
                )
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Secao({
  numero,
  titulo,
  explicacao,
  children,
}: {
  numero: number;
  titulo: string;
  explicacao?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={estilos.secao}>
      <h2 className={estilos.tituloSecao}>
        <span className={estilos.numeroSecao}>{numero}</span>
        {titulo}
      </h2>
      {explicacao && <p className={estilos.explicacaoSecao}>{explicacao}</p>}
      <div className="cartao">{children}</div>
    </section>
  );
}
