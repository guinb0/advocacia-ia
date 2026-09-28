/** Chamada de vídeo do atendimento. */

import { buscar, comoJson } from "./base";

/** Sorteia uma sala nova, ou pega o token para ENTRAR numa que já existe.
 *
 * São duas rotas porque são dois atos com donos diferentes. Sortear sala é do
 * escritório e exige sessão. Entrar é do cliente, que não tem conta — a página
 * da chamada promete que ele não precisa criar uma —, e por isso a rota de
 * entrada é pública, com a sala no caminho: o que protege é o nome dela, 256
 * bits sorteados, igual ao portal do caso.
 *
 * Antes as duas passavam pela mesma rota autenticada, e o link público da
 * chamada abria uma tela de login. */
export async function criarSalaChamada(
  sala?: string,
): Promise<{ sala: string; url: string; token: string; p2p: boolean }> {
  const destino = sala
    ? `/api/chamada/sala/${encodeURIComponent(sala)}/token`
    : "/api/chamada/sala";
  /* `p2p` vem do servidor, e não do build, de propósito: é o interruptor de
   * emergência da chamada. Se o videobridge estiver inalcançável, religá-lo é
   * uma variável de ambiente e um restart da API — sem rebuild do frontend, que
   * levaria um pipeline inteiro com o cliente esperando. Ver `CHAMADA_P2P`. */
  return comoJson<{ sala: string; url: string; token: string; p2p: boolean }>(
    await buscar(destino, { method: "POST" }),
  );
}
