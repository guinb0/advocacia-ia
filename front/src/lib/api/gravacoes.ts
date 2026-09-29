/** Gravações e transcrições da entrevista enviadas ao servidor. */

import { buscar, comoJson } from "./base";

export async function guardarGravacaoNoBanco(
  arquivo: Blob,
  nome: string,
  tipo: "video" | "audio" | "transcricao",
  entrevistaId = "",
): Promise<void> {
  const form = new FormData();
  form.append("arquivo", arquivo, nome);
  form.append("nome", nome);
  form.append("tipo", tipo);
  form.append("entrevista_id", entrevistaId);
  await comoJson(await buscar("/api/gravacoes-temporarias", { method: "POST", body: form }));
}

async function comRetentativas(enviar: () => Promise<unknown>, tentativas = 5): Promise<void> {
  for (let tentativa = 1; tentativa <= tentativas; tentativa++) {
    try {
      await enviar();
      return;
    } catch {
      if (tentativa < tentativas) await new Promise((ok) => setTimeout(ok, 2000 * tentativa));
    }
  }
}

export function enviarPedacoGravacao(
  sessaoId: string,
  ordem: number,
  pedaco: Blob,
  nome: string,
  entrevistaId = "",
): Promise<void> {
  return comRetentativas(async () => {
    const form = new FormData();
    form.append("arquivo", pedaco, nome);
    form.append("sessao_id", sessaoId);
    form.append("ordem", String(ordem));
    form.append("nome", nome);
    form.append("entrevista_id", entrevistaId);
    await comoJson(await buscar("/api/gravacoes-temporarias/pedacos", { method: "POST", body: form }));
  });
}

export function guardarTrechoNoBanco(entrevistaId: string, quando: number, texto: string): Promise<void> {
  if (!entrevistaId || !texto.trim()) return Promise.resolve();
  return comRetentativas(async () => {
    await comoJson(
      await buscar("/api/gravacoes-temporarias/trechos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entrevista_id: entrevistaId, quando, texto }),
      }),
    );
  });
}

/** Guarda uma transcrição de atendimento como entrevista do caso. Aceita um
 *  arquivo (.txt, .docx, .pdf); texto colado vira um .txt no cliente. É o que
 *  destrava a análise/petição quando o caso ainda não tem entrevista gravada. */
export async function enviarTranscricaoEntrevista(
  casoId: string,
  arquivo: File,
): Promise<{ id: string; arquivo?: string }> {
  const form = new FormData();
  form.append("arquivo", arquivo);
  return comoJson(await buscar(`/api/casos/${casoId}/entrevista`, { method: "POST", body: form }));
}
