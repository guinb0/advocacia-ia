"use client";

/* A tela do secretário: quem entrevistou, quanto, e como conduziu.
 *
 * Três níveis, e a ordem é a das perguntas que ele faz de verdade: quem fez
 * quantas → quais foram → como foi esta. Cada nível só carrega quando é aberto;
 * a auditoria, em especial, custa uma ida ao modelo e por isso nunca dispara
 * sozinha ao abrir a tela.
 */

import { useCallback, useEffect, useState } from "react";

import { Aviso } from "@/components/Basicos";
import {
  ApiError,
  auditarEntrevista,
  listarSupervisao,
  obterTranscricao,
  type Auditoria,
  type ParteLida,
  type PessoaSupervisao,
} from "@/lib/api";
import estilos from "./Supervisao.module.css";

interface Props {
  onVoltar: () => void;
}

const SITUACAO: Record<ParteLida["situacao"], { texto: string; classe: string }> = {
  feita: { texto: "feita", classe: "ok" },
  parcial: { texto: "parcial", classe: "falta" },
  ausente: { texto: "não aparece", classe: "falta" },
  incerta: { texto: "incerta", classe: "incerta" },
};

/** Uma das partes lidas em voz alta, com o que faltou dela. */
function Parte({ rotulo, parte }: { rotulo: string; parte: ParteLida }) {
  const s = SITUACAO[parte.situacao] ?? SITUACAO.incerta;
  return (
    <div className={estilos.parte}>
      <span className={estilos.parteTitulo}>
        {rotulo}
        <span className={estilos[s.classe]}>{s.texto}</span>
      </span>
      {parte.faltou.length > 0 && (
        <ul className={estilos.perguntas}>
          {parte.faltou.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
    <div className={estilos.container}>
      <button type="button" className="botao botao--secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </button>

      <header className={estilos.cabecalho}>
        <h1>Supervisão</h1>
        <p>
          As entrevistas do escritório por quem as conduziu. Abra uma para ler a
          transcrição e conferir se o roteiro foi seguido.
        </p>
        {!carregando && (
          <p className={estilos.totais}>
            <strong>{totais.entrevistas}</strong> entrevista(s) ·{" "}
            <strong>{totais.pessoas}</strong> pessoa(s)
            {totais.sem > 0 && (
              <>
                {" "}
                ·{" "}
                <span className={estilos.pendencia}>
                  {totais.sem} sem quem conduziu
                </span>
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

      <div className={estilos.colunas}>
        <section className={estilos.lista}>
          {carregando ? (
            <p className={estilos.vazio}>Carregando…</p>
          ) : pessoas.length === 0 ? (
            <p className={estilos.vazio}>Nenhuma entrevista registrada ainda.</p>
          ) : (
            pessoas.map((p) => (
              <div key={p.entrevistador} className={estilos.pessoa}>
                <h2>
                  {p.entrevistador}
                  <span className={estilos.contagem}>
                    {p.quantidade} entrevista{p.quantidade === 1 ? "" : "s"}
                  </span>
                </h2>
                <ul>
                  {p.entrevistas.map((e) => (
                    <li key={e.id}>
                      <button
                        type="button"
                        className={`${estilos.item} ${aberta === e.id ? estilos.itemAberto : ""}`}
                        onClick={() => void abrir(e.id)}
                      >
                        <span>{e.realizada_em || e.criado_em?.slice(0, 10) || "sem data"}</span>
                        <span className={estilos.meta}>
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

        <section className={estilos.detalhe}>
          {!aberta ? (
            <p className={estilos.vazio}>
              Escolha uma entrevista à esquerda para ler a transcrição.
            </p>
          ) : (
            <>
              <div className={estilos.acoes}>
                <button
                  type="button"
                  className="botao"
                  onClick={() => void auditar(aberta)}
                  disabled={auditando || carregandoTexto}
                >
                  {auditando ? "Analisando…" : "Conferir contra o roteiro"}
                </button>
                {auditando && (
                  <span className={estilos.meta}>
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
                <div className={estilos.relatorio}>
                  <h3>Conferência do roteiro</h3>
                  <p className={estilos.resumo}>{relatorio.resumo}</p>

                  <div className={estilos.placar}>
                    <span className={estilos.ok}>{relatorio.cobertas.length} cobertas</span>
                    <span className={estilos.falta}>
                      {relatorio.nao_cobertas.length} não cobertas
                    </span>
                    {relatorio.incertas.length > 0 && (
                      <span className={estilos.incerta}>
                        {relatorio.incertas.length} incertas
                      </span>
                    )}
                    <span className={estilos.meta}>de {relatorio.total_perguntas}</span>
                  </div>

                  {/* Antes das perguntas: abertura e encerramento são o que o
                    * escritório pediu para seguir à risca, e é o que some
                    * primeiro quando a entrevista corre apertada. */}
                  <div className={estilos.bloco}>
                    <h4>Abertura e encerramento</h4>
                    <Parte rotulo="Abertura" parte={relatorio.abertura} />
                    <Parte rotulo="Encerramento" parte={relatorio.encerramento} />
                  </div>

                  {relatorio.faltando_obrigatorias.length > 0 && (
                    <div className={estilos.bloco}>
                      <h4>
                        Obrigatórias que não aparecem (
                        {relatorio.faltando_obrigatorias.length} de{" "}
                        {relatorio.total_obrigatorias})
                      </h4>
                      <ul className={estilos.perguntas}>
                        {relatorio.faltando_obrigatorias.map((p) => (
                          <li key={p.id}>
                            {p.texto} <span className={estilos.meta}>({p.bloco})</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.observacoes.length > 0 && (
                    <div className={estilos.bloco}>
                      <h4>Observações</h4>
                      <ul className={estilos.perguntas}>
                        {relatorio.observacoes.map((o, i) => (
                          <li key={i}>
                            <strong>{o.item}</strong> — {o.porque}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.pontos_fortes.length > 0 && (
                    <div className={estilos.bloco}>
                      <h4>Pontos fortes</h4>
                      <ul className={estilos.perguntas}>
                        {relatorio.pontos_fortes.map((p, i) => (
                          <li key={i}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {relatorio.transcricao_truncada && (
                    <p className={estilos.meta}>
                      A transcrição é longa e foi analisada até o limite do modelo — o
                      fim da conversa pode não ter entrado.
                    </p>
                  )}
                  <p className={estilos.aviso}>{relatorio.aviso}</p>
                </div>
              )}

              <h3>Transcrição</h3>
              {carregandoTexto ? (
                <p className={estilos.vazio}>Carregando…</p>
              ) : texto ? (
                <pre className={estilos.transcricao}>{texto}</pre>
              ) : (
                <p className={estilos.vazio}>Esta entrevista não tem texto.</p>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
