/** Gasto e saldo das APIs pagas. */

import { buscar, comoJson } from "./base";

export type SinalGastoApi = "ok" | "atencao" | "critico" | "desconhecido" | "ausente";

export type GastoApi = {
  id: string;
  nome: string;
  configurada: boolean;
  moeda: string;
  saldo: number | null;
  teto: number | null;
  sinal: SinalGastoApi;
  mensagem: string;
  gasto_24h: number;
  gasto_7d: number;
  gasto_30d: number;
  chamadas_30d: number;
  erros_30d: number;
  tokens_30d: number;
};

export async function obterGastosApi(): Promise<{ apis: GastoApi[]; atualizado_em: string }> {
  return comoJson(await buscar("/api/gastos-api"));
}

type Consumo = { custo_usd: number; tokens: number; chamadas: number; erros: number };

export type UsoDoDia = Consumo & {
  /** AAAA-MM-DD, no horário de Brasília. */
  dia: string;
  por_fornecedor: Record<string, { custo_usd: number; tokens: number }>;
};

export type UsoDaHora = Consumo & { /** AAAA-MM-DDTHH, no horário de Brasília. */ hora: string };

export type UsoDaOperacao = Consumo & {
  operacao: string;
  fornecedor: string;
  hoje_custo_usd: number;
  hoje_tokens: number;
};

export type AlertaDeUso = {
  nivel: "ok" | "atencao" | "critico";
  mensagem: string;
  /** Com custo informado compara em dólar; sem custo, em tokens. */
  medida: "custo" | "tokens";
  hoje: number;
  media: number;
  vezes: number | null;
  principal_hoje: { operacao: string; fornecedor: string; valor: number } | null;
};

export type UsoDasApis = {
  dias: number;
  fuso: string;
  por_dia: UsoDoDia[];
  por_hora: UsoDaHora[];
  por_operacao: UsoDaOperacao[];
  totais: Consumo;
  /** Fornecedores que gastaram tokens mas não informam o custo por chamada. */
  fornecedores_sem_custo: string[];
  alerta: AlertaDeUso;
  atualizado_em: string;
};

export async function obterUsoDasApis(dias = 30): Promise<UsoDasApis> {
  return comoJson(await buscar(`/api/gastos-api/uso?dias=${dias}`));
}
