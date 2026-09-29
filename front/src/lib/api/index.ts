/* Cliente da API do escritório, repartido por domínio.
 *
 * Quem usa importa de "@/lib/api" como sempre; este índice reúne os módulos.
 * `buscar`, `comoJson` e `nomeDoAnexo` ficam de fora de propósito: são o
 * transporte interno dos módulos, não API pública. */

export { ApiError, cabecalhos, CREDENCIAIS, duplicidadesDoErro, urlApi } from "./base";
export * from "./acervo";
export * from "./analise";
export * from "./assinatura";
export * from "./casos";
export * from "./chamada";
export * from "./contrato";
export * from "./documentacao";
export * from "./entregas";
export * from "./entrevista";
export * from "./extracao";
export * from "./followup";
export * from "./gastos";
export * from "./glossario";
export * from "./gravacoes";
export * from "./integracoes";
export * from "./investigacao";
export * from "./mensagens";
export * from "./peticao";
export * from "./revisao";
export * from "./roteiro";
export * from "./skills";
export * from "./supervisao";
export * from "./tiposCaso";
export * from "./usuarios";
