"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useSessao } from "@/lib/auth";
import { Aviso } from "./Basicos";
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
        <span className={estilos.marca}>Acervo</span>
        <span className={estilos.marcaAjuda}>Documentos e casos do escritório</span>
        <hr className={estilos.divisor} />

        <h1 className={estilos.titulo}>Entrar no sistema</h1>
        <p className={estilos.texto}>
          A carteira de casos e os documentos dos clientes exigem identificação. Ao continuar, você
          passa pela tela de acesso do escritório e volta para cá já identificado.
        </p>

        {erro && (
          <div style={{ marginTop: 18 }}>
            <Aviso tom="critico" titulo="Não foi possível verificar o acesso">
              {erro}
              <span className={estilos.dica}>
                Se o problema continuar, avise o suporte técnico: o serviço de acesso pode estar
                fora do ar (<code>docker compose up -d keycloak</code>).
              </span>
            </Aviso>
          </div>
        )}

        <div className={estilos.acao}>
          <button type="button" className="botao botao--primario botao--bloco" onClick={entrar}>
            Entrar
          </button>
        </div>
      </div>
    </div>
  );
}
