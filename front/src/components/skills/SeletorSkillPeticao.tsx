"use client";

import { useEffect, useState } from "react";

import { AjudaCampo, Aviso, CampoSeletor, RotuloCampo } from "@/components/ui/Basicos";
import { definirSkillDoCaso, obterCaso, obterSkillPeticao, type EstadoSkillPeticao } from "@/lib/api";

/** O seletor ligado a um caso já criado: grava a escolha na hora. */
export function SkillDoCaso({ casoId, desabilitado }: { casoId: string; desabilitado?: boolean }) {
  const [valor, setValor] = useState<string | null>(null);
  const [gravando, setGravando] = useState(false);
  const [recado, setRecado] = useState<{ tom: "ok" | "critico"; texto: string } | null>(null);

  useEffect(() => {
    let vivo = true;
    setValor(null);
    void obterCaso(casoId)
      .then((situacao) => {
        if (vivo) setValor(situacao.caso.skill_juridica_id ?? "");
      })
      .catch(() => {
        if (vivo) setValor("");
      });
    return () => {
      vivo = false;
    };
  }, [casoId]);

  async function mudar(skillId: string) {
    const anterior = valor ?? "";
    setValor(skillId);
    setGravando(true);
    setRecado(null);
    try {
      await definirSkillDoCaso(casoId, skillId);
      setRecado({ tom: "ok", texto: "Skill trocada. Vale a partir da próxima vez que a petição for gerada." });
    } catch (e) {
      setValor(anterior);
      setRecado({ tom: "critico", texto: e instanceof Error ? e.message : "Não foi possível trocar a skill." });
    } finally {
      setGravando(false);
    }
  }

  if (valor === null) return null;
  return (
    <div className="grid gap-2">
      <SeletorSkillPeticao
        id={`skill-do-caso-${casoId}`}
        valor={valor}
        onMudar={(skillId) => void mudar(skillId)}
        desabilitado={desabilitado || gravando}
      />
      {recado && <Aviso tom={recado.tom}>{recado.texto}</Aviso>}
    </div>
  );
}

/** Escolhe a skill que gera a petição de um caso. `""` = a skill em uso no escritório. */
export default function SeletorSkillPeticao({
  id,
  valor,
  onMudar,
  desabilitado,
  ajuda = "Muda o texto, a ordem das partes e o visual da petição deste caso. Na dúvida, deixe no padrão.",
}: {
  id: string;
  valor: string;
  onMudar: (skillId: string) => void;
  desabilitado?: boolean;
  ajuda?: string;
}) {
  const [estado, setEstado] = useState<EstadoSkillPeticao | null>(null);

  useEffect(() => {
    let vivo = true;
    void obterSkillPeticao()
      .then((atual) => {
        if (vivo) setEstado(atual);
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, []);

  if (!estado) return null;
  const padrao = `Padrão do escritório (${estado.ativa.nome})`;

  if (estado.disponiveis.length === 0) {
    return (
      <div>
        <p className="m-0 mb-[6px] text-sm font-semibold text-tinta">Skill que vai escrever a petição</p>
        <p className="m-0 text-sm text-tinta">{padrao}</p>
        <AjudaCampo>
          Por enquanto só existe esta. Para ter outras opções, vá em Skills e clique em &quot;Adicionar uma skill&quot;.
        </AjudaCampo>
      </div>
    );
  }

  return (
    <div>
      <RotuloCampo htmlFor={id}>Skill que vai escrever a petição</RotuloCampo>
      <CampoSeletor id={id} value={valor} disabled={desabilitado} onChange={(e) => onMudar(e.target.value)}>
        <option value="">{padrao}</option>
        {estado.disponiveis.map((skill) => (
          <option key={skill.id} value={skill.id}>
            {skill.nome}
          </option>
        ))}
      </CampoSeletor>
      <AjudaCampo>{ajuda}</AjudaCampo>
    </div>
  );
}
