"use client";

import { useState } from "react";

import { gerarRelatorio } from "@/lib/api";
import type { RelatorioGerado } from "@/lib/api";
import estilos from "./RelatorioEntrevista.module.css";

/* O relatório analisado da entrevista, para a equipe jurídica.
 *
 * Aparece quando a entrevista fecha. Sai em PDF com o símbolo do escritório,
 * organiza as respostas na ordem do roteiro e — quando a base de precedentes
 * responde — traz a análise assistida (síntese, ações, riscos, lacunas).
 *
 * Por que um clique e não download automático: a análise busca precedentes e
 * chama o modelo, o que pode levar de segundos a mais de um minuto. Um arquivo
 * baixando sozinho no meio disso, sem a tela dizer que está trabalhando, pareceria
 * travamento. O botão deixa o tempo visível e o controle com quem conduz. */

interface Props {
  respostas: Record<string, string | string[]>;
  /** O relato corrido da entrevista — é dele que sai a análise por precedentes. */
  relato: string;
}

/** Dispara o download de um blob que já veio pela API com o Bearer anexado. */
function baixar(arquivo: Blob, nome: string): void {
  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.click();
  URL.revokeObjectURL(url);
}

export default function RelatorioEntrevista({ respostas, relato }: Props) {
  const [gerando, setGerando] = useState(false);
  const [feito, setFeito] = useState<RelatorioGerado | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function gerar() {
    setErro(null);
    setGerando(true);
    try {
      const r = await gerarRelatorio(respostas, relato);
      baixar(r.arquivo, r.nome);
      setFeito(r);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível gerar o relatório.");
    } finally {
      setGerando(false);
    }
  }

  return (
    <section className={estilos.bloco}>
      <span className={estilos.rotulo}>RELATÓRIO DA ENTREVISTA</span>
      <p className={estilos.texto}>
        Documento PDF com o símbolo do escritório para a equipe jurídica: as
        respostas na ordem do roteiro, o que ficou sem responder e uma análise
        assistida por precedentes.
      </p>

      <div className={estilos.linha}>
        <button
          type="button"
          className={estilos.botao}
          onClick={gerar}
          disabled={gerando}
        >
          {gerando
            ? "Gerando…"
            : feito
              ? "Gerar de novo"
              : "Gerar relatório analisado (PDF)"}
        </button>

        {gerando && (
          <span className={estilos.meta}>
            buscando precedentes e analisando — pode levar até um minuto
          </span>
        )}
      </div>

      {erro && <p className={estilos.erro}>{erro}</p>}

      {feito && !gerando && (
        <p className={estilos.estado} aria-live="polite">
          Baixado.{" "}
          {feito.analise === "sim"
            ? "Com análise por precedentes."
            : feito.analise === "indisponivel"
              ? "Sem a análise — a base de precedentes não respondeu; dá para gerar de novo."
              : "Sem análise."}
          {feito.impedimentos > 0 && ` ${feito.impedimentos} impedimento(s) sinalizado(s).`}
          {feito.pendencias > 0 && ` ${feito.pendencias} pendência(s) obrigatória(s).`}
        </p>
      )}
    </section>
  );
}
