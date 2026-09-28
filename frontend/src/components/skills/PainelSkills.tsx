"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  listarModulosDeSkill,
  obterModuloDeSkill,
  type SkillModulo,
  type SkillModuloDetalhe,
} from "@/lib/api";

import AdicionarSkill from "./AdicionarSkill";
import SkillDePeticao, { type PainelDaSkill } from "./SkillDePeticao";

type Adicionando = { tipo?: "peticao" } | null;

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
  const [adicionando, setAdicionando] = useState<Adicionando>(null);
  /* Remonta o cartão da petição: depois de enviar uma skill nova, ou para abrir um
   * painel dele a partir do passo a passo. */
  const [cartao, setCartao] = useState<{ versao: number; painel: PainelDaSkill | null }>({ versao: 0, painel: null });

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

  function abrirAdicionar(tipo?: "peticao") {
    setAdicionando(tipo ? { tipo } : {});
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (skillId) {
    return (
      <div className="space-y-5">
        <div>
          <Botao variante="secundario" pequeno onClick={() => onAbrir("")}>
            ← Voltar para Skills
          </Botao>
        </div>
        <ModuloDaSkill skillId={skillId} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <Botao variante="secundario" pequeno onClick={onVoltar}>
          ← Voltar para a carteira
        </Botao>
        <h1 className="mt-[6px] mb-0 text-xl tracking-[-0.01em]">Skills</h1>
        <p className="mt-[5px] mb-0 max-w-[66ch] text-tinta-2 text-base">
          Uma skill é um <strong>manual de instruções que a IA segue</strong>. Aqui você decide como a IA escreve as
          petições e pode ensinar tarefas novas a ela.
        </p>
      </div>

      {erro && <Aviso tom="critico">{erro}</Aviso>}

      {adicionando ? (
        <AdicionarSkill
          tipoInicial={adicionando.tipo}
          onFechar={() => setAdicionando(null)}
          onPeticaoTrocada={() => {
            window.dispatchEvent(new Event("skills-atualizadas"));
            setCartao((atual) => ({ versao: atual.versao + 1, painel: null }));
          }}
          onModuloCriado={(id) => {
            setAdicionando(null);
            void carregar();
            onAbrir(id);
          }}
          onPrefiroInstrucoes={() => {
            setAdicionando(null);
            setCartao((atual) => ({ versao: atual.versao + 1, painel: "instrucoes" }));
          }}
        />
      ) : (
        <Botao variante="primario" onClick={() => abrirAdicionar()}>
          <Plus aria-hidden className="size-5" />
          Adicionar uma skill
        </Botao>
      )}

      <SkillDePeticao
        key={cartao.versao}
        painelInicial={cartao.painel}
        onMudou={() => void carregar()}
        onEnviarNova={() => abrirAdicionar("peticao")}
      />

      <section className="grid gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold text-tinta">Outras skills</h2>
          <p className="mt-1 mb-0 text-sm text-tinta-3">
            Cada uma vira um item no menu. Clique para ver o que ela manda a IA fazer.
          </p>
        </div>
        {carregando && <p className="m-0 text-sm text-tinta-2">Carregando…</p>}
        {!carregando && skills.length === 0 && (
          <Vazio>Nenhuma outra skill ainda. Para criar uma, clique em &quot;Adicionar uma skill&quot;.</Vazio>
        )}
        <ul className="m-0 grid list-none gap-3 p-0 md:grid-cols-2">
          {skills.map((skill) => (
            <li key={skill.id}>
              <button
                type="button"
                className="h-full w-full cursor-pointer rounded-campo border border-borda bg-papel p-4 text-left [font:inherit] hover:border-acao"
                onClick={() => onAbrir(skill.id)}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <strong className="text-sm text-tinta">{skill.nome}</strong>
                  <Selo tom={skill.origem === "arquivo" ? "neutro" : "ok"}>
                    {skill.origem === "arquivo" ? "veio com o sistema" : "adicionada pelo escritório"}
                  </Selo>
                </span>
                {skill.descricao && (
                  <p className="m-0 mt-2 line-clamp-3 text-sm text-tinta-2">{skill.descricao}</p>
                )}
                <span className="mt-2 block text-xs font-semibold text-acao">Ver a skill →</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ModuloDaSkill({ skillId }: { skillId: string }) {
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
    <Cartao titulo={detalhe?.nome ?? "Abrindo a skill…"} subtitulo={detalhe?.descricao || undefined}>
      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {detalhe && (
        <>
          <p className="m-0 mb-2 text-sm font-semibold text-tinta">O que esta skill manda a IA fazer:</p>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 p-4 text-sm text-tinta">
            {detalhe.texto}
          </pre>
          {detalhe.cortado && <p className="text-xs text-tinta-3">O texto é longo e foi cortado nesta tela.</p>}
        </>
      )}
    </Cartao>
  );
}
