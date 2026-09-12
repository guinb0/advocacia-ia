/* Um jeito só de entregar arquivo ao navegador.
 *
 * O QUE ESTAVA ERRADO
 *
 * A mesma função estava copiada em sete telas — relatório da entrevista,
 * contrato, pacote de documentos do caso, item do checklist, petição, dossiê,
 * revisão —, e as sete tinham o mesmo defeito em duas partes:
 *
 * 1. O `<a>` nunca era inserido na página. No Chrome funciona; no Firefox um
 *    link fora do documento não dispara download nenhum, e o clique não fazia
 *    absolutamente nada — sem erro no console, sem aviso na tela. Era o último
 *    passo do fluxo: a petição pronta, gerada e paga em tokens, não descia.
 * 2. `revokeObjectURL` vinha na linha seguinte ao `click()`. O download é
 *    assíncrono; revogar a URL antes de o navegador começar a ler o blob
 *    cancela o arquivo pela metade — o que aparece como .docx corrompido, sem
 *    relação óbvia com o clique.
 *
 * Aqui o link entra no documento, é clicado, é removido, e a URL só é revogada
 * um tique depois — tempo de o navegador ter começado a baixar. Revogar importa:
 * sem isso o blob (uma petição em PDF, um zip de documentos) fica na memória da
 * aba até ela ser fechada.
 */

/** Entrega `arquivo` ao navegador com o nome `nome`, como download. */
export function baixarArquivo(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Baixa uma URL que JÁ existe e pertence a outro dono — não a revoga.
 *
 * O caso é o vídeo da entrevista: o object URL é do gravador, que ainda o usa
 * para mostrar a prévia na tela e para o botão manual de baixar. Revogar aqui
 * apagaria a prévia e quebraria a segunda tentativa. */
export function baixarUrl(url: string, nome: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/** O mesmo, para texto montado na hora (relato da entrevista, transcrição). */
export function baixarTexto(conteudo: string, nome: string): void {
  baixarArquivo(new Blob([conteudo], { type: "text/plain;charset=utf-8" }), nome);
}
