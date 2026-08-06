"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useSessao } from "@/lib/auth";
import estilos from "./PortaoLogin.module.css";

/** Só deixa passar quem tem sessão. Com a autenticação desligada
 * (`iniciar.ps1 -SemAuth`) o provedor já entrega `autenticado`, e este
 * componente vira um passa-tudo. */
export default function PortaoLogin({ children }: { children: ReactNode }) {
  const caminho = usePathname();
  const { carregando, autenticado, erro, entrar } = useSessao();

  /* O portal do cliente fica fora deste portão: o cliente não tem conta no
   * Keycloak. Quem o protege é a senha do caso, conferida pela própria página
   * e pelo backend em toda rota /api/portal/. */
  if (caminho?.startsWith("/portal/")) return <>{children}</>;

  if (carregando) {
    return <div className={estilos.carregando}>Verificando a sessão…</div>;
  }

  if (autenticado) return <>{children}</>;

  return (
    <div className={estilos.tela}>
      <div className={estilos.cartao}>
        <span className={estilos.marca}>ACERVO</span>
        <div className={estilos.filete} />

        <h1 className={estilos.titulo}>Entrar</h1>
        <p className={estilos.texto}>
          A carteira de casos e os documentos dos clientes exigem identificação. Você será
          levado ao Keycloak e volta para cá autenticado.
        </p>

        {erro && (
          <div className={estilos.erro}>
            {erro}
            <br />
            Verifique se o Keycloak está no ar: <code>docker compose up -d keycloak</code>
          </div>
        )}

        <button type="button" className={estilos.botao} onClick={entrar}>
          Entrar com o Keycloak
        </button>
      </div>
    </div>
  );
}
