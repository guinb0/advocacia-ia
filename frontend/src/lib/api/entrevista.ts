/** Entrevista: triagem, escuta, processamento, estratégia, relatório e gravação ao vivo. */

import type {
  AnaliseResposta,
  Escuta,
  Estrategia,
  ProcessamentoEntrevista,
  RecomendacaoEntrevista,
  RoteiroCompleto,
  Triagem as TriagemResposta,
} from "../types";
import { ApiError, buscar, comoJson } from "./base";
import type { EntrevistaResumo } from "./supervisao";

export interface RelatorioGerado {
  arquivo: Blob;
  nome: string;
  /** Pendências obrigatórias que a entrevista deixou em aberto. */
  pendencias: number;
  /** Impedimentos que o escritório mandou observar. */
  impedimentos: number;
  /** Se a análise por precedentes entrou no documento. */
  analise: "sim" | "indisponivel" | "nao";
}

/** O relatório analisado da entrevista, em PDF, com o símbolo do escritório.
 *
 * Organiza as respostas na ordem do roteiro e, quando a base de precedentes
 * responde, traz a análise assistida (síntese, ações, riscos, lacunas). O
 * `relato` é o texto corrido da entrevista — é dele que sai a análise. */
export async function gerarRelatorio(
  respostas: Record<string, string | string[]>,
  relato = "",
  roteiro = "auxilio_acidente",
): Promise<RelatorioGerado> {
  const criado = await comoJson<{ job_id: string }>(await buscar("/api/entrevista/relatorio/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respostas, relato, roteiro }),
  }));

  const limite = Date.now() + 15 * 60_000;
  while (Date.now() < limite) {
    const job = await comoJson<{
      status: string;
      erro?: string | null;
      resultado?: { arquivo: string; pendencias: number; impedimentos: number; analise: RelatorioGerado["analise"] } | null;
    }>(await buscar(`/api/jobs/${criado.job_id}`));
    if (job.status === "FAILED") throw new ApiError(job.erro || "Falha ao gerar relatório.");
    if (job.status === "COMPLETED" && job.resultado) {
      const pdf = await buscar(job.resultado.arquivo);
      if (!pdf.ok) throw new ApiError("O PDF foi gerado, mas não pôde ser baixado.");
      return {
        arquivo: await pdf.blob(), nome: "relatorio-entrevista.pdf",
        pendencias: job.resultado.pendencias, impedimentos: job.resultado.impedimentos,
        analise: job.resultado.analise,
      };
    }
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("O relatório não respondeu em 90 segundos. Tente novamente; respostas e entrevista permanecem salvas.");
}

// ----------------------------------------------------- triagem da entrevista

/** Classifica o relato e sugere a categoria. NÃO cria caso — só sugere. */
export async function triarEntrevista(texto: string, arquivo?: File): Promise<TriagemResposta> {
  const form = new FormData();
  form.append("texto", texto);
  if (arquivo) form.append("arquivo", arquivo);
  return comoJson<TriagemResposta>(
    await buscar("/api/triagem", { method: "POST", body: form }),
  );
}

/** Manda um trecho da conversa e recebe o que ele respondeu do roteiro.
 *
 * É o que sustenta a entrevista de microfone aberto: em vez de a atendente
 * apertar gravar a cada uma das 86 perguntas, a conversa corre e o roteiro se
 * preenche atrás dela. */
export async function escutarTrecho(
  trecho: string,
  respostas: Record<string, string | string[]>,
  roteiro = "auxilio_acidente",
  perguntaAtual = "",
  roteiroSnapshot?: RoteiroCompleto,
): Promise<Escuta> {
  return comoJson<Escuta>(
    await buscar("/api/entrevista/escuta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trecho,
        respostas,
        roteiro,
        pergunta_atual: perguntaAtual,
        roteiro_snapshot: roteiroSnapshot,
      }),
    }),
  );
}

function explicarRotaDeProcessamento(resposta: Response): Response {
  if (resposta.status === 404) {
    throw new ApiError(
      "O serviço de preenchimento está desatualizado. Reinicie a aplicação e processe a entrevista novamente.",
    );
  }
  return resposta;
}

/** Organiza a conversa completa somente depois que a captura foi encerrada. */
export async function processarEntrevista(
  transcricao: string,
  respostas: Record<string, string | string[]>,
  roteiro = "auxilio_acidente",
  roteiroSnapshot?: RoteiroCompleto,
): Promise<ProcessamentoEntrevista> {
  const resposta = await buscar("/api/entrevista/processar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcricao,
      respostas,
      roteiro,
      roteiro_snapshot: roteiroSnapshot,
    }),
  });
  return comoJson<ProcessamentoEntrevista>(
    explicarRotaDeProcessamento(resposta),
  );
}

/** Confere UMA resposta narrativa e diz o que ela não trouxe.
 *
 * É a irmã curta de `analisarEstrategia`: aquela produz um parecer por caso,
 * esta roda uma vez por pergunta, durante a entrevista, e cabe em três itens. */
export async function analisarResposta(
  perguntaId: string,
  pergunta: string,
  resposta: string,
  contexto = "",
): Promise<AnaliseResposta> {
  return comoJson<AnaliseResposta>(
    await buscar("/api/entrevista/analise", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pergunta_id: perguntaId,
        pergunta,
        resposta,
        contexto,
      }),
    }),
  );
}

/** Recomenda se vale ABRIR o caso para análise; nunca estima chance de vitória. */
export async function recomendarEntrevista(
  relato: string,
  lacunasObrigatorias: string[],
  roteiro: RoteiroCompleto,
): Promise<RecomendacaoEntrevista> {
  const contextoRoteiro = [
    `Roteiro ativo: ${roteiro.nome}`,
    roteiro.descricao && `Objetivo: ${roteiro.descricao}`,
    ...roteiro.blocos.map((bloco) =>
      `${bloco.titulo}: ${bloco.perguntas.map((pergunta) => pergunta.texto).join(" | ")}`
    ),
  ].filter(Boolean).join("\n").slice(0, 12_000);
  return comoJson<RecomendacaoEntrevista>(
    await buscar("/api/entrevista/recomendacao", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        relato,
        lacunas_obrigatorias: lacunasObrigatorias,
        contexto_roteiro: contextoRoteiro,
        limite_precedentes: 12,
      }),
    }),
  );
}

/** Recupera processos semelhantes e gera apoio estratégico fundamentado. */
export async function analisarEstrategia(relato: string): Promise<Estrategia> {
  const criado = await comoJson<{ job_id: string }>(
    await buscar("/api/estrategia/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relato, limite_precedentes: 8 }),
    }),
  );
  const limite = Date.now() + 10 * 60_000;
  while (Date.now() < limite) {
    const job = await comoJson<{ status: string; erro?: string | null; resultado?: Estrategia | null }>(
      await buscar(`/api/jobs/${criado.job_id}`),
    );
    if (job.status === "COMPLETED" && job.resultado) return job.resultado;
    if (job.status === "FAILED") throw new ApiError(job.erro || "Falha na análise estratégica.");
    await new Promise((resolver) => window.setTimeout(resolver, 1000));
  }
  throw new ApiError("A análise estratégica excedeu o tempo de espera.");
}

/* ------------------------------------- a entrevista conduzida ao vivo
 *
 * Até aqui, a entrevista só virava registro quando alguém anexava um arquivo ao
 * caso, à mão, depois. O atendimento guiado — roteiro, escuta, gravação — não
 * gravava nada: a conversa transcrita morria com a aba, e a supervisão (que lê
 * essa tabela) enxergava só a amostra que tinha sido anexada.
 *
 * O que sobe é a transcrição BRUTA, não o relato montado das respostas: o relato
 * diz o que a escuta extraiu, e auditá-lo mediria o reconhecimento de voz em vez
 * da condução da entrevista (ver o cabeçalho de `app/auditoria.py`).
 *
 * PUT, e chamado mais de uma vez por atendimento: o caso nasce no meio da
 * rolagem e a conversa continua depois dele — avaliação, documentos, fechamento.
 * `gravacao_id` é a chave, e a segunda chamada reescreve a primeira. */

export interface EntrevistaAoVivo {
  /** Id da gravação no serviço de transcrição. Identifica a entrevista. */
  gravacao_id: string;
  texto: string;
  realizada_em: string;
  avaliacao_google: boolean;
  /** O atendimento foi encerrado — só então o agente lê a conversa. */
  concluida: boolean;
}

export async function gravarEntrevistaAoVivo(
  casoId: string,
  dados: EntrevistaAoVivo,
): Promise<EntrevistaResumo> {
  return comoJson(
    await buscar(`/api/casos/${encodeURIComponent(casoId)}/entrevista-ao-vivo`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }),
  );
}
