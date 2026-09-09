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

/** O login parou no segundo fator: a senha conferiu, mas falta o código.
 *
 * NÃO há sessão nenhuma neste estado — nenhum cookie foi gravado. É por isso que
 * ele é um tipo separado de `SessaoUsuario` em vez de um campo opcional dentro
 * dela: um `SessaoUsuario` com metade dos campos vazios acabaria sendo tratado
 * como usuário logado em algum lugar da tela, que é justamente o que não pode
 * acontecer. */
export interface DesafioDeAcesso {
  /** Identificador do desafio no servidor. É o que a confirmação do código
   *  envia — o e-mail nunca volta ao servidor, senão bastaria um código válido
   *  qualquer para escolher em que conta entrar. */
  desafio: string;
  /** O endereço MASCARADO (`fu****@escritorio.com`), só para a pessoa saber qual
   *  caixa abrir. O servidor nunca devolve o e-mail inteiro nesta etapa. */
  email: string;
  expira_em_segundos: number;
  reenviar_em_segundos: number;
}

/** As duas formas da resposta de `POST /api/user/authenticate`.
 *
 * O `etapa` é o discriminador: `"sessao"` quer dizer que acabou ali (perfil
 * isento do segundo fator, ou segundo fator desligado); `"dois_fatores"` quer
 * dizer que falta confirmar o código. */
export type RespostaDeLogin =
  | ({ etapa: "sessao" } & SessaoUsuario)
  | ({ etapa: "dois_fatores" } & DesafioDeAcesso);

/** O que `/api/config` conta à tela de login antes de alguém se identificar. */
export interface ConfiguracaoDeAcesso {
  captcha: {
    ativo: boolean;
    /** Pública por definição — o navegador precisa dela para desenhar o widget. */
    site_key: string;
  };
  doisFatores: {
    ativo: boolean;
    validade_minutos: number;
    reenviar_em_segundos: number;
  };
}
