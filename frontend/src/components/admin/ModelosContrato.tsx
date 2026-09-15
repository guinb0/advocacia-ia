"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileText, RefreshCw, RotateCcw, Upload } from "lucide-react";

import { Aviso, Botao, Cartao, LinkBotao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  enviarModeloContrato,
  listarModelosContrato,
  restaurarModeloContratoAnterior,
  urlModeloContrato,
  type ModeloContrato,
} from "@/lib/api";

function data(valor?: string) {
  if (!valor) return "modelo padrão do sistema";
  const instante = new Date(valor);
  return Number.isNaN(instante.getTime()) ? valor : instante.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

type Resultado = { tom: "ok" | "atencao"; texto: string; semOrigem: string[] };

export default function ModelosContrato() {
  const [modelos, setModelos] = useState<ModeloContrato[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [enviando, setEnviando] = useState<string | null>(null);
  const [restaurando, setRestaurando] = useState<string | null>(null);
  const [resultados, setResultados] = useState<Record<string, Resultado>>({});
  const seletores = useRef<Record<string, HTMLInputElement | null>>({});

  async function carregar() {
    setCarregando(true);
    try {
      setModelos(await listarModelosContrato());
      setErro(null);
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível carregar os modelos de contrato.");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => { void carregar(); }, []);

  async function enviar(modelo: ModeloContrato, arquivo?: File) {
    if (!arquivo) return;
    setErro(null);
    if (!arquivo.name.toLowerCase().endsWith(".docx")) {
      setErro("Para preencher os dados do cliente, o modelo precisa ser um arquivo .docx (Word). PDF não permite o preenchimento automático.");
      return;
    }
    setEnviando(modelo.codigo);
    try {
      const resposta = await enviarModeloContrato(modelo.codigo, arquivo);
      const semOrigem = resposta.sem_origem ?? [];
      setResultados((atuais) => ({
        ...atuais,
        [modelo.codigo]: {
          tom: semOrigem.length ? "atencao" : "ok",
          texto: `Nova versão em uso. O teste de preenchimento passou e o sistema reconheceu ${resposta.marcadores?.length ?? 0} campo(s).`,
          semOrigem,
        },
      }));
      await carregar();
    } catch (falha) {
      setErro(
        `${modelo.rotulo}: ${falha instanceof ApiError ? falha.message : "não foi possível substituir o modelo."} A versão atual continua funcionando.`,
      );
    } finally {
      setEnviando(null);
    }
  }

  async function restaurar(modelo: ModeloContrato) {
    if (!window.confirm(`Voltar o ${modelo.rotulo} para a versão anterior (${modelo.anterior_arquivo})?`)) return;
    setErro(null);
    setRestaurando(modelo.codigo);
    try {
      await restaurarModeloContratoAnterior(modelo.codigo);
      setResultados((atuais) => ({
        ...atuais,
        [modelo.codigo]: { tom: "ok", texto: "Versão anterior restaurada e em uso.", semOrigem: [] },
      }));
      await carregar();
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível restaurar a versão anterior.");
    } finally {
      setRestaurando(null);
    }
  }

  return (
    <section className="space-y-5">
      <Cartao
        titulo="Modelos de contrato"
        subtitulo="Troque os três documentos usados para gerar e enviar à assinatura: contrato de honorários, procuração e declaração de hipossuficiência."
      >
        <div className="mb-4 flex justify-end">
          <Botao pequeno variante="secundario" onClick={() => void carregar()} carregando={carregando}><RefreshCw size={14} />Atualizar</Botao>
        </div>
        <Aviso tom="info" titulo="Como trocar sem quebrar nada">
          1. Baixe o modelo em uso e edite no Word, mantendo os campos entre colchetes, como <strong>[nome completo]</strong> e <strong>[CPF]</strong>.{" "}
          2. Envie a nova versão em <strong>.docx</strong>. Antes de trocar, o sistema faz um teste de preenchimento: se o arquivo não servir, nada muda e a versão atual continua funcionando.{" "}
          3. Se algo sair errado depois, use <strong>Restaurar versão anterior</strong>.
        </Aviso>
      </Cartao>
      {erro && <Aviso tom="critico" titulo="O modelo não foi trocado">{erro}</Aviso>}
      {carregando && modelos.length === 0 ? <Vazio>Carregando modelos…</Vazio> : (
        <div className="grid gap-4 lg:grid-cols-3">
          {modelos.map((modelo) => {
            const resultado = resultados[modelo.codigo];
            return (
              <Cartao key={modelo.codigo} className="flex min-w-0 flex-col" titulo={<span className="inline-flex items-center gap-2"><FileText size={18} className="text-acao" />{modelo.rotulo}</span>}>
                <div className="flex flex-1 flex-col gap-3 text-sm">
                  <div><span className="block text-xs font-semibold text-tinta-3">Arquivo em uso</span><strong className="mt-1 block break-words text-tinta">{modelo.arquivo || "Nenhum modelo disponível"}</strong></div>
                  <div className="flex flex-wrap gap-2"><Selo tom={modelo.disponivel ? "ok" : "critico"} simbolo={modelo.disponivel ? "✓" : "!"}>{modelo.disponivel ? "disponível" : "pendente"}</Selo><Selo tom="neutro">{modelo.origem === "banco" ? "enviado pelo escritório" : "padrão local"}</Selo></div>
                  <p className="m-0 text-xs text-tinta-3">Atualizado: {data(modelo.atualizado_em)}{modelo.enviado_por ? ` por ${modelo.enviado_por}` : ""}</p>
                  {resultado && (
                    <div className={`border-l-[3px] px-3 py-2 text-xs leading-[1.5] ${resultado.tom === "ok" ? "border-ok text-ok" : "border-atencao text-tinta-2"}`}>
                      <strong className="block">{resultado.texto}</strong>
                      {resultado.semOrigem.length > 0 && (
                        <span className="mt-1 block">
                          Estes campos o sistema não sabe preencher e vão sair em branco: {resultado.semOrigem.map((campo) => `[${campo}]`).join(", ")}.
                        </span>
                      )}
                    </div>
                  )}
                  <input ref={(elemento) => { seletores.current[modelo.codigo] = elemento; }} className="sr-only" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(evento) => { void enviar(modelo, evento.target.files?.[0]); evento.currentTarget.value = ""; }} />
                  <div className="mt-auto grid gap-2">
                    <Botao variante="primario" bloco carregando={enviando === modelo.codigo} textoCarregando="Testando e enviando…" onClick={() => seletores.current[modelo.codigo]?.click()}><Upload size={16} />Enviar nova versão</Botao>
                    {modelo.disponivel && (
                      <LinkBotao variante="secundario" href={urlModeloContrato(modelo.codigo)} download>
                        <Download size={16} />Baixar modelo em uso
                      </LinkBotao>
                    )}
                    {modelo.tem_anterior && (
                      <Botao variante="texto" pequeno carregando={restaurando === modelo.codigo} textoCarregando="Restaurando…" onClick={() => void restaurar(modelo)}>
                        <RotateCcw size={14} />Restaurar versão anterior
                      </Botao>
                    )}
                  </div>
                </div>
              </Cartao>
            );
          })}
        </div>
      )}
    </section>
  );
}
