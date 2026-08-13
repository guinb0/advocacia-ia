"use client";

import { useState } from "react";

import { gerarContrato } from "@/lib/api";
import estilos from "./PainelContrato.module.css";

/* Contrato de honorários, preenchido com o que a entrevista respondeu.
 *
 * O documento é o modelo oficial do escritório (`docs/CONTRATO oficial.docx`):
 * cláusulas, percentuais e inscrições na OAB saem de lá palavra por palavra. O
 * que este painel faz é levar os dados da qualificação para os colchetes e
 * devolver o arquivo para conferência e assinatura.
 *
 * É por isso que o botão diz "gerar" e não "enviar": ninguém assina nada aqui,
 * e o texto ainda passa pelos olhos do advogado. */

interface Props {
  /** Respostas do roteiro, como o `Roteiro` as devolve ao concluir. */
  respostas: Record<string, string | string[]>;
}

/** "nome da pessoa" → "Nome da pessoa", para o aviso de campo faltando. */
function legivel(campo: string): string {
  const texto = campo.replace(/\brg\b/i, "RG").replace(/\bcpf\b/i, "CPF");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export default function PainelContrato({ respostas }: Props) {
  const [gerando, setGerando] = useState(false);
  const [faltando, setFaltando] = useState<string[] | null>(null);
  const [baixado, setBaixado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const cliente = typeof respostas.nome === "string" ? respostas.nome.trim() : "";

  async function gerar() {
    setGerando(true);
    setErro(null);
    try {
      const contrato = await gerarContrato(respostas);
      setFaltando(contrato.faltando);
      setBaixado(contrato.nome);

      // Download por object URL: o arquivo já veio no corpo da resposta, com o
      // Bearer que uma navegação direta não levaria.
      const url = URL.createObjectURL(contrato.arquivo);
      const link = document.createElement("a");
      link.href = url;
      link.download = contrato.nome;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível gerar o contrato.");
    } finally {
      setGerando(false);
    }
  }

  return (
    <div className={estilos.bloco}>
      <span className={estilos.rotulo}>CONTRATO DE HONORÁRIOS</span>

      <p className={estilos.texto}>
        Preenche o modelo do escritório com a qualificação que a entrevista trouxe — nome,
        CPF, RG, endereço, telefone e e-mail. As cláusulas, os percentuais e o foro vêm do
        modelo, sem alteração.
      </p>

      <div className={estilos.acoes}>
        <button type="button" className={estilos.botao} onClick={gerar} disabled={gerando}>
          {gerando ? "Gerando…" : baixado ? "Gerar de novo" : "Gerar contrato"}
        </button>
        {cliente && <span className={estilos.cliente}>para {cliente}</span>}
      </div>

      {erro && <div className={estilos.erro}>{erro}</div>}

      {baixado && !erro && (
        <p className={estilos.baixado}>
          <strong>{baixado}</strong> foi baixado. Confira antes de mandar assinar.
        </p>
      )}

      {faltando && faltando.length > 0 && (
        <div className={estilos.faltando}>
          <strong>A entrevista não respondeu {faltando.length} campo(s):</strong>{" "}
          {faltando.map(legivel).join(", ")}.
          <span className={estilos.explicacao}>
            No documento eles continuam entre colchetes, à vista. Volte ao roteiro e
            complete, ou preencha à mão antes da assinatura — em branco passariam
            despercebidos na revisão.
          </span>
        </div>
      )}

      {faltando?.length === 0 && (
        <p className={estilos.completo}>
          ✓ Todos os campos do modelo foram preenchidos pela entrevista.
        </p>
      )}

      {baixado && (
        <p className={estilos.proximo}>
          Assinado o contrato, crie o caso abaixo: é ele que abre o checklist e o portal
          para o cliente enviar os documentos.
        </p>
      )}
    </div>
  );
}
