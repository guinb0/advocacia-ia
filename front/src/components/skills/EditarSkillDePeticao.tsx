"use client";

/**
 * As três formas de mexer na skill de petição em uso, cada uma dona do próprio rascunho:
 * instruções para a IA (as observações do escritório), desfazer uma mudança (histórico)
 * e, para quem entende do formato, editar os arquivos da skill.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw, Save, Undo2 } from "lucide-react";

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
  "estrutura_peca.md": "ordem das partes da petição",
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

export function dataEHora(valor: string): string {
  const data = new Date(valor.replace(" ", "T"));
  return Number.isNaN(data.getTime())
    ? valor
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function textoDe(dados: ArquivosSkillPeticao | null, caminho: string): string {
  return dados?.arquivos.find((a) => a.caminho === caminho)?.texto ?? "";
}

function avisoDeCopia(dados: ArquivosSkillPeticao, novo: EstadoSkillPeticao): string {
  return dados.do_sistema
    ? ` A skill padrão do sistema não pode ser alterada, então foi guardada uma cópia com a sua mudança, chamada "${novo.ativa.nome}". É ela que vale agora.`
    : "";
}

/** O que está no campo e o arquivo como estava quando a pessoa começou a editar. */
type Rascunho = { caminho: string; texto: string; lido: string };
type Retorno = { tom: "ok" | "critico"; texto: string; conflito?: boolean } | null;

type Props = {
  /** Skill em uso; quando muda, o texto é lido de novo. */
  skillId: string;
  onSalvou: (novo: EstadoSkillPeticao) => void;
};

/** Um arquivo da skill aberto para edição, com gravação protegida contra edição simultânea. */
function useArquivoDaSkill(skillId: string, caminhoInicial: string) {
  const [dados, setDados] = useState<ArquivosSkillPeticao | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [rascunho, setRascunho] = useState<Rascunho>({ caminho: caminhoInicial, texto: "", lido: "" });
  const [gravando, setGravando] = useState(false);
  const [retorno, setRetorno] = useState<Retorno>(null);

  const carregar = useCallback(async (caminho: string) => {
    setErroCarga(null);
    try {
      const lidos = await obterArquivosSkillPeticao();
      setDados(lidos);
      const alvo = lidos.arquivos.some((a) => a.caminho === caminho) ? caminho : caminhoInicial;
      setRascunho({ caminho: alvo, texto: textoDe(lidos, alvo), lido: textoDe(lidos, alvo) });
    } catch (e) {
      setErroCarga(mensagem(e, "Não foi possível abrir a skill."));
    }
  }, [caminhoInicial]);

  useEffect(() => {
    void carregar(caminhoInicial);
  }, [carregar, caminhoInicial, skillId]);

  async function gravar(onSalvou: (novo: EstadoSkillPeticao) => void, textoDeSucesso: string) {
    if (!dados) return;
    setGravando(true);
    setRetorno(null);
    try {
      const novo = await salvarArquivoSkillPeticao(dados.skill_id, rascunho.caminho, rascunho.texto, rascunho.lido);
      setRetorno({ tom: "ok", texto: textoDeSucesso + avisoDeCopia(dados, novo) });
      await carregar(rascunho.caminho);
      onSalvou(novo);
    } catch (e) {
      setRetorno({
        tom: "critico",
        texto: mensagem(e, "Não foi possível gravar."),
        conflito: e instanceof ApiError && e.status === 409,
      });
    } finally {
      setGravando(false);
    }
  }

  return { dados, erroCarga, rascunho, setRascunho, gravando, retorno, setRetorno, carregar, gravar };
}

function RetornoDaGravacao({
  valor,
  tituloDoErro,
  onRecarregar,
}: {
  valor: Retorno;
  tituloDoErro: string;
  onRecarregar: () => void;
}) {
  if (!valor) return null;
  return (
    <Aviso tom={valor.tom} titulo={valor.tom === "critico" ? tituloDoErro : undefined}>
      {valor.texto}
      {valor.conflito && (
        <span className="mt-2 block">
          <Botao variante="secundario" pequeno onClick={onRecarregar}>
            <RefreshCw aria-hidden className="size-4" />
            Descartar o meu texto e abrir o que está valendo
          </Botao>
        </span>
      )}
    </Aviso>
  );
}

/** As observações do escritório: o jeito simples de mudar como a IA escreve. */
export function InstrucoesParaIA({ skillId, onSalvou }: Props) {
  const arquivo = useArquivoDaSkill(skillId, OBSERVACOES);
  const { rascunho, setRascunho } = arquivo;
  const mudou = rascunho.texto !== rascunho.lido;

  if (arquivo.erroCarga) return <Aviso tom="critico" titulo="Não foi possível abrir as instruções">{arquivo.erroCarga}</Aviso>;
  if (!arquivo.dados) return <p className="m-0 text-sm text-tinta-2">Abrindo as instruções…</p>;

  return (
    <div className="grid gap-2">
      <RotuloCampo htmlFor="skill-peticao-instrucoes" className="mb-0 text-base">
        O que a IA deve sempre fazer (ou nunca fazer) nas petições?
      </RotuloCampo>
      <AjudaCampo className="mt-0">
        Escreva como se estivesse falando com um estagiário, uma instrução por linha. Vale para todas as petições
        novas e, se contrariar alguma regra da skill, a sua instrução é que vale.
      </AjudaCampo>
      <Campo
        area
        id="skill-peticao-instrucoes"
        rows={7}
        value={rascunho.texto}
        onChange={(e) => setRascunho({ ...rascunho, texto: e.target.value })}
        placeholder={"Exemplos:\nSempre pedir justiça gratuita.\nNão usar a expressão \"data venia\".\nAssinar com a OAB do Dr. Fulano."}
      />
      <div className="flex flex-wrap gap-2">
        <Botao
          variante="primario"
          disabled={!mudou}
          onClick={() => void arquivo.gravar(onSalvou, "Pronto! As próximas petições já seguem essas instruções.")}
          carregando={arquivo.gravando}
          textoCarregando="Gravando…"
        >
          <Save aria-hidden className="size-4" />
          Salvar instruções
        </Botao>
        {mudou && (
          <Botao variante="discreto" onClick={() => setRascunho({ ...rascunho, texto: rascunho.lido })}>
            <Undo2 aria-hidden className="size-4" />
            Desfazer o que digitei
          </Botao>
        )}
      </div>
      <RetornoDaGravacao
        valor={arquivo.retorno}
        tituloDoErro="As instruções não foram salvas"
        onRecarregar={() => {
          arquivo.setRetorno(null);
          void arquivo.carregar(OBSERVACOES);
        }}
      />
    </div>
  );
}

/** Edição direta dos arquivos da skill — para quem conhece o formato. */
export function EditarArquivosDaSkill({ skillId, onSalvou }: Props) {
  const arquivo = useArquivoDaSkill(skillId, "SKILL.md");
  const { dados, rascunho, setRascunho } = arquivo;
  const mudou = rascunho.texto !== rascunho.lido;

  if (arquivo.erroCarga) return <Aviso tom="critico" titulo="Não foi possível abrir a skill">{arquivo.erroCarga}</Aviso>;
  if (!dados) return <p className="m-0 text-sm text-tinta-2">Abrindo os arquivos…</p>;

  return (
    <div className="grid gap-3">
      <p className="m-0 text-sm text-tinta-2">
        Antes de gravar, o sistema confere a skill inteira. Se a mudança quebrar o layout ou a ordem das partes da
        petição, nada é gravado e aparece o motivo.
      </p>
      <div>
        <RotuloCampo htmlFor="skill-peticao-arquivo">Arquivo</RotuloCampo>
        <CampoSeletor
          id="skill-peticao-arquivo"
          value={rascunho.caminho}
          onChange={(e) => {
            if (mudou && !window.confirm("Você tem uma alteração não salva neste arquivo. Descartar?")) return;
            const caminho = e.target.value;
            setRascunho({ caminho, texto: textoDe(dados, caminho), lido: textoDe(dados, caminho) });
            arquivo.setRetorno(null);
          }}
        >
          {dados.arquivos
            .filter((a) => a.caminho !== OBSERVACOES)
            .map((a) => (
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
          value={rascunho.texto}
          onChange={(e) => setRascunho({ ...rascunho, texto: e.target.value })}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Botao
          variante="primario"
          disabled={!mudou}
          onClick={() => void arquivo.gravar(onSalvou, "Gravado. Vale a partir da próxima petição gerada.")}
          carregando={arquivo.gravando}
          textoCarregando="Conferindo e gravando…"
        >
          <Save aria-hidden className="size-4" />
          Salvar alteração
        </Botao>
        {mudou && (
          <Botao variante="discreto" onClick={() => setRascunho({ ...rascunho, texto: rascunho.lido })}>
            <Undo2 aria-hidden className="size-4" />
            Desfazer
          </Botao>
        )}
      </div>
      <RetornoDaGravacao
        valor={arquivo.retorno}
        tituloDoErro="A alteração não foi gravada"
        onRecarregar={() => {
          arquivo.setRetorno(null);
          void arquivo.carregar(rascunho.caminho);
        }}
      />
    </div>
  );
}

/** Cada gravação da skill, com o botão de voltar para ela. */
export function HistoricoDaSkill({ skillId, onSalvou }: Props) {
  const [historico, setHistorico] = useState<HistoricoSkillPeticao | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [restaurando, setRestaurando] = useState<number | null>(null);
  const [retorno, setRetorno] = useState<Retorno>(null);

  const carregar = useCallback(async () => {
    setErroCarga(null);
    try {
      setHistorico(await obterHistoricoSkillPeticao());
    } catch (e) {
      setErroCarga(mensagem(e, "Não foi possível abrir o histórico."));
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar, skillId]);

  async function restaurar(versaoId: number, quando: string) {
    if (!historico) return;
    if (!window.confirm(`Voltar a skill para como estava em ${quando}? O jeito atual continua guardado na lista.`)) return;
    setRestaurando(versaoId);
    setRetorno(null);
    try {
      const novo = await restaurarVersaoSkillPeticao(historico.skill_id, versaoId);
      setRetorno({ tom: "ok", texto: `Pronto! A skill voltou a ser como era em ${quando}.` });
      await carregar();
      onSalvou(novo);
    } catch (e) {
      setRetorno({ tom: "critico", texto: mensagem(e, "Não foi possível voltar para essa versão.") });
    } finally {
      setRestaurando(null);
    }
  }

  if (erroCarga) return <Aviso tom="critico" titulo="Não foi possível abrir o histórico">{erroCarga}</Aviso>;
  if (!historico) return <p className="m-0 text-sm text-tinta-2">Abrindo o histórico…</p>;

  const versoes = historico.versoes;
  if (historico.do_sistema || versoes.length === 0) {
    return (
      <p className="m-0 text-sm text-tinta-2">
        Ainda não há nenhuma mudança para desfazer. Toda vez que alguém mudar a skill, a mudança aparece aqui e dá para
        voltar atrás com um clique.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      <p className="m-0 text-sm text-tinta-2">
        Se uma mudança piorou as petições, clique em <strong>Voltar para esta</strong> na versão que estava boa. Nada se
        perde: o jeito atual continua na lista.
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
                <span className="text-xs font-semibold text-ok">✓ é a que vale agora</span>
              ) : (
                <Botao
                  variante="secundario"
                  pequeno
                  onClick={() => void restaurar(versao.id, quando)}
                  carregando={restaurando === versao.id}
                  disabled={restaurando !== null}
                >
                  <RotateCcw aria-hidden className="size-4" />
                  Voltar para esta
                </Botao>
              )}
            </li>
          );
        })}
      </ol>
      {retorno && (
        <Aviso tom={retorno.tom} titulo={retorno.tom === "critico" ? "A skill não voltou" : undefined}>
          {retorno.texto}
        </Aviso>
      )}
    </div>
  );
}
