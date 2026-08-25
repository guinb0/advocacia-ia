"use client";

/* A tela do secretário: quem entrevistou, quanto, e como conduziu.
 *
 * Três níveis, e a ordem é a das perguntas que ele faz de verdade: quem fez
 * quantas → quais foram → como foi esta. Cada nível só carrega quando é aberto;
 * a conferência contra o roteiro, em especial, custa uma ida ao modelo e por isso
 * nunca dispara sozinha ao abrir a tela.
 *
 * O TERCEIRO NÍVEL É O CHECKLIST, NÃO A TRANSCRIÇÃO
 *
 * Era a transcrição que abria primeiro, e ela é quarenta minutos de texto: na
 * prática ninguém lia, e a conferência não acontecia. Agora abre o checklist do
 * roteiro (`ChecklistRoteiro`), que responde em uma tela o que a leitura responderia
 * em meia hora — assinaturas, avaliação do Google, perguntas, abertura e
 * encerramento. A transcrição continua a um clique, na outra aba, porque é ela que
 * resolve a dúvida quando o checklist aponta algo que o secretário quer conferir
 * com os próprios olhos.
 */

import { useCallback, useEffect, useState } from "react";

import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import ChecklistRoteiro from "@/components/admin/ChecklistRoteiro";
import { Aviso, BarraAbas, Botao, BotaoAba, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  auditarEntrevista,
  corrigirAvaliacaoGoogle,
  listarSupervisao,
  obterChecklist,
  obterTranscricao,
  type Auditoria,
  type ChecklistRegistro,
  type PessoaSupervisao,
} from "@/lib/api";

interface Props {
  onVoltar: () => void;
}

const ITEM_BASE =
  "flex flex-col gap-[5px] w-full px-[11px] py-[9px] border border-transparent rounded-campo " +
  "[font:inherit] text-left cursor-pointer";
const ITEM_RESTING = "bg-transparent hover:bg-papel-3";
const ITEM_ABERTO = "bg-acao-clara border-acao-borda";

export default function Supervisao({ onVoltar }: Props) {
  const [pessoas, setPessoas] = useState<PessoaSupervisao[]>([]);
  const [totais, setTotais] = useState({ entrevistas: 0, pessoas: 0, sem: 0 });
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [aberta, setAberta] = useState<string | null>(null);
  const [aba, setAba] = useState<"checklist" | "transcricao">("checklist");

  const [texto, setTexto] = useState<string>("");
  const [carregandoTexto, setCarregandoTexto] = useState(false);

  const [registro, setRegistro] = useState<ChecklistRegistro | null>(null);
  const [erroRegistro, setErroRegistro] = useState<string | null>(null);
  const [corrigindo, setCorrigindo] = useState(false);

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
    // Trocar de entrevista limpa a conferência: um relatório de OUTRA entrevista
    // ao lado deste checklist é pior que relatório nenhum.
    setAberta(id);
    setAba("checklist");
    setRelatorio(null);
    setErroAuditoria(null);
    setTexto("");
    setRegistro(null);
    setErroRegistro(null);

    // O checklist do registro é uma consulta ao banco e abre junto. A transcrição
    // vem no mesmo passo porque é o mesmo custo — o que NÃO vem é a leitura pelo
    // modelo, que espera o secretário pedir.
    setCarregandoTexto(true);
    try {
      setRegistro(await obterChecklist(id));
    } catch (e) {
      setErroRegistro(e instanceof ApiError ? e.message : "Erro ao montar o checklist.");
    }
    try {
      setTexto((await obterTranscricao(id)).texto);
    } catch (e) {
      setTexto("");
      setErroRegistro(e instanceof ApiError ? e.message : "Erro ao ler a transcrição.");
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
      setErroAuditoria(e instanceof ApiError ? e.message : "Não foi possível conferir.");
    } finally {
      setAuditando(false);
    }
  }

  async function corrigirAvaliacao(id: string, concluida: boolean) {
    setCorrigindo(true);
    try {
      setRegistro(await corrigirAvaliacaoGoogle(id, concluida));
      // A lista à esquerda mostra o mesmo sinal; deixá-la desatualizada faria o
      // secretário achar que a correção não pegou.
      await carregar();
    } catch (e) {
      setErroRegistro(
        e instanceof ApiError ? e.message : "Não foi possível gravar a marcação.",
      );
    } finally {
      setCorrigindo(false);
    }
  }

  return (
    <div className="max-w-[1240px] mx-auto px-5 pt-6 pb-16">
      <Botao variante="secundario" onClick={onVoltar}>
        ← Voltar para a carteira
      </Botao>

      <header className="my-5">
        <h1 className="mb-[6px] mt-0 text-tinta font-titulo text-xl font-semibold">Supervisão</h1>
        <p className="m-0 text-tinta-3 max-w-[66ch] leading-[1.5]">
          As entrevistas do escritório por quem as conduziu. Abra uma para conferir o
          checklist do roteiro — assinaturas, avaliação no Google, perguntas — e para
          ler a transcrição.
        </p>
        {!carregando && (
          <p className="mt-[10px] mb-0 text-tinta-3 max-w-[66ch] leading-[1.5]">
            <strong>{totais.entrevistas}</strong> entrevista(s) ·{" "}
            <strong>{totais.pessoas}</strong> pessoa(s)
            {totais.sem > 0 && (
              <> · <span className="text-atencao">{totais.sem} sem quem conduziu</span></>
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

      <div className="grid grid-cols-[340px_minmax(0,1fr)] max-[900px]:grid-cols-1 gap-6 items-start mt-5">
        {/* ------------------------------------------- funcionário e entrevistas */}
        <section className="border border-borda-forte rounded-cartao bg-papel shadow-cartao p-4">
          {carregando ? (
            <p className="m-0 text-tinta-3">Carregando…</p>
          ) : pessoas.length === 0 ? (
            <Vazio>Nenhuma entrevista registrada ainda.</Vazio>
          ) : (
            pessoas.map((p) => {
              const semAvaliacao = p.entrevistas.filter((e) => !e.avaliacao_google).length;

              return (
                <div
                  key={p.entrevistador}
                  className="[&+&]:mt-[18px] [&+&]:pt-[18px] [&+&]:border-t [&+&]:border-borda"
                >
                  <h2 className="flex justify-between items-baseline gap-[10px] mb-1 mt-0 text-tinta font-titulo text-md font-semibold">
                    {p.entrevistador}
                    <span className="font-ui font-normal text-xs text-tinta-3 whitespace-nowrap">
                      {p.quantidade} entrevista{p.quantidade === 1 ? "" : "s"}
                    </span>
                  </h2>

                  {/* O que o secretário cobraria desta pessoa hoje, sem abrir nada.
                    * A avaliação do Google é o único item do roteiro que a lista
                    * consegue conferir sem ir ao modelo — e é o mais frágil deles. */}
                  <p className="mt-0 mb-2 text-xs leading-[1.5]">
                    {semAvaliacao === 0 ? (
                      <span className="text-ok">✓ avaliação do Google em todas</span>
                    ) : (
                      <span className="text-atencao">
                        ! {semAvaliacao} sem avaliação do Google registrada
                      </span>
                    )}
                  </p>

                  <ul className="list-none m-0 p-0 flex flex-col gap-[2px]">
                    {p.entrevistas.map((e) => (
                      <li key={e.id}>
                        <button
                          type="button"
                          className={`${ITEM_BASE} ${aberta === e.id ? ITEM_ABERTO : ITEM_RESTING}`}
                          onClick={() => void abrir(e.id)}
                        >
                          <span className="flex justify-between items-baseline gap-[10px] w-full">
                            <span
                              className={`text-tinta text-sm truncate ${aberta === e.id ? "font-semibold" : ""}`}
                            >
                              {e.cliente || "cliente não informado"}
                            </span>
                            <span className="text-tinta-3 text-xs whitespace-nowrap">
                              {e.realizada_em || e.criado_em?.slice(0, 10) || "sem data"}
                            </span>
                          </span>
                          <span className="flex items-center gap-[6px] flex-wrap">
                            <Selo
                              tom={e.avaliacao_google ? "ok" : "atencao"}
                              simbolo={e.avaliacao_google ? "✓" : "!"}
                            >
                              Google
                            </Selo>
                            {!e.enviada && (
                              <Selo tom="atencao" simbolo="!">
                                sem dossiê
                              </Selo>
                            )}
                            <span className="text-tinta-3 text-xs whitespace-nowrap">
                              {e.caracteres.toLocaleString("pt-BR")} car.
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </section>

        {/* --------------------------------------------------- checklist e texto */}
        <section className="min-w-0">
          {!aberta ? (
            <Vazio>
              Escolha uma entrevista à esquerda para abrir o checklist do roteiro.
            </Vazio>
          ) : (
            <div className="flex flex-col gap-4">
              <BarraAbas className="self-start">
                <BotaoAba ativa={aba === "checklist"} onClick={() => setAba("checklist")}>
                  Checklist do roteiro
                </BotaoAba>
                <BotaoAba ativa={aba === "transcricao"} onClick={() => setAba("transcricao")}>
                  Transcrição
                </BotaoAba>
              </BarraAbas>

              {erroRegistro && (
                <Aviso tom="critico" titulo="Falhou ao carregar">
                  {erroRegistro}
                </Aviso>
              )}

              {aba === "checklist" ? (
                <ChecklistRoteiro
                  registro={registro}
                  auditoria={relatorio}
                  auditando={auditando}
                  erroAuditoria={erroAuditoria}
                  onAuditar={() => void auditar(aberta)}
                  onCorrigirAvaliacao={(c) => void corrigirAvaliacao(aberta, c)}
                  corrigindoAvaliacao={corrigindo}
                />
              ) : carregandoTexto ? (
                <p className="m-0 text-tinta-3">Carregando…</p>
              ) : texto ? (
                <>
                  {/* O áudio, quando a entrevista foi conduzida pelo roteiro.
                    * A transcrição vem de reconhecimento de voz e erra — quando
                    * o checklist aponta algo que o secretário quer conferir de
                    * verdade, é aqui que ele ouve o trecho em vez de decidir
                    * pelo texto. A anexada como arquivo não tem áudio. */}
                  {registro?.origem === "ao_vivo" && registro.gravacao_id && (
                    <AudioDaEntrevista entrevistaId={registro.gravacao_id} />
                  )}
                  <pre className="m-0 px-[14px] py-3 max-h-[620px] overflow-y-auto border border-borda-forte rounded-cartao bg-papel text-tinta-2 [font-family:inherit] text-sm leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]">
                    {texto}
                  </pre>
                </>
              ) : (
                <Vazio>Esta entrevista não tem texto.</Vazio>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
