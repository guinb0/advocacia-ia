import type { Documento } from "@/lib/types";
import { ListaMensagens, Selo } from "./Basicos";
import ui from "./ui.module.css";

/** Resposta de sim/não como selo: símbolo + palavra, nunca só a cor. */
function SimNao({ valor, tomDoNao = "critico" }: { valor: boolean; tomDoNao?: "critico" | "atencao" }) {
  return valor ? (
    <Selo tom="ok" simbolo="✓">
      sim
    </Selo>
  ) : (
    <Selo tom={tomDoNao} simbolo={tomDoNao === "critico" ? "✕" : "!"}>
      não
    </Selo>
  );
}

export default function PainelValidacao({ doc }: { doc: Documento }) {
  const v = doc.validacao;

  return (
    <>
      <div className={ui.secao}>Situação</div>
      <table className={ui.tabela}>
        <tbody>
          <tr>
            <td>
              <strong>Dados utilizáveis</strong>
              <div className={ui.observacao}>
                legível, nada faltando e nada reprovado no dígito verificador
              </div>
            </td>
            <td className={ui.direita}>
              <SimNao valor={v.dados_utilizaveis} />
            </td>
          </tr>
          <tr>
            <td>
              <strong>Imagem legível</strong>
            </td>
            <td className={ui.direita}>
              <SimNao valor={v.imagem_legivel} />
            </td>
          </tr>
          <tr>
            <td>
              <strong>Sem ressalvas de qualidade</strong>
            </td>
            <td className={ui.direita}>
              <SimNao valor={v.aprovado} tomDoNao="atencao" />
            </td>
          </tr>
        </tbody>
      </table>

      <ListaMensagens titulo="Erros" itens={v.erros} tom="erro" />
      <ListaMensagens titulo="Avisos" itens={v.avisos} tom="aviso" />
      <ListaMensagens titulo="Sugestões ao usuário" itens={v.sugestoes} tom="sugestao" />

      {v.campos_esperados.length > 0 && (
        <>
          <div className={ui.secao}>Campos esperados para {doc.tipo.descricao}</div>
          <table className={ui.tabela}>
            <tbody>
              {v.campos_esperados.map((campo) => {
                const extraido = !v.campos_faltando.includes(campo);
                return (
                  <tr key={campo}>
                    <td className={ui.valor}>{campo}</td>
                    <td className={ui.direita}>
                      {extraido ? (
                        <Selo tom="ok" simbolo="✓">
                          extraído
                        </Selo>
                      ) : (
                        <Selo tom="critico" simbolo="✕">
                          faltando
                        </Selo>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
