"use client";

/* A tela do secretário: quem entrevistou, quanto, e como conduziu.
 *
 * Três níveis, e a ordem é a das perguntas que ele faz de verdade: quem fez
 * quantas → quais foram → como foi esta. Cada nível só carrega quando é aberto;
 * a auditoria, em especial, custa uma ida ao modelo e por isso nunca dispara
 * sozinha ao abrir a tela.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao } from "@/components/ui/Basicos";
import {
  ApiError,
  auditarEntrevista,
  listarSupervisao,
  obterTranscricao,
  type Auditoria,
  type ParteLida,
  type PessoaSupervisao,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const SELO_PLACAR_BASE = "px-[10px] py-[2px] rounded-pill text-[0.82rem]";
const SELO_PLACAR: Record<"ok" | "falta" | "incerta", string> = {
  ok: `${SELO_PLACAR_BASE} bg-ok-claro text-ok`,
  falta: `${SELO_PLACAR_BASE} bg-atencao-claro text-atencao`,
  incerta: `${SELO_PLACAR_BASE} bg-papel-3 text-tinta-3`,
};

const SITUACAO: Record<ParteLida["situacao"], { texto: string; classe: "ok" | "falta" | "incerta" }> = {
  feita: { texto: "feita", classe: "ok" },
  parcial: { texto: "parcial", classe: "falta" },
  ausente: { texto: "não aparece", classe: "falta" },
  incerta: { texto: "incerta", classe: "incerta" },
};

/** Uma das partes lidas em voz alta, com o que faltou dela. */
function Parte({ rotulo, parte }: { rotulo: string; parte: ParteLida }) {
  const s = SITUACAO[parte.situacao] ?? SITUACAO.incerta;
  return (
    <div className="[&+&]:mt-[10px]">
      <span className="flex items-center gap-2 font-semibold text-[0.88rem]">
        {rotulo}
        <span className={SELO_PLACAR[s.classe]}>{s.texto}</span>
      </span>
      {parte.faltou.length > 0 && (
        <ul className="list-none m-0 p-0">
          {parte.faltou.map((f, i) => (
            <li key={i} className="py-[5px] border-b border-borda leading-[1.5] last:border-b-0">
              {f}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const ITEM_BASE =
  "flex justify-between gap-[10px] w-full px-[9px] py-[7px] border-0 rounded-[6px] [font:inherit] text-left cursor-pointer";
const ITEM_RESTING = "bg-transparent hover:bg-papel-3";
const ITEM_ABERTO = "bg-acao-clara font-semibold hover:bg-papel-3";

export default function Supervisao({ onVoltar }: Props) {
  const [pessoas, setPessoas] = useState<PessoaSupervisao[]>([]);
  const [totais, setTotais] = useState({ entrevistas: 0, pessoas: 0, sem: 0 });
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [aberta, setAberta] = useState<string | null>(null);
  const [texto, setTexto] = useState<string>("");
  const [carregandoTexto, setCarregandoTexto] = useState(false);

  const [relatorio, setRelatorio] = useState<Auditoria | null>(null);
  const [auditando, setAuditando] = useState(false);
  const [erroAuditoria, setErroAuditoria] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const d = await listarSupervisao();
      setPessoas(d.itens);
      setTotais({
        entrevistas: d.total_entrevistas,
        pessoas: d.total_pessoas,
        sem: d.sem_atribuicao,
      });
      setErro(null);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível carregar.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function abrir(id: string) {
    // Trocar de entrevista limpa o relatório: um relatório de OUTRA entrevista
    // ao lado desta transcrição é pior que relatório nenhum.
    setAberta(id);
    setRelatorio(null);
    setErroAuditoria(null);
    setTexto("");
    setCarregandoTexto(true);
    try {
      setTexto((await obterTranscricao(id)).texto);
    } catch (e) {
      setTexto("");
      setErroAuditoria(e instanceof ApiError ? e.message : "Erro ao ler a transcrição.");
    } finally {
      setCarregandoTexto(false);
    }
  }

  async function auditar(id: string) {
    setAuditando(true);
    setErroAuditoria(null);
    try {
      setRelatorio(await auditarEntrevista(id));
    } catch (e) {
      setErroAuditoria(e instanceof ApiError ? e.message : "Não foi possível auditar.");
    } finally {
      setAuditando(false);
    }
  }

  return (
    <div className="max-w-[1240px] mx-auto px-5 pt-6 pb-16">
      <Botao variante="secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <header className="my-5">
        <h1 className="mb-[6px] mt-0 text-[1.6rem]">Supervisão</h1>
        <p className="m-0 text-tinta-3 max-w-[66ch] leading-[1.5]">
          As entrevistas do escritório por quem as conduziu. Abra uma para ler a
          transcrição e conferir se o roteiro foi seguido.
        </p>
        {!carregando && (
          <p className="mt-[10px] mb-0 text-tinta-3 max-w-[66ch] leading-[1.5]">
            <strong>{totais.entrevistas}</strong> entrevista(s) ·{" "}
            <strong>{totais.pessoas}</strong> pessoa(s)
            {totais.sem > 0 && (
              <>
                {" "}
                ·{" "}
                <span className="text-atencao">{totais.sem} sem quem conduziu</span>
              </>
            )}
          </p>
        )}
      </header>

      {erro && (
        <Aviso tom="critico" titulo="Não foi possível carregar">
          {erro}
        </Aviso>
      )}

      {/* A atribuição passou a ser automática, mas o que já estava gravado antes
        * disso não tem como ser recuperado. Dizer isto evita que o secretário
        * leia o buraco como alguém que não trabalhou. */}
      {totais.sem > 0 && (
        <Aviso tom="atencao" titulo="Entrevistas sem quem conduziu">
          {totais.sem} entrevista(s) foram gravadas antes de o sistema passar a
          registrar quem conduziu. Elas aparecem agrupadas como “não identificado” —
          não é ausência de trabalho, é ausência de dado.
        </Aviso>
      )}

      <div className="grid grid-cols-[320px_minmax(0,1fr)] max-[900px]:grid-cols-1 gap-6 items-start mt-5">
        <section className="border border-borda-forte rounded-[10px] p-4 bg-papel">
          {carregando ? (
            <p className="m-0 text-tinta-3">Carregando…</p>
          ) : pessoas.length === 0 ? (
            <p className="m-0 text-tinta-3">Nenhuma entrevista registrada ainda.</p>
          ) : (
            pessoas.map((p) => (
              <div key={p.entrevistador} className="[&+&]:mt-[18px] [&+&]:pt-[18px] [&+&]:border-t [&+&]:border-borda">
                <h2 className="flex justify-between items-baseline gap-[10px] mb-2 mt-0 text-[0.98rem]">
                  {p.entrevistador}
                  <span className="font-normal text-[0.8rem] text-tinta-3 whitespace-nowrap">
                    {p.quantidade} entrevista{p.quantidade === 1 ? "" : "s"}
                  </span>
                </h2>
                <ul className="list-none m-0 p-0">
                  {p.entrevistas.map((e) => (
                    <li key={e.id}>
                      <button
                        type="button"
                        className={`${ITEM_BASE} ${aberta === e.id ? ITEM_ABERTO : ITEM_RESTING}`}
                        onClick={() => void abrir(e.id)}
                      >
                        <span>{e.realizada_em || e.criado_em?.slice(0, 10) || "sem data"}</span>
                        <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                          {e.caracteres.toLocaleString("pt-BR")} car.
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>

        <section className="border border-borda-forte rounded-[10px] p-4 bg-papel">
          {!aberta ? (
            <p className="m-0 text-tinta-3">Escolha uma entrevista à esquerda para ler a transcrição.</p>
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap mb-[14px]">
                {/* Só o botão base, sem variante — assim como no CSS original. */}
                <button
                  type="button"
                  className="inline-flex items-center justify-center gap-2 min-h-10 px-4 py-[9px] border border-transparent rounded-campo bg-transparent font-ui text-sm font-semibold text-tinta-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => void auditar(aberta)}
                  disabled={auditando || carregandoTexto}
                >
                  {auditando ? "Analisando…" : "Conferir contra o roteiro"}
                </button>
                {auditando && (
                  <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                    A leitura da conversa inteira leva alguns segundos.
                  </span>
                )}
              </div>

              {erroAuditoria && (
                <Aviso tom="critico" titulo="Não deu para analisar">
                  {erroAuditoria}
                </Aviso>
              )}

              {relatorio && (
                <div className="border border-borda-forte rounded-[8px] px-4 py-[14px] bg-papel-2">
                  <h3 className="mt-0">Conferência do roteiro</h3>
                  <p className="mb-3 mt-0 leading-[1.55]">{relatorio.resumo}</p>

                  <div className="flex gap-2 flex-wrap items-center mb-3">
                    <span className={SELO_PLACAR.ok}>{relatorio.cobertas.length} cobertas</span>
                    <span className={SELO_PLACAR.falta}>{relatorio.nao_cobertas.length} não cobertas</span>
                    {relatorio.incertas.length > 0 && (
                      <span className={SELO_PLACAR.incerta}>{relatorio.incertas.length} incertas</span>
                    )}
                    <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                      de {relatorio.total_perguntas}
                    </span>
                  </div>

                  {/* Antes das perguntas: abertura e encerramento são o que o
                    * escritório pediu para seguir à risca, e é o que some
                    * primeiro quando a entrevista corre apertada. */}
                  <div className="mt-[14px]">
                    <h4 className="mb-[6px] mt-0 text-[0.88rem]">Abertura e encerramento</h4>
                    <Parte rotulo="Abertura" parte={relatorio.abertura} />
                    <Parte rotulo="Encerramento" parte={relatorio.encerramento} />
                  </div>

                  {relatorio.faltando_obrigatorias.length > 0 && (
                    <div className="mt-[14px]">
                      <h4 className="mb-[6px] mt-0 text-[0.88rem]">
                        Obrigatórias que não aparecem (
                        {relatorio.faltando_obrigatorias.length} de{" "}
                        {relatorio.total_obrigatorias})
                      </h4>
                      <ul className="list-none m-0 p-0">
                        {relatorio.faltando_obrigatorias.map((p) => (
                          <li key={p.id} className="py-[5px] border-b border-borda leading-[1.5] last:border-b-0">
                            {p.texto} <span className="text-tinta-3 text-[0.82rem] whitespace-nowrap">({p.bloco})</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.observacoes.length > 0 && (
                    <div className="mt-[14px]">
                      <h4 className="mb-[6px] mt-0 text-[0.88rem]">Observações</h4>
                      <ul className="list-none m-0 p-0">
                        {relatorio.observacoes.map((o, i) => (
                          <li key={i} className="py-[5px] border-b border-borda leading-[1.5] last:border-b-0">
                            <strong>{o.item}</strong> — {o.porque}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.pontos_fortes.length > 0 && (
                    <div className="mt-[14px]">
                      <h4 className="mb-[6px] mt-0 text-[0.88rem]">Pontos fortes</h4>
                      <ul className="list-none m-0 p-0">
                        {relatorio.pontos_fortes.map((p, i) => (
                          <li key={i} className="py-[5px] border-b border-borda leading-[1.5] last:border-b-0">
                            {p}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.transcricao_truncada && (
                    <p className="text-tinta-3 text-[0.82rem] whitespace-nowrap">
                      A transcrição é longa e foi analisada até o limite do modelo — o
                      fim da conversa pode não ter entrado.
                    </p>
                  )}
                  <p className="mt-[14px] mb-0 text-tinta-3 text-[0.82rem] leading-[1.5]">{relatorio.aviso}</p>
                </div>
              )}

              <h3 className="my-[18px] mb-2 text-[0.9rem] uppercase tracking-[0.04em] text-tinta-3">Transcrição</h3>
              {carregandoTexto ? (
                <p className="m-0 text-tinta-3">Carregando…</p>
              ) : texto ? (
                <pre className="m-0 px-[14px] py-3 max-h-[460px] overflow-y-auto border border-borda-forte rounded-[8px] bg-papel-2 [font-family:inherit] text-[0.9rem] leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]">
                  {texto}
                </pre>
              ) : (
                <p className="m-0 text-tinta-3">Esta entrevista não tem texto.</p>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
