"use client";

import { useMemo, useState } from "react";
import { ExternalLink, Plus, X } from "lucide-react";

import { Aviso, Botao, Campo, CampoSeletor, RotuloCampo, Selo } from "@/components/ui/Basicos";
import type {
  AcaoConfirmada,
  AnaliseAtendimento,
  FundamentoAnalise,
  NovaAcaoSugerida,
  SugestaoAcao,
} from "@/lib/api/atendimentos";
import type { Categoria } from "@/lib/types";

/* As ações que a análise sugeriu, para o advogado decidir.
 *
 * Nada é aceito sozinho: cada ação vira um caso (a ação é a categoria do caso),
 * e caso errado é checklist errado. A confiança alta só vem pré-marcada; quem
 * confirma é o advogado. Ação fora do catálogo ("NOVA AÇÃO IDENTIFICADA") nasce
 * como tipo de caso rascunho, marcado para revisão. */

const MAXIMO_ACOES = 6;
const CONFIANCA_PRE_MARCADA = 0.7;

type Escolha =
  | { chave: string; tipo: "sugestao"; sugestao: SugestaoAcao }
  | { chave: string; tipo: "nova"; nova: NovaAcaoSugerida }
  | { chave: string; tipo: "manual"; codigo: string; nome: string };

function Fundamentos({ itens }: { itens: FundamentoAnalise[] }) {
  if (!itens.length) return null;
  return (
    <div className="mt-2">
      <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-tinta-3">Fundamentos</span>
      <ul className="m-0 mt-1 list-none space-y-1 p-0">
        {itens.map((f) => (
          <li key={f.authority_id} className="text-xs leading-[1.5] text-tinta-2">
            <span className="mr-1">
              <Selo tom={f.verificada ? "ok" : "neutro"} simbolo={f.verificada ? "✓" : "•"}>
                {f.verificada ? "verificado" : f.tipo || "fonte"}
              </Selo>
            </span>
            {f.url ? (
              <a href={f.url} target="_blank" rel="noreferrer" className="font-semibold text-acao underline">
                {f.titulo} <ExternalLink aria-hidden className="inline size-3" />
              </a>
            ) : (
              <strong>{f.titulo}</strong>
            )}
            {f.motivo && <span className="text-tinta-3"> — {f.motivo}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Lista({ titulo, itens, tom }: { titulo: string; itens: string[]; tom?: "ok" | "atencao" }) {
  if (!itens.length) return null;
  const cor = tom === "ok" ? "text-ok" : tom === "atencao" ? "text-atencao" : "text-tinta-3";
  return (
    <div className="mt-2">
      <span className={`text-[11px] font-bold uppercase tracking-[0.08em] ${cor}`}>{titulo}</span>
      <ul className="m-0 mt-1 pl-[18px] text-xs leading-[1.55] text-tinta-2">
        {itens.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Marcador({
  marcado,
  onAlternar,
  rotulo,
  desabilitado,
}: {
  marcado: boolean;
  onAlternar: () => void;
  rotulo: string;
  desabilitado?: boolean;
}) {
  return (
    <label className={`inline-flex items-center gap-2 text-sm font-semibold ${desabilitado ? "text-tinta-desabilitada" : "cursor-pointer text-tinta"}`}>
      <input
        type="checkbox"
        className="size-4 accent-[var(--acao)]"
        checked={marcado}
        disabled={desabilitado}
        onChange={onAlternar}
      />
      {rotulo}
    </label>
  );
}

interface Props {
  analise: AnaliseAtendimento | null;
  categorias: Categoria[];
  clienteInicial?: string;
  confirmando: boolean;
  onConfirmar: (acoes: AcaoConfirmada[], cliente: string) => void;
  onRefazer?: () => void;
}

export default function SugestoesDeAcao({
  analise,
  categorias,
  clienteInicial = "",
  confirmando,
  onConfirmar,
  onRefazer,
}: Props) {
  const resultado = analise?.resultado ?? null;
  const sugestoes = useMemo(() => resultado?.sugestoes ?? [], [resultado]);
  const novas = useMemo(() => resultado?.novas_acoes ?? [], [resultado]);

  const [marcadas, setMarcadas] = useState<Set<string>>(
    () => new Set(sugestoes.filter((s) => s.confianca >= CONFIANCA_PRE_MARCADA).map((s) => `s:${s.tipo_codigo}`)),
  );
  const [manuais, setManuais] = useState<{ codigo: string; nome: string }[]>([]);
  const [escolhaManual, setEscolhaManual] = useState("");
  const [cliente, setCliente] = useState(clienteInicial);

  const alternar = (chave: string) =>
    setMarcadas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(chave)) proximo.delete(chave);
      else proximo.add(chave);
      return proximo;
    });

  const codigosUsados = new Set([
    ...sugestoes.filter((s) => marcadas.has(`s:${s.tipo_codigo}`)).map((s) => s.tipo_codigo),
    ...manuais.map((m) => m.codigo),
  ]);

  const escolhidas: Escolha[] = [
    ...sugestoes
      .filter((s) => marcadas.has(`s:${s.tipo_codigo}`))
      .map((s) => ({ chave: `s:${s.tipo_codigo}`, tipo: "sugestao" as const, sugestao: s })),
    ...novas
      .filter((n) => marcadas.has(`n:${n.id}`))
      .map((n) => ({ chave: `n:${n.id}`, tipo: "nova" as const, nova: n })),
    ...manuais.map((m) => ({ chave: `m:${m.codigo}`, tipo: "manual" as const, codigo: m.codigo, nome: m.nome })),
  ];
  const excedeu = escolhidas.length > MAXIMO_ACOES;

  const confirmar = () => {
    const acoes: AcaoConfirmada[] = escolhidas.map((e) =>
      e.tipo === "sugestao"
        ? { codigo: e.sugestao.tipo_codigo, nome: e.sugestao.nome, origem: e.sugestao.origem === "triagem" ? "triagem" : "ia" }
        : e.tipo === "nova"
          ? { nome: e.nova.nome, origem: "ia", nova: e.nova }
          : { codigo: e.codigo, nome: e.nome, origem: "manual" },
    );
    onConfirmar(acoes, cliente.trim());
  };

  const adicionarManual = () => {
    const categoria = categorias.find((c) => c.codigo === escolhaManual);
    if (!categoria || codigosUsados.has(categoria.codigo)) return;
    setManuais((atual) => [...atual, { codigo: categoria.codigo, nome: categoria.nome }]);
    setEscolhaManual("");
  };

  return (
    <section className="mt-6 overflow-hidden rounded-cartao border border-borda-forte bg-papel shadow-cartao">
      <header className="border-b border-borda bg-papel-2 px-4 py-4 sm:px-5">
        <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-acao">Análise jurídica</span>
        <h3 className="mt-1 text-lg font-semibold text-tinta">Ações sugeridas</h3>
        <p className="mb-0 mt-1 max-w-[72ch] text-xs leading-[1.55] text-tinta-3">
          Marque as ações que o escritório vai propor. Cada ação confirmada vira um caso, com o checklist de documentos dela.
        </p>
      </header>

      <div className="space-y-4 p-4 sm:p-5">
        {resultado?.reserva && (
          <Aviso tom="atencao" titulo="A análise automática não concluiu">
            {analise?.erro || "As sugestões abaixo vieram da triagem da entrevista."} Confira com atenção ou adicione a ação manualmente.
          </Aviso>
        )}
        {resultado?.observacoes && (
          <p className="m-0 max-w-[80ch] text-sm leading-[1.6] text-tinta-2">{resultado.observacoes}</p>
        )}
        {resultado?.triagem?.divergiu && (
          <Aviso tom="info" titulo="A análise divergiu da triagem ao vivo">
            A ação que a triagem apontou durante a entrevista não é a principal aqui. Compare as justificativas antes de decidir.
          </Aviso>
        )}

        {sugestoes.length === 0 && novas.length === 0 && (
          <Aviso tom="neutro" titulo="Nenhuma ação foi sugerida">
            Adicione a ação manualmente abaixo.
          </Aviso>
        )}

        {sugestoes.map((s) => {
          const chave = `s:${s.tipo_codigo}`;
          const marcado = marcadas.has(chave);
          return (
            <article
              key={chave}
              className={`rounded-campo border px-4 py-3 ${marcado ? "border-acao bg-acao-clara" : "border-borda bg-papel"}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Marcador marcado={marcado} onAlternar={() => alternar(chave)} rotulo={s.nome} />
                <div className="flex flex-wrap gap-1">
                  <Selo tom={s.confianca >= 0.7 ? "ok" : s.confianca >= 0.4 ? "atencao" : "neutro"}>
                    {Math.round(s.confianca * 100)}% de confiança
                  </Selo>
                  {s.origem === "triagem" && <Selo tom="neutro">da triagem</Selo>}
                </div>
              </div>
              {s.justificativa && <p className="mb-0 mt-2 text-xs leading-[1.55] text-tinta-2">{s.justificativa}</p>}
              <div className="grid gap-x-6 sm:grid-cols-2">
                <Lista titulo="Critérios atendidos" itens={s.criterios_atendidos} tom="ok" />
                <Lista titulo="Critérios pendentes" itens={s.criterios_pendentes} tom="atencao" />
              </div>
              <Lista titulo="Documentos mínimos faltantes" itens={s.documentos_minimos_faltantes} tom="atencao" />
              <Fundamentos itens={s.fundamentos} />
            </article>
          );
        })}

        {novas.map((n) => {
          const chave = `n:${n.id}`;
          const marcado = marcadas.has(chave);
          return (
            <article
              key={chave}
              className={`rounded-campo border-2 px-4 py-3 ${marcado ? "border-atencao bg-atencao-claro" : "border-atencao-borda bg-papel"}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Marcador marcado={marcado} onAlternar={() => alternar(chave)} rotulo={n.nome} />
                <Selo tom="atencao" simbolo="★">NOVA AÇÃO IDENTIFICADA</Selo>
              </div>
              {n.descricao && <p className="mb-0 mt-2 text-xs leading-[1.55] text-tinta-2">{n.descricao}</p>}
              {n.justificativa && <p className="mb-0 mt-1 text-xs leading-[1.55] text-tinta-3">{n.justificativa}</p>}
              <div className="grid gap-x-6 sm:grid-cols-2">
                <Lista titulo="Critérios" itens={n.criterios} />
                <Lista
                  titulo="Documentos"
                  itens={n.documentos.map((d) => (d.minimo ? `${d.nome} (documento mínimo)` : d.nome))}
                />
              </div>
              <Lista titulo="Informações necessárias" itens={n.informacoes_necessarias} />
              <Fundamentos itens={n.fundamentos} />
              <p className="mb-0 mt-2 text-[11px] leading-[1.5] text-tinta-3">
                Aceitar cria um tipo de caso novo como rascunho (&quot;Gerado por IA — requer revisão&quot;) em Tipos de caso.
              </p>
            </article>
          );
        })}

        <div className="rounded-campo border border-dashed border-borda-forte bg-papel-2 px-4 py-3">
          <RotuloCampo htmlFor="acao-manual">Adicionar ação manualmente</RotuloCampo>
          <div className="mt-1 flex flex-wrap gap-2">
            <CampoSeletor
              id="acao-manual"
              className="min-w-[240px] flex-1"
              value={escolhaManual}
              onChange={(e) => setEscolhaManual(e.target.value)}
            >
              <option value="">Escolha um tipo de caso…</option>
              {categorias
                .filter((c) => !codigosUsados.has(c.codigo))
                .map((c) => (
                  <option key={c.codigo} value={c.codigo}>
                    {c.nome}
                  </option>
                ))}
            </CampoSeletor>
            <Botao variante="secundario" onClick={adicionarManual} disabled={!escolhaManual}>
              <Plus aria-hidden className="size-4" /> Adicionar
            </Botao>
          </div>
          {manuais.length > 0 && (
            <ul className="m-0 mt-2 flex list-none flex-wrap gap-2 p-0">
              {manuais.map((m) => (
                <li key={m.codigo} className="inline-flex items-center gap-1 rounded-pill border border-acao-borda bg-acao-clara px-3 py-1 text-xs font-semibold text-acao">
                  {m.nome}
                  <button
                    type="button"
                    aria-label={`Remover ${m.nome}`}
                    className="ml-1 text-acao hover:text-critico"
                    onClick={() => setManuais((atual) => atual.filter((x) => x.codigo !== m.codigo))}
                  >
                    <X aria-hidden className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-campo border border-borda bg-papel px-4 py-3">
          <RotuloCampo htmlFor="cliente-do-caso">Nome do cliente</RotuloCampo>
          <p className="m-0 text-[11px] text-tinta-3">Necessário para criar os casos das ações selecionadas.</p>
          <Campo
            id="cliente-do-caso"
            className="mt-1"
            value={cliente}
            placeholder="Nome completo do cliente"
            onChange={(e) => setCliente(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-borda pt-4">
          <Botao
            variante="primario"
            onClick={confirmar}
            disabled={escolhidas.length === 0 || excedeu || cliente.trim().length < 2}
            carregando={confirmando}
            textoCarregando="Criando caso(s)…"
          >
            {escolhidas.length > 1 ? `Confirmar ${escolhidas.length} ações e criar os casos` : "Confirmar ação e criar o caso"}
          </Botao>
          {onRefazer && (
            <Botao variante="discreto" onClick={onRefazer} disabled={confirmando}>
              Refazer análise
            </Botao>
          )}
          <span className="text-xs text-tinta-3">
            {excedeu
              ? `No máximo ${MAXIMO_ACOES} ações por atendimento.`
              : escolhidas.length === 0
                ? "Marque ao menos uma ação."
                : cliente.trim().length < 2
                  ? "Informe o nome do cliente para criar o caso."
                : escolhidas.map((e) => (e.tipo === "sugestao" ? e.sugestao.nome : e.tipo === "nova" ? e.nova.nome : e.nome)).join(" · ")}
          </span>
        </div>
      </div>
    </section>
  );
}
