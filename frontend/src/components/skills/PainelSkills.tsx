"use client";

import { useCallback, useEffect, useState } from "react";

import { Aviso, Botao, Campo, Cartao, RotuloCampo, Selo, Vazio } from "@/components/ui/Basicos";
import {
  criarSkill,
  importarSkillJuridica,
  listarModulosDeSkill,
  obterModuloDeSkill,
  type SkillModulo,
  type SkillModuloDetalhe,
} from "@/lib/api";

import SkillDePeticao from "./SkillDePeticao";

export default function PainelSkills({
  skillId,
  onAbrir,
  onVoltar,
}: {
  skillId: string | null;
  onAbrir: (skillId: string) => void;
  onVoltar: () => void;
}) {
  const [skills, setSkills] = useState<SkillModulo[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      setSkills(await listarModulosDeSkill());
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível listar as skills.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  return (
    <div className="space-y-5">
      <div>
        <Botao variante="secundario" pequeno onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
        <h1 className="mt-[6px] mb-0 text-xl tracking-[-0.01em]">
          {skillId ? "Skill" : "Skills"}
        </h1>
        <p className="mt-[5px] mb-0 max-w-[66ch] text-tinta-2 text-base">
          A skill que gera as petições fica no primeiro cartão. As demais skills adicionadas ficam logo abaixo, cada uma no próprio módulo.
        </p>
      </div>

      {erro && <Aviso tom="critico">{erro}</Aviso>}

      {skillId ? (
        <ModuloDaSkill skillId={skillId} onVoltarLista={() => onAbrir("")} />
      ) : (
        <>
          <SkillDePeticao onMudou={() => void carregar()} />
          <h2 className="mt-2 mb-0 text-lg font-semibold text-tinta">Todas as skills</h2>
          {carregando && <p className="text-sm text-tinta-2">Carregando as skills…</p>}
          {!carregando && skills.length === 0 && (
            <Vazio>Nenhuma skill adicionada ainda.</Vazio>
          )}
          <ul className="m-0 grid list-none gap-3 p-0 md:grid-cols-2">
            {skills.map((skill) => (
              <li key={skill.id}>
                <button
                  type="button"
                  className="h-full w-full cursor-pointer rounded-campo border border-borda bg-papel p-4 text-left hover:border-acao"
                  onClick={() => onAbrir(skill.id)}
                >
                  <span className="flex items-center gap-2">
                    <strong className="text-sm text-tinta">{skill.nome}</strong>
                    <Selo tom={skill.origem === "arquivo" ? "ok" : "neutro"}>
                      {skill.origem === "arquivo" ? "no sistema" : "adicionada"}
                    </Selo>
                  </span>
                  {skill.descricao && (
                    <p className="m-0 mt-2 line-clamp-3 text-sm text-tinta-2">{skill.descricao}</p>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <AdicionarSkill
            onCriada={async (id) => {
              await carregar();
              onAbrir(id);
            }}
          />
        </>
      )}
    </div>
  );
}

function ModuloDaSkill({ skillId, onVoltarLista }: { skillId: string; onVoltarLista: () => void }) {
  const [detalhe, setDetalhe] = useState<SkillModuloDetalhe | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setDetalhe(null);
    setErro(null);
    void obterModuloDeSkill(skillId)
      .then((atual) => {
        if (vivo) setDetalhe(atual);
      })
      .catch((e: unknown) => {
        if (vivo) setErro(e instanceof Error ? e.message : "Não foi possível abrir esta skill.");
      });
    return () => {
      vivo = false;
    };
  }, [skillId]);

  return (
    <Cartao titulo={detalhe?.nome ?? "Abrindo a skill…"}>
      <Botao variante="discreto" pequeno onClick={onVoltarLista}>
        ← Todas as skills
      </Botao>
      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {detalhe && (
        <>
          <p className="text-sm text-tinta-2">{detalhe.descricao}</p>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 p-4 text-sm text-tinta">
            {detalhe.texto}
          </pre>
          {detalhe.cortado && <p className="text-xs text-tinta-3">O texto foi cortado nesta tela.</p>}
        </>
      )}
    </Cartao>
  );
}

function AdicionarSkill({ onCriada }: { onCriada: (id: string) => Promise<void> }) {
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [texto, setTexto] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function gravar() {
    setOcupado(true);
    setErro(null);
    try {
      const criada = await criarSkill({ nome, descricao, texto });
      setNome("");
      setDescricao("");
      setTexto("");
      window.dispatchEvent(new Event("skills-atualizadas"));
      await onCriada(criada.id);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível adicionar a skill.");
    } finally {
      setOcupado(false);
    }
  }

  async function importar(arquivo: File | null) {
    if (!arquivo) return;
    setOcupado(true);
    setErro(null);
    try {
      const criada = await importarSkillJuridica(arquivo);
      window.dispatchEvent(new Event("skills-atualizadas"));
      await onCriada(criada.id);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível importar a skill.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Cartao
      titulo="Adicionar outra skill"
      subtitulo="Ela abre como módulo próprio na barra, ao lado das que já existem. Para trocar a skill que gera as petições, use o cartão “Skill de geração de petição” lá em cima."
    >
      <div className="grid gap-3">
        <div>
          <RotuloCampo htmlFor="skill-nome">Nome</RotuloCampo>
          <Campo id="skill-nome" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Análise previdenciária" />
        </div>
        <div>
          <RotuloCampo htmlFor="skill-descricao">O que ela faz</RotuloCampo>
          <Campo id="skill-descricao" value={descricao} onChange={(e) => setDescricao(e.target.value)} />
        </div>
        <div>
          <RotuloCampo htmlFor="skill-texto">Texto da skill</RotuloCampo>
          <Campo id="skill-texto" area rows={8} value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Regras, etapas e o que a skill deve fazer." />
        </div>
        {erro && <Aviso tom="critico">{erro}</Aviso>}
        <div className="flex flex-wrap items-center gap-2">
          <Botao variante="primario" onClick={() => void gravar()} carregando={ocupado} disabled={!nome.trim() || !texto.trim()}>
            Adicionar como módulo
          </Botao>
          <label className="cursor-pointer text-sm font-semibold text-acao">
            ou importar .skill.zip
            <input
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(e) => {
                void importar(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>
    </Cartao>
  );
}
