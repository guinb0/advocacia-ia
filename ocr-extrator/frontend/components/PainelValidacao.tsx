import type { Documento } from "@/lib/types";
import { ListaMensagens, Tag } from "./Basicos";
import ui from "./ui.module.css";

export default function PainelValidacao({ doc }: { doc: Documento }) {
  const v = doc.validacao;

  return (
    <>
      <div className={ui.secao}>Situação</div>
      <table className={ui.tabela}>
        <tbody>
          <tr>
            <td>
              Dados utilizáveis
              <div className={ui.observacao}>
                legível, nada faltando e nada reprovado no dígito verificador
              </div>
            </td>
            <td className={ui.direita}>
              <Tag tom={v.dados_utilizaveis ? "ok" : "err"}>
                {v.dados_utilizaveis ? "sim" : "não"}
              </Tag>
            </td>
          </tr>
          <tr>
            <td>Imagem legível</td>
            <td className={ui.direita}>
              <Tag tom={v.imagem_legivel ? "ok" : "err"}>{v.imagem_legivel ? "sim" : "não"}</Tag>
            </td>
          </tr>
          <tr>
            <td>Sem ressalvas de qualidade</td>
            <td className={ui.direita}>
              <Tag tom={v.aprovado ? "ok" : "warn"}>{v.aprovado ? "sim" : "não"}</Tag>
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
                      <Tag tom={extraido ? "ok" : "err"}>
                        {extraido ? "extraído" : "faltando"}
                      </Tag>
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
