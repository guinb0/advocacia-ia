"use client";

/**
 * Passo a passo para adicionar uma skill, uma pergunta por tela.
 *
 * Existem dois tipos de skill que se comportam de forma muito diferente — a que escreve
 * as petições (substitui a atual e precisa cobrir a peça inteira) e as demais (viram um
 * item novo no menu). Antes havia um botão de enviar ZIP para cada uma, em lugares
 * diferentes da tela, e quem enviava no lugar errado não entendia por que nada mudava.
 */

import { useRef, useState, type ReactNode } from "react";
import { Check, FileArchive, FileText, PenLine, Puzzle, Upload, X } from "lucide-react";

import { AjudaCampo, Aviso, Botao, Campo, Cartao, RotuloCampo } from "@/components/ui/Basicos";
import { criarSkill, enviarSkillPeticao, importarSkillJuridica, type EstadoSkillPeticao } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tipo = "peticao" | "outra";
type Tela =
  | { passo: "tipo" }
  | { passo: "como" }
  | { passo: "arquivo"; tipo: Tipo }
  | { passo: "escrever" }
  | { passo: "pronto"; texto: string; moduloId?: string };

function mensagem(e: unknown, padrao: string): string {
  return e instanceof Error && e.message ? e.message : padrao;
}

function Opcao({
  icone,
  titulo,
  descricao,
  onClick,
}: {
  icone: ReactNode;
  titulo: string;
  descricao: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-full cursor-pointer items-start gap-4 rounded-campo border-2 border-borda bg-papel p-5 text-left [font:inherit] transition-colors hover:border-acao hover:bg-acao-clara"
    >
      <span className="shrink-0 rounded-full bg-acao-clara p-3 text-acao" aria-hidden>
        {icone}
      </span>
      <span className="grid gap-1">
        <strong className="text-base text-tinta">{titulo}</strong>
        <span className="text-sm leading-relaxed text-tinta-2">{descricao}</span>
      </span>
    </button>
  );
}

function Cabecalho({ passo, total, pergunta }: { passo: number; total: number; pergunta: string }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-tinta-3">
        Passo {passo} de {total}
      </span>
      <h3 className="m-0 text-lg font-semibold text-tinta">{pergunta}</h3>
    </div>
  );
}

function AreaDoArquivo({
  enviando,
  onEscolher,
}: {
  enviando: boolean;
  onEscolher: (arquivo: File) => void;
}) {
  const [arrastando, setArrastando] = useState(false);
  const seletor = useRef<HTMLInputElement>(null);

  return (
    <div
      className={cn(
        "rounded-xl border-2 border-dashed p-8 text-center transition-colors",
        arrastando ? "border-acao bg-acao-clara" : "border-borda bg-papel-2",
      )}
      onDragEnter={(e) => {
        e.preventDefault();
        setArrastando(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setArrastando(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setArrastando(false);
        const arquivo = e.dataTransfer.files?.[0];
        if (arquivo && !enviando) onEscolher(arquivo);
      }}
    >
      <Upload className="mx-auto size-8 text-acao" aria-hidden />
      <p className="mt-3 mb-0 text-base font-semibold text-tinta">Arraste o arquivo da skill para cá</p>
      <p className="mt-1 mb-0 text-sm text-tinta-3">É um arquivo que termina em .zip</p>
      <div className="mt-4">
        <Botao
          variante="primario"
          onClick={() => seletor.current?.click()}
          carregando={enviando}
          textoCarregando="Conferindo o arquivo…"
        >
          <FileArchive aria-hidden className="size-4" />
          Ou clique aqui para escolher o arquivo
        </Botao>
      </div>
      <input
        ref={seletor}
        type="file"
        accept=".zip,application/zip,application/x-zip-compressed"
        className="hidden"
        onChange={(e) => {
          const arquivo = e.target.files?.[0];
          e.target.value = "";
          if (arquivo) onEscolher(arquivo);
        }}
      />
    </div>
  );
}

export default function AdicionarSkill({
  tipoInicial,
  onFechar,
  onPeticaoTrocada,
  onModuloCriado,
  onPrefiroInstrucoes,
}: {
  /** Pula a primeira pergunta quando já se sabe o tipo. */
  tipoInicial?: Tipo;
  onFechar: () => void;
  onPeticaoTrocada: (estado: EstadoSkillPeticao) => void;
  onModuloCriado: (skillId: string) => void;
  /** Quem só quer mudar umas regras não precisa de arquivo: vai para as instruções. */
  onPrefiroInstrucoes: () => void;
}) {
  const [tela, setTela] = useState<Tela>(tipoInicial ? { passo: "arquivo", tipo: tipoInicial } : { passo: "tipo" });
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [texto, setTexto] = useState("");

  function ir(proxima: Tela) {
    setErro(null);
    setTela(proxima);
  }

  async function enviarArquivo(tipo: Tipo, arquivo: File) {
    if (!/\.zip$/i.test(arquivo.name)) {
      setErro(`"${arquivo.name}" não é um arquivo .zip. A skill vem sempre num arquivo que termina em .zip.`);
      return;
    }
    setEnviando(true);
    setErro(null);
    try {
      if (tipo === "peticao") {
        const estado = await enviarSkillPeticao(arquivo);
        onPeticaoTrocada(estado);
        ir({ passo: "pronto", texto: `Pronto! As petições novas vão ser escritas com a skill "${estado.ativa.nome}".` });
      } else {
        const criada = await importarSkillJuridica(arquivo);
        window.dispatchEvent(new Event("skills-atualizadas"));
        ir({ passo: "pronto", texto: "Pronto! A skill foi adicionada e já aparece no menu.", moduloId: criada.id });
      }
    } catch (e) {
      setErro(mensagem(e, "Não foi possível usar este arquivo."));
    } finally {
      setEnviando(false);
    }
  }

  async function criarEscrita() {
    setEnviando(true);
    setErro(null);
    try {
      const criada = await criarSkill({ nome: nome.trim(), descricao: descricao.trim(), texto });
      window.dispatchEvent(new Event("skills-atualizadas"));
      ir({ passo: "pronto", texto: `Pronto! A skill "${nome.trim()}" foi criada e já aparece no menu.`, moduloId: criada.id });
    } catch (e) {
      setErro(mensagem(e, "Não foi possível criar a skill."));
    } finally {
      setEnviando(false);
    }
  }

  const voltar = (destino: Tela) => (
    <Botao type="button" variante="texto" onClick={() => ir(destino)} disabled={enviando}>
      ← Voltar
    </Botao>
  );

  return (
    <Cartao>
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="m-0 text-lg font-semibold text-tinta">Adicionar uma skill</h2>
        <button
          type="button"
          onClick={onFechar}
          className="inline-flex size-8 cursor-pointer items-center justify-center rounded-pill border-none bg-transparent text-tinta-3 hover:bg-papel-3 hover:text-tinta"
          aria-label="Fechar"
          title="Fechar"
        >
          <X className="size-5" aria-hidden />
        </button>
      </div>

      {tela.passo === "tipo" && (
        <div className="grid gap-4">
          <Cabecalho passo={1} total={2} pergunta="Para que serve essa skill?" />
          <div className="grid gap-3 md:grid-cols-2">
            <Opcao
              icone={<FileText className="size-6" />}
              titulo="Para escrever as petições"
              descricao="Muda o texto, a ordem das partes e o visual das petições que o sistema gera."
              onClick={() => ir({ passo: "arquivo", tipo: "peticao" })}
            />
            <Opcao
              icone={<Puzzle className="size-6" />}
              titulo="Para outra tarefa"
              descricao="Qualquer outra coisa, como analisar documentos. Vira um item novo no menu."
              onClick={() => ir({ passo: "como" })}
            />
          </div>
          <p className="m-0 text-sm text-tinta-3">Na dúvida, pergunte a quem te passou a skill para que ela serve.</p>
        </div>
      )}

      {tela.passo === "arquivo" && tela.tipo === "peticao" && (
        <div className="grid gap-4">
          <Cabecalho passo={2} total={2} pergunta="Envie o arquivo da skill de petição" />
          <AreaDoArquivo enviando={enviando} onEscolher={(arquivo) => void enviarArquivo("peticao", arquivo)} />
          <ul className="m-0 grid gap-1 pl-5 text-sm text-tinta-2">
            <li>O sistema confere o arquivo antes de usar. Se faltar alguma coisa, nada muda e aparece o que falta.</li>
            <li>Depois de enviar, as petições novas passam a usar essa skill. As que já existem não mudam.</li>
            <li>Se não gostar, dá para voltar atrás em &quot;Desfazer uma mudança&quot; ou &quot;Trocar por outra skill&quot;.</li>
          </ul>
          <Aviso tom="info" titulo="Não tem arquivo?">
            Se você só quer mudar algumas regras (por exemplo, &quot;sempre pedir justiça gratuita&quot;), não precisa de
            arquivo nenhum.{" "}
            <button
              type="button"
              onClick={onPrefiroInstrucoes}
              className="cursor-pointer border-none bg-transparent p-0 font-semibold text-acao underline [font:inherit]"
            >
              Escreva as instruções para a IA
            </button>
            .
          </Aviso>
          {erro && (
            <Aviso tom="critico" titulo="Este arquivo não serviu">
              {erro} Confira se é o arquivo certo e tente de novo.
            </Aviso>
          )}
          <div>{voltar({ passo: "tipo" })}</div>
        </div>
      )}

      {tela.passo === "como" && (
        <div className="grid gap-4">
          <Cabecalho passo={2} total={3} pergunta="Você já tem a skill pronta?" />
          <div className="grid gap-3 md:grid-cols-2">
            <Opcao
              icone={<FileArchive className="size-6" />}
              titulo="Sim, tenho um arquivo .zip"
              descricao="Alguém te mandou a skill pronta num arquivo."
              onClick={() => ir({ passo: "arquivo", tipo: "outra" })}
            />
            <Opcao
              icone={<PenLine className="size-6" />}
              titulo="Não, quero escrever"
              descricao="Você escreve, com suas palavras, o que a IA deve fazer."
              onClick={() => ir({ passo: "escrever" })}
            />
          </div>
          <div>{voltar({ passo: "tipo" })}</div>
        </div>
      )}

      {tela.passo === "arquivo" && tela.tipo === "outra" && (
        <div className="grid gap-4">
          <Cabecalho passo={3} total={3} pergunta="Envie o arquivo da skill" />
          <AreaDoArquivo enviando={enviando} onEscolher={(arquivo) => void enviarArquivo("outra", arquivo)} />
          {erro && (
            <Aviso tom="critico" titulo="Este arquivo não serviu">
              {erro} Confira se é o arquivo certo e tente de novo.
            </Aviso>
          )}
          <div>{voltar({ passo: "como" })}</div>
        </div>
      )}

      {tela.passo === "escrever" && (
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void criarEscrita();
          }}
        >
          <Cabecalho passo={3} total={3} pergunta="Escreva a skill" />
          <div>
            <RotuloCampo htmlFor="skill-nova-nome">1. Dê um nome</RotuloCampo>
            <Campo
              id="skill-nova-nome"
              value={nome}
              maxLength={120}
              autoFocus
              onChange={(e) => setNome(e.target.value)}
              placeholder="Ex.: Análise de documentos previdenciários"
            />
            <AjudaCampo>É o nome que vai aparecer no menu.</AjudaCampo>
          </div>
          <div>
            <RotuloCampo htmlFor="skill-nova-descricao">
              2. Para que ela serve? <span className="font-normal text-tinta-3">(opcional)</span>
            </RotuloCampo>
            <Campo
              id="skill-nova-descricao"
              value={descricao}
              maxLength={300}
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="Ex.: Confere se os documentos do INSS estão completos."
            />
          </div>
          <div>
            <RotuloCampo htmlFor="skill-nova-texto">3. O que a IA deve fazer?</RotuloCampo>
            <Campo
              id="skill-nova-texto"
              area
              rows={9}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder={"Escreva passo a passo, como explicaria para um estagiário. Exemplo:\n1. Confira se tem RG, CPF e comprovante de endereço.\n2. Veja se o CNIS está atualizado.\n3. Liste o que estiver faltando."}
            />
          </div>
          {erro && <Aviso tom="critico" titulo="A skill não foi criada">{erro}</Aviso>}
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              type="submit"
              variante="primario"
              disabled={!nome.trim() || !texto.trim()}
              carregando={enviando}
              textoCarregando="Criando…"
            >
              <Check aria-hidden className="size-4" />
              Criar a skill
            </Botao>
            {voltar({ passo: "como" })}
          </div>
          {(!nome.trim() || !texto.trim()) && (
            <p className="m-0 text-xs text-tinta-3">Preencha o nome e o que a IA deve fazer para liberar o botão.</p>
          )}
        </form>
      )}

      {tela.passo === "pronto" && (
        <div className="grid gap-4">
          <Aviso tom="ok">{tela.texto}</Aviso>
          <div className="flex flex-wrap gap-2">
            {tela.moduloId && (
              <Botao variante="primario" onClick={() => onModuloCriado(tela.moduloId as string)}>
                Ver a skill
              </Botao>
            )}
            <Botao variante={tela.moduloId ? "secundario" : "primario"} onClick={onFechar}>
              Concluir
            </Botao>
          </div>
        </div>
      )}
    </Cartao>
  );
}
