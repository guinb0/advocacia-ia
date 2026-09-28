"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { History, NotebookPen, RefreshCw, RotateCcw, Save, Undo2 } from "lucide-react";

import { AjudaCampo, Aviso, Botao, Campo, CampoSeletor, RotuloCampo } from "@/components/ui/Basicos";
import {
  ApiError,
  obterArquivosSkillPeticao,
  obterHistoricoSkillPeticao,
  restaurarVersaoSkillPeticao,
  salvarArquivoSkillPeticao,
  type ArquivosSkillPeticao,
  type EstadoSkillPeticao,
  type HistoricoSkillPeticao,
} from "@/lib/api";

const OBSERVACOES = "observacoes.md";

const PAPEL_DO_ARQUIVO: Record<string, string> = {
  "SKILL.md": "instruções gerais e tabela de assuntos",
  "formatacao.md": "layout: fonte, margens, espaçamento, títulos",
  "estrutura_peca.md": "ordem dos blocos da petição",
  "validacoes.md": "conferências antes de entregar",
};

function rotulo(caminho: string): string {
  const nome = caminho === "SKILL.md" ? caminho : `references/${caminho}`;
  const papel = PAPEL_DO_ARQUIVO[caminho];
  return papel ? `${nome} — ${papel}` : nome;
}

function mensagem(e: unknown, padrao: string): string {
  return e instanceof Error && e.message ? e.message : padrao;
}

function dataEHora(valor: string): string {
  const data = new Date(valor.replace(" ", "T"));
  return Number.isNaN(data.getTime())
    ? valor
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function textoDe(dados: ArquivosSkillPeticao | null, caminho: string): string {
  return dados?.arquivos.find((a) => a.caminho === caminho)?.texto ?? "";
}

/** O que está no campo e o arquivo como estava quando a pessoa começou a editar. */
type Rascunho = { caminho: string; texto: string; lido: string };
type Retorno = { tom: "ok" | "critico"; texto: string; conflito?: boolean } | null;
type CampoEditavel = "observacoes" | "arquivo";

/** Observações do escritório, edição dos arquivos e histórico da skill de petição em uso. */
export default function EditarSkillDePeticao({
  skillId,
  onSalvou,
}: {
  /** Skill em uso; quando muda, os arquivos são lidos de novo. */
  skillId: string;
  onSalvou: (novo: EstadoSkillPeticao) => void;
}) {
  const [dados, setDados] = useState<ArquivosSkillPeticao | null>(null);
  const [historico, setHistorico] = useState<HistoricoSkillPeticao | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [obs, setObs] = useState<Rascunho>({ caminho: OBSERVACOES, texto: "", lido: "" });
  const [arq, setArq] = useState<Rascunho>({ caminho: "SKILL.md", texto: "", lido: "" });
  const [ocupado, setOcupado] = useState<CampoEditavel | `restaurar-${number}` | null>(null);
  const [retorno, setRetorno] = useState<Record<CampoEditavel | "historico", Retorno>>({
    observacoes: null,
    arquivo: null,
    historico: null,
  });
  const caminhoAberto = useRef("SKILL.md");

  /**
   * Relê a skill. Um campo com alteração ainda não salva continua como está (e com o
   * texto de quando foi aberto), a não ser que esteja em `descartar`: salvar uma
   * coisa nunca apaga o que a pessoa está digitando na outra.
   */
  const carregar = useCallback(async (descartar: CampoEditavel[] = []) => {
    setErroCarga(null);
    try {
      const [lidos, versoes] = await Promise.all([obterArquivosSkillPeticao(), obterHistoricoSkillPeticao()]);
      setDados(lidos);
      setHistorico(versoes);
      const reler = (atual: Rascunho, caminho: string, campo: CampoEditavel): Rascunho =>
        atual.caminho === caminho && atual.texto !== atual.lido && !descartar.includes(campo)
          ? atual
          : { caminho, texto: textoDe(lidos, caminho), lido: textoDe(lidos, caminho) };
      setObs((atual) => reler(atual, OBSERVACOES, "observacoes"));
      const alvo = lidos.arquivos.some((a) => a.caminho === caminhoAberto.current) ? caminhoAberto.current : "SKILL.md";
      caminhoAberto.current = alvo;
      setArq((atual) => reler(atual, alvo, "arquivo"));
    } catch (e) {
      setErroCarga(mensagem(e, "Não foi possível ler os arquivos da skill."));
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar, skillId]);

  function avisar(campo: CampoEditavel | "historico", valor: Retorno) {
    setRetorno((atual) => ({ ...atual, [campo]: valor }));
  }

  async function salvar(campo: CampoEditavel) {
    if (!dados) return;
    const rascunho = campo === "observacoes" ? obs : arq;
    setOcupado(campo);
    avisar(campo, null);
    try {
      const novo = await salvarArquivoSkillPeticao(dados.skill_id, rascunho.caminho, rascunho.texto, rascunho.lido);
      const copia = dados.do_sistema
        ? ` Como a skill padrão do sistema não pode ser alterada, foi criada a cópia "${novo.ativa.nome}", que já está em uso.`
        : "";
      avisar(campo, { tom: "ok", texto: `Gravado. Vale a partir da próxima petição gerada.${copia}` });
      onSalvou(novo);
      await carregar([campo]);
    } catch (e) {
      avisar(campo, {
        tom: "critico",
        texto: mensagem(e, "Não foi possível gravar a alteração."),
        conflito: e instanceof ApiError && e.status === 409,
      });
    } finally {
      setOcupado(null);
    }
  }

  async function restaurar(versaoId: number, quando: string) {
    if (!historico) return;
    if (!window.confirm(`Voltar a skill para a versão de ${quando}? A versão atual continua no histórico.`)) return;
    setOcupado(`restaurar-${versaoId}`);
    avisar("historico", null);
    try {
      const novo = await restaurarVersaoSkillPeticao(historico.skill_id, versaoId);
      avisar("historico", { tom: "ok", texto: `A skill voltou para a versão de ${quando}. Vale a partir da próxima petição.` });
      onSalvou(novo);
      await carregar(["observacoes", "arquivo"]);
    } catch (e) {
      avisar("historico", { tom: "critico", texto: mensagem(e, "Não foi possível restaurar a versão.") });
    } finally {
      setOcupado(null);
    }
  }

  function mostrar(campo: CampoEditavel | "historico", titulo: string) {
    const valor = retorno[campo];
    if (!valor) return null;
    return (
      <Aviso tom={valor.tom} titulo={valor.tom === "critico" ? titulo : undefined}>
        {valor.texto}
        {valor.conflito && campo !== "historico" && (
          <span className="mt-2 block">
            <Botao variante="secundario" pequeno onClick={() => void carregar([campo])}>
              <RefreshCw aria-hidden className="size-4" />
              Descartar o meu texto e abrir a versão atual
            </Botao>
          </span>
        )}
      </Aviso>
    );
  }

  if (erroCarga) return <Aviso tom="critico" titulo="Não foi possível abrir a skill para edição">{erroCarga}</Aviso>;
  if (!dados) return null;

  const editaveis = dados.arquivos.filter((a) => a.caminho !== OBSERVACOES);
  const obsMudou = obs.texto !== obs.lido;
  const arquivoMudou = arq.texto !== arq.lido;
  const versoes = historico?.versoes ?? [];

  return (
    <div className="grid gap-5">
      <section className="grid gap-2 rounded-campo border border-borda bg-papel-2 p-4" aria-label="Observações do escritório">
        <h3 className="m-0 flex items-center gap-2 text-base font-semibold text-tinta">
          <NotebookPen aria-hidden className="size-4 text-acao" />
          Observações do escritório
        </h3>
        <RotuloCampo htmlFor="skill-peticao-observacoes" className="sr-only">
          Observações do escritório para a skill de petição
        </RotuloCampo>
        <Campo
          area
          id="skill-peticao-observacoes"
          rows={6}
          value={obs.texto}
          onChange={(e) => setObs({ ...obs, texto: e.target.value })}
          placeholder={"Ex.: Sempre pedir justiça gratuita.\nNão usar a expressão \"data venia\".\nCitar a OAB do Dr. Fulano na assinatura."}
        />
        <AjudaCampo className="mt-0">
          Escreva do jeito que falaria com um estagiário. As observações entram em toda petição gerada com esta skill e,
          se contrariarem alguma regra dela, <strong>prevalecem</strong>.
        </AjudaCampo>
        <div className="flex flex-wrap gap-2">
          <Botao
            variante="primario"
            disabled={!obsMudou}
            onClick={() => void salvar("observacoes")}
            carregando={ocupado === "observacoes"}
            textoCarregando="Gravando…"
          >
            <Save aria-hidden className="size-4" />
            Salvar observações
          </Botao>
          {obsMudou && (
            <Botao variante="discreto" onClick={() => setObs({ ...obs, texto: obs.lido })}>
              <Undo2 aria-hidden className="size-4" />
              Desfazer
            </Botao>
          )}
        </div>
        {mostrar("observacoes", "As observações não foram gravadas")}
      </section>

      <details className="rounded-campo border border-borda p-4">
        <summary className="cursor-pointer text-base font-semibold text-acao">
          Editar a skill aqui mesmo (sem baixar o ZIP)
        </summary>
        <div className="mt-3 grid gap-3">
          <p className="m-0 text-sm text-tinta-2">
            Escolha o arquivo, altere o texto e salve. Antes de gravar, o sistema confere a skill inteira: se a
            alteração quebrar o layout ou a ordem dos blocos, nada é gravado e aparece o motivo. Se outra pessoa
            tiver mudado o mesmo arquivo enquanto você editava, nada é gravado e o seu texto continua aqui.
            {dados.do_sistema && (
              <>
                {" "}
                <strong>A skill em uso é a padrão do sistema:</strong> ao salvar, é criada uma cópia editável do
                escritório, que passa a ser usada no lugar dela. Essa cópia não recebe as atualizações futuras da
                padrão; para voltar a ela, use &quot;Voltar para a skill padrão do sistema&quot;.
              </>
            )}
          </p>
          <div>
            <RotuloCampo htmlFor="skill-peticao-arquivo">Arquivo</RotuloCampo>
            <CampoSeletor
              id="skill-peticao-arquivo"
              value={arq.caminho}
              onChange={(e) => {
                if (arquivoMudou && !window.confirm("Você tem uma alteração não salva neste arquivo. Descartar?")) return;
                const caminho = e.target.value;
                caminhoAberto.current = caminho;
                setArq({ caminho, texto: textoDe(dados, caminho), lido: textoDe(dados, caminho) });
                avisar("arquivo", null);
              }}
            >
              {editaveis.map((a) => (
                <option key={a.caminho} value={a.caminho}>
                  {rotulo(a.caminho)}
                </option>
              ))}
            </CampoSeletor>
          </div>
          <div>
            <RotuloCampo htmlFor="skill-peticao-texto">Conteúdo</RotuloCampo>
            <Campo
              area
              id="skill-peticao-texto"
              rows={20}
              spellCheck={false}
              className="font-mono text-sm"
              value={arq.texto}
              onChange={(e) => setArq({ ...arq, texto: e.target.value })}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Botao
              variante="primario"
              disabled={!arquivoMudou}
              onClick={() => void salvar("arquivo")}
              carregando={ocupado === "arquivo"}
              textoCarregando="Conferindo e gravando…"
            >
              <Save aria-hidden className="size-4" />
              Salvar alteração
            </Botao>
            {arquivoMudou && (
              <Botao variante="discreto" onClick={() => setArq({ ...arq, texto: arq.lido })}>
                <Undo2 aria-hidden className="size-4" />
                Desfazer
              </Botao>
            )}
          </div>
          {mostrar("arquivo", "A alteração não foi gravada")}
        </div>
      </details>

      <details className="rounded-campo border border-borda p-4">
        <summary className="cursor-pointer text-base font-semibold text-acao">
          <History aria-hidden className="mr-1 inline size-4 align-[-2px]" />
          Histórico de alterações (desfazer)
        </summary>
        <div className="mt-3 grid gap-3">
          {historico?.do_sistema ? (
            <p className="m-0 text-sm text-tinta-2">
              A skill em uso é a padrão do sistema, que nunca é alterada. Quando o escritório editar ou enviar uma
              skill, cada gravação aparece aqui e pode ser desfeita.
            </p>
          ) : versoes.length === 0 ? (
            <p className="m-0 text-sm text-tinta-2">Nenhuma gravação registrada ainda.</p>
          ) : (
            <>
              <p className="m-0 text-sm text-tinta-2">
                Cada gravação da skill fica guardada. Se uma alteração piorou as petições, volte para uma versão
                anterior: a atual não se perde, ela continua na lista.
              </p>
              <ol className="m-0 grid list-none gap-2 p-0">
                {versoes.map((versao, indice) => {
                  const quando = dataEHora(versao.gravado_em);
                  return (
                    <li
                      key={versao.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-campo border border-borda px-3 py-2"
                    >
                      <span className="text-sm text-tinta">
                        <strong>{quando}</strong>
                        {" — "}
                        {versao.motivo || "Alteração"}
                        {versao.gravado_por ? ` (${versao.gravado_por})` : ""}
                      </span>
                      {indice === 0 ? (
                        <span className="text-xs font-semibold text-ok">em uso</span>
                      ) : (
                        <Botao
                          variante="discreto"
                          pequeno
                          onClick={() => void restaurar(versao.id, quando)}
                          carregando={ocupado === `restaurar-${versao.id}`}
                          disabled={ocupado !== null}
                        >
                          <RotateCcw aria-hidden className="size-4" />
                          Voltar para esta
                        </Botao>
                      )}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
          {mostrar("historico", "A versão não foi restaurada")}
        </div>
      </details>
    </div>
  );
}
