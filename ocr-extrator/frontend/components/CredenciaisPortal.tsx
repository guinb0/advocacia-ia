"use client";

import { useState } from "react";

import type { PortalGerado } from "@/lib/types";
import estilos from "./CredenciaisPortal.module.css";

/** Link e senha do caso recém-criado.
 *
 * Aparece uma vez só, e de propósito: o backend guarda apenas o hash da senha,
 * então este é o único momento em que ela existe em texto claro. Fechar sem
 * copiar obriga a gerar outra. */
export default function CredenciaisPortal({
  cliente,
  portal,
  onAbrirCaso,
  onFechar,
}: {
  cliente: string;
  portal: PortalGerado;
  onAbrirCaso: () => void;
  onFechar: () => void;
}) {
  const [copiado, setCopiado] = useState<string | null>(null);

  const mensagem =
    `Olá, ${cliente}! Envie os documentos do seu processo por aqui:\n` +
    `${portal.url}\n\nSenha: ${portal.senha}`;

  async function copiar(texto: string, qual: string) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(qual);
      setTimeout(() => setCopiado(null), 2000);
    } catch {
      // Sem permissão de área de transferência: o texto continua visível para
      // seleção manual, então não vale interromper o fluxo com um erro.
    }
  }

  return (
    <div className={estilos.bloco} role="status">
      <span className={estilos.rotulo}>
        <span className={estilos.simbolo} aria-hidden>
          !
        </span>
        Caso criado — copie a senha agora
      </span>
      <p className={estilos.texto}>{portal.aviso}</p>

      {/* De quem são estas credenciais.
        *
        * Elas abrem o portal do CLIENTE, e só ele precisa delas — quem está
        * aqui já entrou no sistema pelo login e já está na sala do caso. Sem
        * esta linha, o atendente tentava usar o link e a senha para "entrar no
        * caso", que é o caminho errado e pede senha à toa. */}
      <p className={estilos.texto}>
        <strong>Link e senha são do cliente.</strong> Você não precisa deles: o caso já
        está aberto aí embaixo e você já está na sala da chamada.
      </p>

      <div className={estilos.campo}>
        <span className={estilos.chave}>Link</span>
        <span className={estilos.valor}>{portal.url}</span>
        <button
          type="button"
          className="botao botao--secundario botao--pequeno"
          onClick={() => copiar(portal.url, "url")}
        >
          {copiado === "url" ? "✓ Copiado" : "Copiar"}
        </button>
      </div>

      <div className={estilos.campo}>
        <span className={estilos.chave}>Senha</span>
        <span className={`${estilos.valor} ${estilos.senha}`}>{portal.senha}</span>
        <button
          type="button"
          className="botao botao--secundario botao--pequeno"
          onClick={() => copiar(portal.senha, "senha")}
        >
          {copiado === "senha" ? "✓ Copiado" : "Copiar"}
        </button>
      </div>

      <div className={estilos.acoes}>
        <button
          type="button"
          className="botao botao--primario"
          onClick={() => copiar(mensagem, "msg")}
        >
          {copiado === "msg" ? "✓ Mensagem copiada" : "Copiar a mensagem para o cliente"}
        </button>
        <button type="button" className="botao botao--secundario" onClick={onAbrirCaso}>
          Abrir o caso
        </button>
        <button type="button" className="botao botao--discreto" onClick={onFechar}>
          Fechar
        </button>
      </div>
    </div>
  );
}
