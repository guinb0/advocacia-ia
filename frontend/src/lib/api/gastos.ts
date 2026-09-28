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
