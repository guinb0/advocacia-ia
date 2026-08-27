"use client";

/**
 * O roteiro inteiro com o que foi respondido — a revisão do atendimento.
 *
 * Enquanto a entrevista corre, a tela mostra UMA pergunta de cada vez: é o que
 * mantém quem conduz olhando para o cliente, e não para uma parede de 89 campos.
 * Mas na hora de revisar a conversa é o contrário — quem confere precisa ver
 * tudo de uma vez, na ordem do documento do escritório, para achar o que ficou
 * para trás antes de o cliente desligar.
 *
 * A LISTA NÃO É A DO ROTEIRO INTEIRO, E ISSO É DELIBERADO
 *
 * Só entram os blocos que valeram PARA ESTE caso. O roteiro é ramificado: quem
 * não sofreu assalto nunca viu o módulo de assalto, e listar aquelas perguntas
 * como "não respondidas" encheria a revisão de pendências falsas — a mais fácil
 * de ignorar, e ignorar pendência é o hábito que faz a pendência de verdade
 * passar. A mesma regra da condução vale aqui: módulo aberto pelo rastreio, e
 * pergunta condicional só quando a pergunta-pai a abriu.
 *
 * O QUE FICA EM DESTAQUE
 *
 * O que falta, não o que já está pronto. Resposta dada é texto comum; pergunta
 * obrigatória sem resposta ganha marca — é ela que ainda dá para colher com o
 * cliente na linha, e é só isso que a revisão precisa gritar.
 */

import { useEffect, useMemo, useState } from "react";

import { Aviso, Selo } from "@/components/ui/Basicos";
import { ApiError, obterRoteiro } from "@/lib/api";
import type { Pergunta, RoteiroCompleto } from "@/lib/types";

type Respostas = Record<string, string | string[]>;

function respondida(valor: string | string[] | undefined): boolean {
  return Array.isArray(valor) ? valor.length > 0 : Boolean(String(valor ?? "").trim());
}

/** Mesma regra da condução: sem a pergunta-pai respondida, a filha não existe. */
function dependenciaAberta(p: Pergunta, respostas: Respostas): boolean {
  if (!p.depende_de) return true;
  const valor = String(respostas[p.depende_de] ?? "").trim().toLowerCase();
  const esperado = p.depende_valor.trim().toLowerCase();
  if (esperado === "nao" || esperado === "não") return valor === "nao" || valor === "não";
  return valor === esperado;
}

function comoTexto(valor: string | string[] | undefined): string {
  if (Array.isArray(valor)) return valor.join(", ");
  return String(valor ?? "").trim();
}

interface Props {
  respostas: Respostas;
  codigo?: string;
  /** Abre o painel. Vira `true` quando a entrevista encerra — é o momento em
   *  que a conferência deixa de ser distração e passa a ser o trabalho. */
  aberto?: boolean;
}

export default function RespostasDoRoteiro({
  respostas,
  codigo = "empregado_publico",
  aberto = false,
}: Props) {
  const [roteiro, setRoteiro] = useState<RoteiroCompleto | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  /* FECHADO POR PADRÃO, e isto é sobre atenção, não sobre espaço.
   *
   * Enquanto a conversa corre, quem conduz olha para a pergunta da vez; uma
   * lista de 89 respostas aberta ao lado disputa o olho com o cliente. Ao
   * encerrar, a prioridade se inverte — o que falta ainda dá para colher, e é
   * aí que ele abre sozinho.
   *
   * Depois de aberto, quem manda é o clique: o estado só acompanha `aberto`
   * enquanto ninguém tiver mexido, senão fechar o painel no fim da entrevista
   * seria desfeito no próximo render. */
  const [expandido, setExpandido] = useState(aberto);
  const [mexido, setMexido] = useState(false);
  useEffect(() => {
    if (!mexido) setExpandido(aberto);
  }, [aberto, mexido]);

  useEffect(() => {
    let cancelado = false;
    obterRoteiro(codigo)
      .then((r) => {
        if (!cancelado) setRoteiro(r);
      })
      .catch((e) => {
        if (!cancelado) setErro(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      cancelado = true;
    };
  }, [codigo]);

  const blocos = useMemo(() => {
    if (!roteiro) return [];
    const positivos = new Set(
      Object.entries(roteiro.mapa_rastreio)
        .filter(([perguntaId]) => respostas[perguntaId] === "sim")
        .map(([, modulo]) => modulo),
    );
    return roteiro.blocos
      .filter((b) => !b.modulo || positivos.has(b.modulo))
      .map((b) => ({
        ...b,
        perguntas: b.perguntas.filter((p) => dependenciaAberta(p, respostas)),
      }))
      .filter((b) => b.perguntas.length > 0);
  }, [roteiro, respostas]);

  const faltando = useMemo(
    () =>
      blocos.flatMap((b) =>
        b.perguntas.filter((p) => p.obrigatoria && !respondida(respostas[p.id])),
      ),
    [blocos, respostas],
  );

  const total = blocos.reduce((soma, b) => soma + b.perguntas.length, 0);
  const respondidas = blocos.reduce(
    (soma, b) => soma + b.perguntas.filter((p) => respondida(respostas[p.id])).length,
    0,
  );

  if (erro) return <Aviso tom="critico">Não foi possível carregar o roteiro: {erro}</Aviso>;
  if (!roteiro) return null;

  return (
    <section className="mt-6 border-t border-borda pt-[14px]" aria-labelledby="titulo-respostas">
      {/* `details` nativo, e não um painel próprio: ele já traz teclado, leitor
        * de tela e o estado aberto/fechado sem nenhuma linha de JavaScript. */}
      <details
        open={expandido}
        onToggle={(e) => {
          const agora = (e.currentTarget as HTMLDetailsElement).open;
          if (agora !== expandido) {
            setMexido(true);
            setExpandido(agora);
          }
        }}
      >
        <summary className="cursor-pointer list-none flex items-center gap-[10px] flex-wrap">
          <span className="text-[10px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
            ROTEIRO RESPONDIDO
          </span>
          <Selo tom={faltando.length ? "atencao" : "ok"} simbolo={faltando.length ? "!" : "✓"}>
            {respondidas} de {total}
          </Selo>
          <span className="text-tinta-3 text-[11px] font-ui underline underline-offset-[3px]">
            {expandido ? "recolher" : "ver respostas"}
          </span>
        </summary>

        <h3 id="titulo-respostas" className="mb-[6px] mt-3 font-medium text-[18px] leading-[1.25] font-titulo">
          Confira o que a entrevista colheu
        </h3>

      {faltando.length > 0 && (
        <div className="mt-2 mb-3">
          <Aviso tom="atencao" titulo={`${faltando.length} pergunta(s) obrigatória(s) sem resposta`}>
            Ainda dá para colher com o cliente na linha:{" "}
            {faltando.slice(0, 4).map((p) => p.texto).join(" · ")}
            {faltando.length > 4 ? ` · e mais ${faltando.length - 4}` : ""}
          </Aviso>
        </div>
      )}

      <div className="mt-3 flex flex-col gap-4">
        {blocos.map((bloco) => (
          <div key={bloco.id}>
            <div className="flex items-center gap-2 flex-wrap mb-[6px]">
              <strong className="text-tinta text-[13px] font-titulo">{bloco.titulo}</strong>
              {/* Dizer que o bloco é de outra equipe evita que a revisão cobre
                  de quem conduziu algo que o roteiro entregou à Documentação. */}
              {bloco.delegado_a && <Selo tom="neutro">{bloco.delegado_a}</Selo>}
            </div>

            <dl className="m-0 grid gap-x-4 gap-y-[6px] sm:grid-cols-[minmax(180px,34%)_1fr]">
              {bloco.perguntas.map((p) => {
                const valor = comoTexto(respostas[p.id]);
                const vazia = !valor;
                return (
                  <div key={p.id} className="contents">
                    <dt className="text-tinta-3 text-xs leading-[1.5] font-ui pt-[2px]">
                      {p.texto}
                      {p.obrigatoria && vazia && (
                        <span className="text-critico font-semibold"> *</span>
                      )}
                    </dt>
                    <dd
                      className={`m-0 text-[13px] leading-[1.55] font-ui ${
                        vazia
                          ? p.obrigatoria
                            ? "text-critico"
                            : "text-tinta-3 italic"
                          : "text-tinta"
                      }`}
                    >
                      {valor || (p.obrigatoria ? "não respondida" : "—")}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
          ))}
        </div>
      </details>
    </section>
  );
}
