"use client";

import { useEffect, useState } from "react";

import type { SituacaoCaso } from "@/lib/types";
import BaixarDocumentos from "./BaixarDocumentos";
import { Aviso, Selo } from "./Basicos";
import { prazosAcervo, type PrazosAcervo } from "@/lib/api";
import estilos from "./Checklist.module.css";
import ItemChecklistLinha from "./ItemChecklistLinha";
import PainelPortal from "./PainelPortal";
import PedidoCliente from "./PedidoCliente";
import ui from "./ui.module.css";

type Filtro = "todos" | "obrigatorios" | "falta";

interface Props {
  situacao: SituacaoCaso;
  enviando: string | null;
  erro: string | null;
  onVoltar: () => void;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
  /** O checklist está dentro do atendimento, não na tela do caso.
   *
   * Ali a chamada já está na tela e o advogado já entrou na sala do caso ao
   * criá-lo: o painel do portal não pode abrir uma segunda, com câmera e tudo,
   * no meio dos documentos. O link e a senha continuam à vista — eles são para
   * MANDAR ao cliente, que é quem precisa deles. */
  dentroDoAtendimento?: boolean;
  /** Mostra a estatística de prazos do acervo no fim da página.
   *
   * Desligado por padrão porque este mesmo componente desenha o PORTAL DO
   * CLIENTE (`app/portal/[token]/page.tsx`). Lá quem olha é o cliente, e taxa de
   * recurso e duração de processo do escritório não são informação dele — além
   * de a rota exigir papel de advogado, o que renderia um bloco quebrado. */
  mostrarPrazos?: boolean;
}

/** "há 2 h", "há 3 dias" — a mesma leitura do cabeçalho no desenho. */
function desde(iso: string): string {
  const minutos = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (!Number.isFinite(minutos) || minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  const dias = Math.floor(horas / 24);
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

export default function Checklist({
  situacao,
  enviando,
  erro,
  onVoltar,
  onEnviar,
  onRemover,
  onVincularIdentidade,
  dentroDoAtendimento = false,
  mostrarPrazos = false,
}: Props) {
  const [filtro, setFiltro] = useState<Filtro>("obrigatorios");
  const { caso, categoria, progresso, itens } = situacao;

  if (!categoria) {
    return (
      <>
        <button
          type="button"
          className={`botao botao--secundario ${estilos.voltar}`}
          onClick={onVoltar}
        >
          ← Voltar para a carteira
        </button>
        <Aviso tom="critico" titulo="Categoria indisponível">
          {situacao.erro ?? "O tipo de ação deste caso não pôde ser carregado."}
        </Aviso>
      </>
    );
  }

  const naoResolvidos = itens.filter((i) => i.status !== "entregue").length;

  const visiveis = itens.filter((item) => {
    if (filtro === "obrigatorios") return item.obrigatorio;
    if (filtro === "falta") return item.status !== "entregue";
    return true;
  });

  const filtros: { id: Filtro; nome: string }[] = [
    { id: "obrigatorios", nome: `Obrigatórios (${progresso.obrigatorios_total})` },
    { id: "falta", nome: `Falta resolver (${naoResolvidos})` },
    { id: "todos", nome: `Todos os documentos (${itens.length})` },
  ];

  const pct = Math.max(0, Math.min(100, progresso.percentual_obrigatorios));

  return (
    <>
      <button
        type="button"
        className={`botao botao--secundario ${estilos.voltar}`}
        onClick={onVoltar}
      >
        ← Voltar para a carteira
      </button>

      <div className={estilos.cartaoCaso}>
        <div className={estilos.faixaCaso}>
          <Selo tom="info">{categoria.nome}</Selo>
          <span className={estilos.faixaMeta}>
            atualizado {desde(caso.atualizado_em || caso.criado_em)}
          </span>
        </div>

        <div className={estilos.identificacaoCaso}>
          <div>
            <h2 className={estilos.cliente}>{caso.cliente}</h2>
            <p className={estilos.descricao}>{categoria.descricao}</p>
          </div>
          <div className={estilos.numeros}>
            <span className={estilos.numeroGrande}>
              {progresso.obrigatorios_entregues}
              <span className={estilos.numeroTotal}>/{progresso.obrigatorios_total}</span>
            </span>
            <div className={estilos.numeroRotulo}>documentos obrigatórios entregues</div>
          </div>
        </div>

        <div
          className={estilos.barra}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos obrigatórios entregues"
        >
          <i className={estilos.barraPreenchimento} style={{ width: `${pct}%` }} />
        </div>

        <div className={estilos.contadores}>
          {progresso.obrigatorios_pendentes > 0 && (
            <Selo tom="critico" simbolo="✕">
              {progresso.obrigatorios_pendentes} sem arquivo
            </Selo>
          )}
          {progresso.itens_a_conferir > 0 && (
            <Selo tom="atencao" simbolo="!">
              {progresso.itens_a_conferir} a conferir
            </Selo>
          )}
          <Selo tom="neutro">
            {progresso.opcionais_entregues} de {progresso.opcionais_total} opcionais
          </Selo>
        </div>

        {progresso.pronto && (
          <div style={{ marginTop: 16 }}>
            <Aviso tom="ok" titulo="Instrução completa">
              Todos os documentos obrigatórios foram entregues e conferidos. O caso está pronto
              para a inicial.
            </Aviso>
          </div>
        )}

        {/* O pacote fica logo abaixo do "instrução completa": é o passo
          * seguinte a ele. Aparece antes disso também, porque baixar o que já
          * chegou é útil no meio do caminho — mas só ganha o botão cheio
          * quando o checklist fecha. A contagem é de ENTREGAS DISTINTAS: uma
          * CIN que atende RG e CPF aparece em dois itens e é um arquivo só. */}
        <BaixarDocumentos
          casoId={caso.id}
          total={new Set(itens.flatMap((i) => i.entregas.map((e) => e.id))).size}
          pronto={progresso.pronto}
        />
      </div>

      {erro && (
        <div style={{ marginBottom: 16 }}>
          <Aviso tom="critico" titulo="Não foi possível concluir a ação">
            {erro}
          </Aviso>
        </div>
      )}

      <div className={estilos.abas} role="tablist" aria-label="Filtrar os documentos">
        {filtros.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filtro === f.id}
            className={`${estilos.aba} ${filtro === f.id ? estilos.abaAtiva : ""}`}
            onClick={() => setFiltro(f.id)}
          >
            {f.nome}
          </button>
        ))}
      </div>

      {visiveis.length === 0 ? (
        <div style={{ marginTop: 16 }}>
          <div className={ui.vazio}>Nada aqui — tudo resolvido neste filtro.</div>
        </div>
      ) : (
        <div className={estilos.painelLista}>
          <ul className={estilos.lista}>
            {visiveis.map((item) => (
              <ItemChecklistLinha
                key={item.codigo}
                item={item}
                enviando={enviando === item.codigo}
                onEnviar={onEnviar}
                onRemover={onRemover}
                onVincularIdentidade={onVincularIdentidade}
              />
            ))}
          </ul>
        </div>
      )}

      <div className={estilos.blocoFinal}>
        {/* Dentro do atendimento a chamada já está na tela e o advogado já
            entrou na sala do caso — o painel do portal não abre outra. */}
        <PainelPortal casoId={caso.id} semChamada={dentroDoAtendimento} />
        <PedidoCliente casoId={caso.id} progresso={progresso} naoResolvidos={naoResolvidos} />
      </div>

      {mostrarPrazos && <Prazos />}
    </>
  );
}

/* O que os processos parecidos mostram sobre tempo e recurso.
 *
 * Fica no FIM da aba de documentos porque é a pergunta que vem quando a papelada
 * acaba: "e agora, quanto demora?".
 *
 * Deliberadamente magro. O acervo não sustenta "tempo médio de etapa": só 20%
 * dos processos têm mais de uma data, e esses são justamente os que recorreram,
 * ou seja, os mais longos. Por isso o número vai com a AMOSTRA ao lado e
 * rotulado como observado, nunca como previsão — prazo dito ao cliente não pode
 * ser "mais ou menos". Ver `docs/PRAZOS.md` para o que falta ingerir. */
function Prazos() {
  const [d, setD] = useState<PrazosAcervo | null>(null);
  const [falhou, setFalhou] = useState(false);
  useEffect(() => {
    void prazosAcervo()
      .then(setD)
      .catch(() => setFalhou(true));
  }, []);
  /* Falhar CALADO foi um erro meu: o bloco sumia e não havia como saber se era
   * o acervo fora do ar ou se ele nunca tinha sido posto na tela. Agora diz. */
  if (falhou) {
    return (
      <div className={estilos.blocoFinal}>
        <div className="cartao">
          <h2 className="tituloCartao">O que os processos parecidos mostram</h2>
          <p className="subtituloCartao">
            O acervo de precedentes não respondeu — ele fica atrás da VPN. O resto
            da página funciona normalmente.
          </p>
        </div>
      </div>
    );
  }
  if (!d) return null;
  const n = (v: number) => v.toLocaleString("pt-BR");
  return (
    <div className={estilos.blocoFinal}>
      <div className="cartao">
        <h2 className="tituloCartao">O que os processos parecidos mostram</h2>
        <p className="subtituloCartao">
          Medido em {n(d.processos)} processos do acervo.
        </p>
        <ul>
          <li>
            <strong>{d.percentual_recurso}%</strong> foram para a segunda instância (
            {n(d.segunda_instancia)} de {n(d.processos)}).
          </li>
          {d.duracao.mediana_dias !== null && (
            <li>
              Do primeiro ao último documento registrado:{" "}
              <strong>{d.duracao.mediana_dias} dias</strong> na mediana,{" "}
              {d.duracao.p90_dias} dias em 9 de cada 10 —{" "}
              <em>
                medido em apenas {d.duracao.processos_medidos} processos, os que têm
                mais de um evento datado
              </em>
              .
            </li>
          )}
        </ul>
        <p className="subtituloCartao">{d.aviso}</p>
      </div>
    </div>
  );
}
