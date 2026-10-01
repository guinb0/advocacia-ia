"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import CartaoWhatsapp from "@/components/whatsapp/CartaoWhatsapp";
import {
  AjudaCampo,
  Aviso,
  BarraAbas,
  Botao,
  BotaoAba,
  Campo,
  CampoSeletor,
  Cartao,
  Marcacao,
  RotuloCampo,
  Selo,
  Tabela,
  Td,
  Th,
  TrZebra,
  Vazio,
} from "@/components/ui/Basicos";
import {
  obterConfigAtendimento,
  salvarConfigAtendimento,
  type ConfigAtendimento,
} from "@/lib/api/atendimentos";
import {
  historicoWhatsapp,
  listarModelosWhatsapp,
  previaModeloWhatsapp,
  restaurarModeloWhatsapp,
  salvarModeloWhatsapp,
  type EnvioWhatsapp,
  type ModeloWhatsapp,
} from "@/lib/api/whatsappModelos";

/* O WhatsApp do escritório num lugar só: conexão, textos das mensagens,
 * periodicidade padrão dos lembretes e o histórico do que saiu (e chegou). */

type Aba = "conexao" | "modelos" | "lembretes" | "historico";

const ROTULO_TIPO: Record<string, string> = {
  confirmacao_agendamento: "Confirmação",
  lembrete_agendamento: "Lembrete",
  cliente_faltou: "Falta",
  cobranca_documentos: "Cobrança de documentos",
  avaliacao_google: "Avaliação Google",
};

function rotuloTipo(tipo: string): string {
  return ROTULO_TIPO[tipo] ?? tipo.replace(/_/g, " ");
}

function quando(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function situacao(envio: EnvioWhatsapp): string {
  return (envio.status_entrega || envio.status || "").toLowerCase();
}

const ROTULO_SITUACAO: Record<string, string> = {
  pendente: "pendente",
  processando: "enviando",
  enviando: "enviando",
  enviado: "enviado",
  entregue: "entregue",
  lido: "lido",
  falhou: "falhou",
  expirado: "não confirmado",
  destinatario_invalido: "número sem WhatsApp",
};

function tomEntrega(envio: EnvioWhatsapp): "ok" | "info" | "atencao" | "critico" | "neutro" {
  const s = situacao(envio);
  if (s === "lido" || s === "entregue") return "ok";
  if (s === "enviado") return "info";
  if (s === "falhou" || s === "destinatario_invalido" || s === "expirado") return "critico";
  if (s === "pendente" || s === "enviando" || s === "processando") return "atencao";
  return "neutro";
}

function EditorModelo({ modelo, variaveis, onSalvo }: { modelo: ModeloWhatsapp; variaveis: string[]; onSalvo: () => void }) {
  const [texto, setTexto] = useState(modelo.texto);
  const [ativo, setAtivo] = useState(modelo.ativo);
  const [previa, setPrevia] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const alterado = texto !== modelo.texto || ativo !== modelo.ativo;

  const executar = async (acao: () => Promise<unknown>) => {
    setOcupado(true);
    setErro(null);
    try {
      await acao();
      onSalvo();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar o modelo.");
    } finally {
      setOcupado(false);
    }
  };

  return (
    <Cartao className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="m-0 text-base font-semibold text-tinta">{modelo.nome || modelo.codigo}</h3>
          {modelo.descricao && <p className="m-0 mt-1 text-xs text-tinta-3">{modelo.descricao}</p>}
        </div>
        <div className="flex flex-wrap gap-1">
          {modelo.personalizado && <Selo tom="info">personalizado</Selo>}
          <Selo tom={modelo.ativo ? "ok" : "neutro"}>{modelo.ativo ? "ativo" : "desativado"}</Selo>
        </div>
      </div>
      <Campo area className="mt-3 font-codigo text-sm" rows={6} value={texto} onChange={(e) => setTexto(e.target.value)} />
      <AjudaCampo>
        Variáveis: {variaveis.map((v) => `{${v}}`).join(" ")}
      </AjudaCampo>
      <div className="mt-2">
        <Marcacao>
          <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} />
          Enviar esta mensagem automaticamente
        </Marcacao>
      </div>
      {erro && (
        <div className="mt-2">
          <Aviso tom="critico">{erro}</Aviso>
        </div>
      )}
      {previa !== null && (
        <pre className="mt-3 whitespace-pre-wrap rounded-campo border border-borda bg-papel-2 p-3 font-ui text-sm text-tinta-2">{previa}</pre>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Botao
          variante="primario"
          pequeno
          disabled={!alterado || !texto.trim()}
          carregando={ocupado}
          onClick={() => void executar(() => salvarModeloWhatsapp(modelo.codigo, { texto, ativo, versao: modelo.versao }))}
        >
          Salvar
        </Botao>
        <Botao
          variante="secundario"
          pequeno
          disabled={ocupado}
          onClick={() =>
            void previaModeloWhatsapp(modelo.codigo, texto)
              .then(setPrevia)
              .catch((e: unknown) => setErro(e instanceof Error ? e.message : "Prévia indisponível."))
          }
        >
          Pré-visualizar
        </Botao>
        {modelo.personalizado && (
          <Botao
            variante="discreto"
            pequeno
            disabled={ocupado}
            onClick={() => {
              if (window.confirm("Voltar ao texto padrão deste modelo?")) {
                void executar(() => restaurarModeloWhatsapp(modelo.codigo));
              }
            }}
          >
            Restaurar padrão
          </Botao>
        )}
      </div>
    </Cartao>
  );
}

function AbaModelos() {
  const [dados, setDados] = useState<{ modelos: ModeloWhatsapp[]; variaveis: string[] } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const carregar = useCallback(() => {
    void listarModelosWhatsapp()
      .then((r) => {
        setDados(r);
        setErro(null);
      })
      .catch((e: unknown) => setErro(e instanceof Error ? e.message : "Não foi possível carregar os modelos."));
  }, []);
  useEffect(carregar, [carregar]);

  if (erro) return <Aviso tom="critico">{erro}</Aviso>;
  if (!dados) return <Vazio>Carregando os modelos…</Vazio>;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {dados.modelos.map((m) => (
        <EditorModelo key={`${m.codigo}-${m.versao}`} modelo={m} variaveis={dados.variaveis} onSalvo={carregar} />
      ))}
    </div>
  );
}

function AbaLembretes() {
  const [config, setConfig] = useState<ConfigAtendimento | null>(null);
  const [minutos, setMinutos] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    void obterConfigAtendimento()
      .then((c) => {
        setConfig(c);
        setMinutos(c.lembretes.minutos_antes_no_dia.join(", "));
      })
      .catch((e: unknown) => setErro(e instanceof Error ? e.message : "Não foi possível carregar a configuração."));
  }, []);

  if (erro && !config) return <Aviso tom="critico">{erro}</Aviso>;
  if (!config) return <Vazio>Carregando…</Vazio>;

  const salvar = async () => {
    setSalvando(true);
    setErro(null);
    setAviso(null);
    try {
      const lista = minutos
        .split(/[,;\s]+/)
        .map((t) => parseInt(t, 10))
        .filter((n) => Number.isFinite(n) && n > 0 && n <= 1440)
        .slice(0, 6);
      const salvo = await salvarConfigAtendimento({
        escalonar_apos_min: config.escalonar_apos_min,
        tolerancia_falta_min: config.tolerancia_falta_min,
        enviar_falta_automatico: config.enviar_falta_automatico,
        lembretes: { ...config.lembretes, minutos_antes_no_dia: lista },
      });
      setConfig(salvo);
      setMinutos(salvo.lembretes.minutos_antes_no_dia.join(", "));
      setAviso("Configuração salva.");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  };

  const numero = (valor: string, min: number, max: number, padrao: number) =>
    Math.max(min, Math.min(max, Number(valor) || padrao));

  return (
    <Cartao titulo="Lembretes e prazos padrão" subtitulo="Valem para todo agendamento que não tiver lembretes próprios.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Marcacao>
          <input
            type="checkbox"
            checked={config.lembretes.ativo}
            onChange={(e) => setConfig({ ...config, lembretes: { ...config.lembretes, ativo: e.target.checked } })}
          />
          Enviar lembretes automáticos
        </Marcacao>
        <Marcacao>
          <input
            type="checkbox"
            checked={config.enviar_falta_automatico}
            onChange={(e) => setConfig({ ...config, enviar_falta_automatico: e.target.checked })}
          />
          Avisar o cliente quando ele faltar
        </Marcacao>
        <div>
          <RotuloCampo htmlFor="cfg-dias">Lembrar a cada (dias) antes da data</RotuloCampo>
          <Campo
            id="cfg-dias"
            type="number"
            min={0}
            max={30}
            value={config.lembretes.intervalo_dias}
            onChange={(e) =>
              setConfig({ ...config, lembretes: { ...config.lembretes, intervalo_dias: numero(e.target.value, 0, 30, 0) } })
            }
          />
          <AjudaCampo>0 desliga os lembretes dos dias anteriores.</AjudaCampo>
        </div>
        <div>
          <RotuloCampo htmlFor="cfg-minutos">No dia: minutos antes</RotuloCampo>
          <Campo id="cfg-minutos" value={minutos} placeholder="120, 30" onChange={(e) => setMinutos(e.target.value)} />
          <AjudaCampo>Até 6 horários, separados por vírgula.</AjudaCampo>
        </div>
        <div>
          <RotuloCampo htmlFor="cfg-escalonar">Avisar a equipe se o cliente esperar (min)</RotuloCampo>
          <Campo
            id="cfg-escalonar"
            type="number"
            min={1}
            max={240}
            value={config.escalonar_apos_min}
            onChange={(e) => setConfig({ ...config, escalonar_apos_min: numero(e.target.value, 1, 240, 5) })}
          />
        </div>
        <div>
          <RotuloCampo htmlFor="cfg-tolerancia">Tolerância para falta (min)</RotuloCampo>
          <Campo
            id="cfg-tolerancia"
            type="number"
            min={1}
            max={240}
            value={config.tolerancia_falta_min}
            onChange={(e) => setConfig({ ...config, tolerancia_falta_min: numero(e.target.value, 1, 240, 15) })}
          />
        </div>
      </div>
      {erro && (
        <div className="mt-3">
          <Aviso tom="critico">{erro}</Aviso>
        </div>
      )}
      {aviso && (
        <div className="mt-3">
          <Aviso tom="ok">{aviso}</Aviso>
        </div>
      )}
      <div className="mt-4">
        <Botao variante="primario" onClick={() => void salvar()} carregando={salvando} textoCarregando="Salvando…">
          Salvar configuração
        </Botao>
      </div>
    </Cartao>
  );
}

function AbaHistorico() {
  const [dias, setDias] = useState(7);
  const [tipo, setTipo] = useState("");
  const [envios, setEnvios] = useState<EnvioWhatsapp[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    void historicoWhatsapp({ dias, tipo: tipo || undefined })
      .then((r) => {
        setEnvios(r);
        setErro(null);
      })
      .catch((e: unknown) => setErro(e instanceof Error ? e.message : "Não foi possível carregar o histórico."));
  }, [dias, tipo]);
  useEffect(carregar, [carregar]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <RotuloCampo htmlFor="hist-dias">Período</RotuloCampo>
          <CampoSeletor id="hist-dias" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
            <option value={1}>Últimas 24 horas</option>
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
          </CampoSeletor>
        </div>
        <div>
          <RotuloCampo htmlFor="hist-tipo">Tipo</RotuloCampo>
          <CampoSeletor id="hist-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(ROTULO_TIPO).map(([codigo, rotulo]) => (
              <option key={codigo} value={codigo}>
                {rotulo}
              </option>
            ))}
          </CampoSeletor>
        </div>
        <Botao variante="discreto" onClick={carregar} aria-label="Atualizar">
          <RefreshCw aria-hidden className="size-4" />
        </Botao>
      </div>
      {erro && <Aviso tom="critico">{erro}</Aviso>}
      {!envios ? (
        <Vazio>Carregando…</Vazio>
      ) : envios.length === 0 ? (
        <Vazio>Nenhuma mensagem neste período.</Vazio>
      ) : (
        <div className="overflow-x-auto rounded-cartao border border-borda-forte bg-papel">
          <Tabela>
            <thead>
              <tr>
                <Th>Quando</Th>
                <Th>Tipo</Th>
                <Th>Destino</Th>
                <Th>Situação</Th>
                <Th>Mensagem</Th>
              </tr>
            </thead>
            <tbody>
              {envios.map((e) => (
                <TrZebra key={e.chave}>
                  <Td className="whitespace-nowrap">{quando(e.enviado_em || e.atualizado_em)}</Td>
                  <Td>{rotuloTipo(e.tipo)}</Td>
                  <Td className="whitespace-nowrap tabular-nums">{e.destino}</Td>
                  <Td>
                    <Selo tom={tomEntrega(e)}>{ROTULO_SITUACAO[situacao(e)] ?? situacao(e)}</Selo>
                    {e.tentativas > 1 && <div className="mt-1 text-[11px] text-tinta-3">{e.tentativas} tentativas</div>}
                    {e.ultimo_erro && <div className="mt-1 max-w-[260px] text-[11px] text-critico">{e.ultimo_erro}</div>}
                  </Td>
                  <Td className="max-w-[420px] text-xs">{e.texto_resumo || "—"}</Td>
                </TrZebra>
              ))}
            </tbody>
          </Tabela>
        </div>
      )}
    </div>
  );
}

export default function ModuloWhatsapp() {
  const [aba, setAba] = useState<Aba>("conexao");
  return (
    <div className="space-y-4">
      <BarraAbas>
        {(
          [
            ["conexao", "Conexão"],
            ["modelos", "Modelos de mensagem"],
            ["lembretes", "Lembretes"],
            ["historico", "Histórico"],
          ] as [Aba, string][]
        ).map(([codigo, rotulo]) => (
          <BotaoAba key={codigo} ativa={aba === codigo} onClick={() => setAba(codigo)}>
            {rotulo}
          </BotaoAba>
        ))}
      </BarraAbas>
      {aba === "conexao" && <CartaoWhatsapp />}
      {aba === "modelos" && <AbaModelos />}
      {aba === "lembretes" && <AbaLembretes />}
      {aba === "historico" && <AbaHistorico />}
    </div>
  );
}
