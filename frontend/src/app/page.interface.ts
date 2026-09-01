/** Quem está logado, do ponto de vista da tela.
 *
 * É o `data` que `POST /api/user/authenticate` devolve. Os nomes seguem os
 * claims do token (`codigo`, `perfil`, `senhaPadrao`) e não a convenção em
 * português do resto do frontend — de propósito: é um contrato que atravessa
 * sistemas, e traduzir aqui obrigaria a traduzir de volta em cada comparação. */
export interface SessaoUsuario {
  codigo: string;
  nome: string;
  email: string;
  perfil: string;
  perfilId?: number | null;
  senhaPadrao: boolean;
  /** Os módulos do Acervo que este perfil alcança (ver `app/perfis.py`).
   *
   * Vem junto do login para o menu não oferecer botão que a rota vai recusar
   * depois — e para não custar uma segunda ida ao servidor só para montá-lo. */
  modulos: string[];
}
