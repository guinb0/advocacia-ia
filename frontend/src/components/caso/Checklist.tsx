"use client";

import { useEffect, useState } from "react";

import type { SituacaoCaso } from "@/lib/types";
import BaixarDocumentos from "@/components/caso/BaixarDocumentos";
import { Aviso, BarraAbas, BotaoAba, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import { prazosAcervo, type PrazosAcervo } from "@/lib/api";
import ItemChecklistLinha from "@/components/caso/ItemChecklistLinha";
import PainelPortal from "@/components/portal/PainelPortal";
import PedidoCliente from "@/components/caso/PedidoCliente";
import EnvioEmLote from "@/components/caso/EnvioEmLote";
import ResumoDocumentos from "@/components/caso/ResumoDocumentos";
import TriagemDocumentos from "@/components/caso/TriagemDocumentos";

type Filtro = "todos" | "obrigatorios" | "falta";

interface Props {
  situacao: SituacaoCaso;
  enviando: string | null;
  erro: string | null;
  onVoltar: () => void;
  onEnviar: (itemCodigo: string, arquivo: File, usarParaRgECpf?: boolean) => void;
  onEnviarLote: (arquivos: File[]) => Promise<void> | void;
  onRemover: (entregaId: string) => void;
  onVincularIdentidade: (entregaId: string, itemCodigo: string) => void;
  onReatribuir: (entregaId: string, itens: string[]) => Promise<void> | void;
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
  onEnviarLote,
  onRemover,
  onVincularIdentidade,
  onReatribuir,
  dentroDoAtendimento = false,
  mostrarPrazos = false,
}: Props) {
  const [filtro, setFiltro] = useState<Filtro>("obrigatorios");
  const { caso, categoria, progresso, itens } = situacao;

  if (!categoria) {
    return (
      <>
        <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
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
      <Botao variante="secundario" className="mb-4" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <div className="px-6 py-[22px] mb-5 border border-borda-forte rounded-cartao bg-papel shadow-cartao">
        <div className="flex justify-between items-center gap-[14px] mb-[14px] flex-wrap">
          <Selo tom="info">{categoria.nome}</Selo>
          <span className="text-tinta-3 text-xs tabular-nums">
            atualizado {desde(caso.atualizado_em || caso.criado_em)}
          </span>
        </div>

        <div className="flex justify-between items-end gap-6 flex-wrap">
          <div>
            <h2 className="m-0 text-xl tracking-[-0.01em]">{caso.cliente}</h2>
            <p className="mt-[6px] mb-0 max-w-[68ch] text-tinta-2 text-sm leading-[1.55]">
              {categoria.descricao}
            </p>
          </div>
          <div className="text-right">
            <span className="text-tinta font-titulo text-[2rem] font-semibold tabular-nums leading-none whitespace-nowrap">
              {progresso.obrigatorios_entregues}
              <span className="text-tinta-3 text-[1.25rem]">/{progresso.obrigatorios_total}</span>
            </span>
            <div className="mt-[2px] text-tinta-3 text-xs">documentos obrigatórios entregues</div>
          </div>
        </div>

        <div
          className="h-2 mt-4 rounded-pill bg-papel-3 overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Documentos obrigatórios entregues"
        >
          <i
            className="block h-full rounded-pill bg-acao transition-[width] duration-[240ms] ease-[ease]"
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="flex gap-2 mt-[14px] flex-wrap">
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
          {(progresso.em_triagem ?? 0) > 0 && (
            <Selo tom="atencao" simbolo="?">
              {progresso.em_triagem ?? 0} para identificar
            </Selo>
          )}
          <Selo tom="neutro">
            {progresso.opcionais_entregues} de {progresso.opcionais_total} opcionais
          </Selo>
        </div>

        {progresso.pronto && (
          <div className="mt-4">
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
        <div className="mb-4">
          <Aviso tom="critico" titulo="Não foi possível concluir a ação">
            {erro}
          </Aviso>
        </div>
      )}

      <EnvioEmLote onEnviar={onEnviarLote} enviando={enviando === "__lote__"} />

      {dentroDoAtendimento && (
        <Aviso tom="info" titulo="Documento no item errado?">
          Em cada arquivo recebido, use <strong>Mover para outro item</strong> para corrigir a
          leitura automática (por exemplo, CAT que caiu em carteira de trabalho). O arquivo e
          os dados lidos permanecem os mesmos.
        </Aviso>
      )}

      <TriagemDocumentos
        entregas={situacao.triagem ?? []}
        itens={itens}
        onAtribuir={onReatribuir}
        onRemover={onRemover}
      />

      <BarraAbas className="mt-5 mb-0" aria-label="Filtrar os documentos">
        {filtros.map((f) => (
          <BotaoAba key={f.id} ativa={filtro === f.id} onClick={() => setFiltro(f.id)}>
            {f.nome}
          </BotaoAba>
        ))}
      </BarraAbas>

      {visiveis.length === 0 ? (
        <Vazio className="mt-4">Nada aqui — tudo resolvido neste filtro.</Vazio>
      ) : (
        <div className="mt-4 border border-borda-forte rounded-cartao bg-papel shadow-cartao overflow-hidden">
          <ul className="list-none m-0 p-0">
            {visiveis.map((item) => (
              <ItemChecklistLinha
                key={item.codigo}
                item={item}
                itensChecklist={itens}
                enviando={enviando === item.codigo}
                onEnviar={onEnviar}
                onRemover={onRemover}
                onVincularIdentidade={onVincularIdentidade}
                onReatribuir={onReatribuir}
                dentroDoAtendimento={dentroDoAtendimento}
              />
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5">
        <ResumoDocumentos itens={itens} />
      </div>

      <div className="flex flex-col gap-5 mt-5">
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
      <div className="mt-5">
        <Cartao
          titulo="O que os processos parecidos mostram"
          subtitulo="O acervo de precedentes não respondeu — ele fica atrás da VPN. O resto da página funciona normalmente."
        />
      </div>
    );
  }
  if (!d) return null;
  const n = (v: number) => v.toLocaleString("pt-BR");
  return (
    <div className="mt-5">
      <Cartao
        titulo="O que os processos parecidos mostram"
        subtitulo={`Medido em ${n(d.processos)} processos do acervo.`}
      >
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
        <p className="mb-4 text-tinta-3 text-sm leading-[1.5]">{d.aviso}</p>
      </Cartao>
    </div>
  );
}
