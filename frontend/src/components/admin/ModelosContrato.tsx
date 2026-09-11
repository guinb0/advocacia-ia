"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, RefreshCw, Upload } from "lucide-react";

import { Aviso, Botao, Cartao, Selo, Vazio } from "@/components/ui/Basicos";
import {
  ApiError,
  enviarModeloContrato,
  listarModelosContrato,
  type ModeloContrato,
} from "@/lib/api";

function data(valor?: string) {
  if (!valor) return "modelo padrão do sistema";
  const instante = new Date(valor);
  return Number.isNaN(instante.getTime()) ? valor : instante.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function ModelosContrato() {
  const [modelos, setModelos] = useState<ModeloContrato[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [enviando, setEnviando] = useState<string | null>(null);
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
    if (!arquivo.name.toLowerCase().endsWith(".docx")) {
      setErro("Para preencher os dados do cliente, o modelo precisa ser um arquivo .docx. PDF pode ser usado como referência, mas não permite o preenchimento automático.");
      return;
    }
    setEnviando(modelo.codigo);
    try {
      await enviarModeloContrato(modelo.codigo, arquivo);
      await carregar();
    } catch (falha) {
      setErro(falha instanceof ApiError ? falha.message : "Não foi possível substituir o modelo.");
    } finally {
      setEnviando(null);
    }
  }

  return (
    <section className="space-y-5">
      <Cartao
        titulo="Modelos de contrato"
        subtitulo="Substitua os três documentos padrão usados para gerar e enviar contratos à assinatura."
        acoes={<Botao pequeno variante="secundario" onClick={() => void carregar()} carregando={carregando}><RefreshCw size={14} />Atualizar</Botao>}
      >
        <Aviso tom="info" titulo="Modelo editável">
          Envie a versão em <strong>DOCX</strong> com os campos entre colchetes. O sistema preenche esses campos antes de gerar o PDF e enviar para assinatura. Um PDF pode servir de referência, mas não pode ser preenchido automaticamente.
        </Aviso>
      </Cartao>
      {erro && <Aviso tom="critico" titulo="Não foi possível concluir">{erro}</Aviso>}
      {carregando ? <Vazio>Carregando modelos…</Vazio> : (
        <div className="grid gap-4 lg:grid-cols-3">
          {modelos.map((modelo) => (
            <Cartao key={modelo.codigo} className="flex min-w-0 flex-col" titulo={<span className="inline-flex items-center gap-2"><FileText size={18} className="text-acao" />{modelo.rotulo}</span>}>
              <div className="flex flex-1 flex-col gap-3 text-sm">
                <div><span className="block text-xs font-semibold text-tinta-3">Arquivo em uso</span><strong className="mt-1 block break-words text-tinta">{modelo.arquivo || "Nenhum modelo disponível"}</strong></div>
                <div className="flex flex-wrap gap-2"><Selo tom={modelo.disponivel ? "ok" : "critico"} simbolo={modelo.disponivel ? "✓" : "!"}>{modelo.disponivel ? "disponível" : "pendente"}</Selo><Selo tom="neutro">{modelo.origem === "banco" ? "enviado pelo escritório" : "padrão local"}</Selo></div>
                <p className="m-0 text-xs text-tinta-3">Atualizado: {data(modelo.atualizado_em)}{modelo.enviado_por ? ` por ${modelo.enviado_por}` : ""}</p>
                <input ref={(elemento) => { seletores.current[modelo.codigo] = elemento; }} className="sr-only" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf" onChange={(evento) => { void enviar(modelo, evento.target.files?.[0]); evento.currentTarget.value = ""; }} />
                <Botao variante="primario" bloco carregando={enviando === modelo.codigo} textoCarregando="Enviando…" onClick={() => seletores.current[modelo.codigo]?.click()}><Upload size={16} />Substituir modelo</Botao>
              </div>
            </Cartao>
          ))}
        </div>
      )}
    </section>
  );
}
