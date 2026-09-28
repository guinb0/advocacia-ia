"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Upload } from "lucide-react";

import { Aviso, Botao, Cartao, CampoSeletor, RotuloCampo, Selo, Stat } from "@/components/ui/Basicos";
import {
  ativarSkillPeticao,
  baixarSkillPeticao,
  enviarSkillPeticao,
  obterSkillPeticao,
  type EstadoSkillPeticao,
} from "@/lib/api";
import { baixarArquivo } from "@/lib/baixar";

import EditarSkillDePeticao from "./EditarSkillDePeticao";

const O_QUE_O_PACOTE_TRAZ: { arquivo: string; papel: string; obrigatorio: boolean }[] = [
  { arquivo: "SKILL.md", papel: "instruções gerais e a tabela de assuntos", obrigatorio: true },
  { arquivo: "references/formatacao.md", papel: "o layout: fonte, margens, espaçamento, títulos (bloco estilo)", obrigatorio: true },
  { arquivo: "references/estrutura_peca.md", papel: "a ordem dos blocos da petição", obrigatorio: true },
  { arquivo: "references/validacoes.md", papel: "as conferências feitas antes de entregar a peça", obrigatorio: false },
  { arquivo: "references/<assunto>.md", papel: "as regras de cada tipo de ação", obrigatorio: false },
  { arquivo: "references/observacoes.md", papel: "as observações do escritório, que prevalecem sobre o resto", obrigatorio: false },
  { arquivo: "assets/logo.png", papel: "a logo do cabeçalho", obrigatorio: false },
];

function numero(valor: number): string {
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function dataEHora(valor: string): string {
  const data = new Date(valor.replace(" ", "T"));
  return Number.isNaN(data.getTime())
    ? ""
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function mensagem(e: unknown, padrao: string): string {
  return e instanceof Error && e.message ? e.message : padrao;
}

export default function SkillDePeticao({ onMudou }: { onMudou: () => void }) {
  const [estado, setEstado] = useState<EstadoSkillPeticao | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [pronto, setPronto] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<"enviar" | "baixar" | "trocar" | null>(null);
  const [escolhida, setEscolhida] = useState("");
  const seletorDeArquivo = useRef<HTMLInputElement>(null);

  const carregar = useCallback(async () => {
    setErroCarga(null);
    try {
      setEstado(await obterSkillPeticao());
    } catch (e) {
      setErroCarga(mensagem(e, "Não foi possível ler a skill de petição."));
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  function atualizar(novo: EstadoSkillPeticao) {
    setEstado(novo);
    window.dispatchEvent(new Event("skills-atualizadas"));
    onMudou();
  }

  function aplicar(novo: EstadoSkillPeticao) {
    atualizar(novo);
    setEscolhida("");
    setPronto(`Pronto! A partir da próxima petição gerada, vale a skill "${novo.ativa.nome}".`);
  }

  async function enviar(arquivo: File | null) {
    if (!arquivo) return;
    setOcupado("enviar");
    setErro(null);
    setPronto(null);
    try {
      aplicar(await enviarSkillPeticao(arquivo));
    } catch (e) {
      setErro(mensagem(e, "Não foi possível enviar a skill."));
    } finally {
      setOcupado(null);
    }
  }

  async function trocar(skillId: string) {
    setOcupado("trocar");
    setErro(null);
    setPronto(null);
    try {
      aplicar(await ativarSkillPeticao(skillId));
    } catch (e) {
      setErro(mensagem(e, "Não foi possível trocar a skill."));
    } finally {
      setOcupado(null);
    }
  }

  async function baixar() {
    if (!estado) return;
    setOcupado("baixar");
    setErro(null);
    try {
      const { arquivo, nome } = await baixarSkillPeticao(estado.ativa.do_sistema ? "" : estado.ativa.id);
      baixarArquivo(arquivo, nome);
    } catch (e) {
      setErro(mensagem(e, "Não foi possível baixar a skill."));
    } finally {
      setOcupado(null);
    }
  }

  const ativa = estado?.ativa;
  const verificacao = ativa?.verificacao;
  const outras = (estado?.disponiveis ?? []).filter((s) => s.id !== ativa?.id);

  return (
    <Cartao
      titulo={
        <span className="flex flex-wrap items-center gap-2">
          <FileText aria-hidden className="size-5 text-acao" />
          Skill de geração de petição
        </span>
      }
      subtitulo="É esta skill que escreve e diagrama toda petição gerada pelo sistema: o texto, a ordem dos blocos, as conferências e o layout (fonte, margens, espaçamento e logo). Para mudar qualquer uma dessas coisas, troque a skill aqui."
    >
      {erroCarga && <Aviso tom="critico" titulo="Não foi possível ler a skill em uso">{erroCarga}</Aviso>}
      {!estado && !erroCarga && <p className="text-sm text-tinta-2">Carregando a skill em uso…</p>}

      {ativa && verificacao && (
        <div className="grid gap-5">
          <section className="grid gap-3" aria-label="Skill em uso">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-tinta-2">Em uso agora:</span>
              <strong className="text-base text-tinta">{ativa.nome}</strong>
              <Selo tom="ok" simbolo="✓">{ativa.do_sistema ? "padrão do sistema" : "enviada pelo escritório"}</Selo>
            </div>
            {!ativa.do_sistema && ativa.ativada_em && (
              <p className="m-0 text-xs text-tinta-3">
                Ativada {ativa.ativada_por ? `por ${ativa.ativada_por} ` : ""}em {dataEHora(ativa.ativada_em)}.
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              <Stat
                chave="Letra"
                valor={`${verificacao.layout.fonte} ${numero(verificacao.layout.tamanho_pt)} pt`}
                titulo={`Espaçamento entre linhas: ${numero(verificacao.layout.espacamento_linha)}`}
              />
              <Stat
                chave="Margens (cm)"
                valor={verificacao.layout.margens_cm.map(numero).join(" · ")}
                titulo="Superior · direita · inferior · esquerda"
              />
              <Stat chave="Blocos da petição" valor={String(verificacao.blocos.length)} />
              <Stat chave="Tipos de ação" valor={String(verificacao.assuntos)} titulo="Linhas da tabela de assuntos do SKILL.md" />
              <Stat chave="Conferências" valor={String(verificacao.validacoes)} />
              <Stat chave="Logo" valor={ativa.logo ? "Da skill" : "Modelo visual"} titulo={ativa.logo || "A skill não traz logo; vale a do modelo visual da petição."} />
            </div>
            {verificacao.blocos.length > 0 && (
              <details className="text-sm text-tinta-2">
                <summary className="cursor-pointer font-semibold text-acao">Ver a ordem dos blocos da petição</summary>
                <ol className="mt-2 mb-0 grid gap-1 pl-5">
                  {verificacao.blocos.map((bloco) => (
                    <li key={bloco}>{bloco}</li>
                  ))}
                </ol>
              </details>
            )}
            {verificacao.avisos.length > 0 && (
              <Aviso tom="atencao" titulo="Pontos de atenção da skill em uso">
                <ul className="m-0 grid gap-1 pl-4">
                  {verificacao.avisos.map((aviso) => (
                    <li key={aviso}>{aviso}</li>
                  ))}
                </ul>
              </Aviso>
            )}
          </section>

          <EditarSkillDePeticao skillId={ativa.id} onSalvou={atualizar} />

          <section className="grid gap-3 rounded-campo border border-borda bg-papel-2 p-4" aria-label="Trocar a skill">
            <h3 className="m-0 text-base font-semibold text-tinta">Como trocar a skill de petição inteira (por arquivo)</h3>
            <ol className="m-0 grid list-none gap-4 p-0">
              <li className="grid gap-2">
                <p className="m-0 text-sm text-tinta">
                  <strong>1. Baixe a skill em uso.</strong> Ela serve de modelo: já vem com todos os arquivos no lugar certo.
                </p>
                <div>
                  <Botao
                    variante="secundario"
                    onClick={() => void baixar()}
                    carregando={ocupado === "baixar"}
                    textoCarregando="Preparando o arquivo…"
                  >
                    <Download aria-hidden className="size-4" />
                    Baixar a skill em uso (.skill.zip)
                  </Botao>
                </div>
              </li>
              <li className="grid gap-2">
                <p className="m-0 text-sm text-tinta">
                  <strong>2. Abra o ZIP e edite o que quiser mudar.</strong> O que cada arquivo controla:
                </p>
                <ul className="m-0 grid gap-1 pl-5 text-sm text-tinta-2">
                  {O_QUE_O_PACOTE_TRAZ.map((item) => (
                    <li key={item.arquivo}>
                      <code className="text-tinta">{item.arquivo}</code> — {item.papel}
                      {item.obrigatorio ? <strong> (obrigatório)</strong> : " (opcional)"}
                    </li>
                  ))}
                </ul>
              </li>
              <li className="grid gap-2">
                <p className="m-0 text-sm text-tinta">
                  <strong>3. Compacte de novo e envie.</strong> O sistema confere o pacote antes de usar: se faltar
                  alguma coisa, nada muda e aparece exatamente o que falta.
                </p>
                <div>
                  <Botao
                    variante="primario"
                    onClick={() => seletorDeArquivo.current?.click()}
                    carregando={ocupado === "enviar"}
                    textoCarregando="Conferindo a skill…"
                  >
                    <Upload aria-hidden className="size-4" />
                    Enviar skill de petição (.skill.zip)
                  </Botao>
                  <input
                    ref={seletorDeArquivo}
                    type="file"
                    accept=".zip,application/zip"
                    className="hidden"
                    onChange={(e) => {
                      void enviar(e.target.files?.[0] ?? null);
                      e.target.value = "";
                    }}
                  />
                </div>
              </li>
            </ol>
          </section>

          {erro && <Aviso tom="critico" titulo="A skill não foi trocada">{erro}</Aviso>}
          {pronto && <Aviso tom="ok">{pronto}</Aviso>}

          {(outras.length > 0 || !ativa.do_sistema) && (
            <section className="grid gap-3" aria-label="Outras skills de petição">
              {outras.length > 0 && (
                <div className="flex flex-wrap items-end gap-2">
                  <div className="min-w-[240px] flex-1">
                    <RotuloCampo htmlFor="skill-peticao-outra">Usar outra skill de petição já enviada</RotuloCampo>
                    <CampoSeletor
                      id="skill-peticao-outra"
                      value={escolhida}
                      onChange={(e) => setEscolhida(e.target.value)}
                    >
                      <option value="">Escolha uma skill…</option>
                      {outras.map((skill) => (
                        <option key={skill.id} value={skill.id}>
                          {skill.nome}
                          {skill.atualizado_em ? ` (enviada em ${dataEHora(skill.atualizado_em)})` : ""}
                        </option>
                      ))}
                    </CampoSeletor>
                  </div>
                  <Botao
                    variante="secundario"
                    disabled={!escolhida}
                    onClick={() => void trocar(escolhida)}
                    carregando={ocupado === "trocar" && Boolean(escolhida)}
                  >
                    Usar esta
                  </Botao>
                </div>
              )}
              {!ativa.do_sistema && (
                <div>
                  <Botao
                    variante="discreto"
                    pequeno
                    onClick={() => void trocar("")}
                    carregando={ocupado === "trocar" && !escolhida}
                  >
                    Voltar para a skill padrão do sistema
                  </Botao>
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </Cartao>
  );
}
