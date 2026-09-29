"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

import { Botao, Cartao } from "@/components/ui/Basicos";

/**
 * Impede que um erro de uma tela apague o aplicativo inteiro.
 *
 * Sem isto, qualquer exceção durante o desenho — um campo que voltou nulo da API, um código
 * novo que o mapa da tela ainda não conhece — faz o React desmontar a árvore toda. O que a
 * pessoa vê é a página em branco: o menu some, a mensagem de erro que a tela tinha acabado de
 * exibir some junto, e não há para onde rolar. A única saída vira recarregar no F5, e o que
 * quebrou não fica registrado em lugar nenhum.
 *
 * Aqui o estrago para no limite da tela: a casca e o menu continuam de pé, a falha aparece
 * escrita — com a mensagem original, que é o que permite consertar a causa — e há um botão
 * para tentar de novo sem perder a sessão.
 *
 * `chave` zera o erro quando muda (passamos a tela aberta): trocar de tela é uma tentativa
 * nova, e sem isso a tela quebrada continuaria quebrada mesmo depois de navegar para longe.
 */
interface Props {
  children: ReactNode;
  /** Muda ⇒ o limite tenta desenhar de novo. Normalmente, a tela aberta. */
  chave?: string | number;
  /** Como chamar o que quebrou, na frase que a pessoa lê. */
  titulo?: string;
}

interface Estado {
  erro: Error | null;
}

export class LimiteDeErro extends Component<Props, Estado> {
  state: Estado = { erro: null };

  static getDerivedStateFromError(erro: Error): Estado {
    return { erro };
  }

  componentDidCatch(erro: Error, info: ErrorInfo) {
    /* O console é o único lugar onde a pilha sobrevive em produção: o build minificado não
     * mostra a origem na tela, mas o navegador ainda sabe dizer qual componente quebrou. */
    console.error("Falha ao desenhar a tela:", erro, info.componentStack);
  }

  componentDidUpdate(anterior: Props) {
    if (this.state.erro && anterior.chave !== this.props.chave) {
      this.setState({ erro: null });
    }
  }

  render() {
    const { erro } = this.state;
    if (!erro) return this.props.children;

    return (
      <div className="mx-auto w-full max-w-[720px] p-5">
        <Cartao titulo={this.props.titulo ?? "Esta tela parou de responder"}>
          <p className="mt-2 mb-3 text-sm leading-[1.55] text-tinta-3">
            Algo na página não pôde ser desenhado e o restante foi interrompido. Seus dados não
            foram perdidos: nada aqui apaga o que já estava salvo. Tente novamente e, se
            repetir, mostre a linha abaixo a quem cuida do sistema — é ela que aponta a causa.
          </p>
          <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 p-3 font-codigo text-xs text-tinta-2">
            {erro.message || String(erro)}
          </pre>
          <div className="mt-4 flex flex-wrap gap-2">
            <Botao variante="primario" onClick={() => this.setState({ erro: null })}>
              Tentar desenhar de novo
            </Botao>
            <Botao variante="secundario" onClick={() => window.location.reload()}>
              Recarregar a página
            </Botao>
          </div>
        </Cartao>
      </div>
    );
  }
}

export default LimiteDeErro;
