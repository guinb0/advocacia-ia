"use client";

/* Os documentos do caso mostrados DENTRO da conversa.
 *
 * É a metade do pedido que o link não atende: quem perguntou "quais documentos tem o
 * caso da Maria?" muitas vezes só quer conferir se a CAT chegou — e sair para o dossiê
 * para isso custa o fio da conversa e a volta.
 *
 * O que ele mostra é o que o sistema JÁ tem. Nada aqui é calculado de novo nem pedido a
 * um modelo: a lista é a do checklist, com o mesmo estado de conferência que o dossiê
 * mostra. Cada arquivo abre pela rota que já existe (`/api/entregas/{id}/arquivo`), que
 * confere a sessão de quem clicou. */

import { Selo } from "@/components/ui/Basicos";
import estilos from "@/components/chat/Chat.module.css";
import { urlApi } from "@/lib/api";
import type { EntregaDoChat, PainelDeDocumentos as Painel } from "@/lib/chat";

interface Props {
  painel: Painel;
  /** Leva ao checklist do caso — o lugar de AGIR sobre o que a lista mostra. */
  onAbrirCaso?: (casoId: string) => void;
}

/** O selo de cada arquivo. Três estados, e não dois.
 *
 * "Ninguém conferiu ainda" não é "não confere": o primeiro espera trabalho, o segundo
 * denuncia o arquivo errado. Achatar os dois faria a tela acusar de errado todo
 * documento recém-chegado. */
function seloDaEntrega(entrega: EntregaDoChat) {
  if (entrega.tipoConfere === true) {
    return <Selo tom="ok" simbolo="✓">{entrega.tipoDetectado || "confere"}</Selo>;
  }
  if (entrega.tipoConfere === false) {
    return (
      <Selo tom="critico" simbolo="✕">
        lido como {entrega.tipoDetectado || "outro tipo"}
      </Selo>
    );
  }
  return <Selo tom="neutro">a conferir</Selo>;
}

export default function PainelDeDocumentos({ painel, onAbrirCaso }: Props) {
  const { caso, entregas, pendentes, entregasOcultas } = painel;

  return (
    <div className={estilos.painel}>
      <div className={estilos.cabecalhoDoPainel}>
        <span className={estilos.nomeDoPainel}>
          Documentos de {caso.cliente || "caso sem cliente"}
        </span>
        <span className={estilos.exemploDaSugestao}>
          {entregas.length + entregasOcultas} entregue(s) · {pendentes.length} pendente(s)
        </span>
      </div>

      {entregas.length > 0 ? (
        <div className={estilos.listaDeArquivos}>
          {entregas.map((entrega) => (
            <div key={entrega.id} className={estilos.arquivo}>
              <span className={estilos.nomeDoArquivo} title={entrega.arquivo}>
                {entrega.arquivo || "arquivo sem nome"}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {seloDaEntrega(entrega)}
                {/* Abre em outra aba: o chat fica onde está, com a pergunta e a
                    resposta intactas atrás do documento. */}
                <a
                  className={estilos.abrirArquivo}
                  href={urlApi(entrega.arquivoUrl)}
                  target="_blank"
                  rel="noreferrer"
                >
                  abrir
                </a>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className={estilos.exemploDaSugestao}>
          Nenhum documento foi entregue neste caso ainda.
        </p>
      )}

      {entregasOcultas > 0 && (
        <p className={estilos.exemploDaSugestao}>
          Mais {entregasOcultas} arquivo(s) estão no dossiê — o chat mostra os primeiros
          para não virar uma segunda carteira aqui dentro.
        </p>
      )}

      {pendentes.length > 0 && (
        <div className={estilos.blocoDeApoio}>
          <span className={estilos.tituloDoBloco}>Ainda falta</span>
          <ul className={estilos.listaSimples}>
            {pendentes.slice(0, 8).map((item) => (
              <li key={item.nome}>
                {item.nome}
                {item.motivo ? ` — ${item.motivo}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {onAbrirCaso && caso.id && (
        <div className={estilos.atalhos}>
          <button
            type="button"
            className={estilos.atalho}
            onClick={() => onAbrirCaso(caso.id)}
          >
            Abrir o checklist para cobrar o que falta
          </button>
        </div>
      )}
    </div>
  );
}
