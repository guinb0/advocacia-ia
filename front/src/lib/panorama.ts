/**
 * Cliente do panorama do escritório — o painel analítico de todos os casos.
 *
 * O backend (`app/panorama.py`) entrega tudo pronto: estágios, medianas com amostra,
 * série mensal e ausências declaradas. Aqui não há derivação nenhuma, e é de propósito:
 * o painel do caso já ensinou que dois lugares calculando o mesmo número produzem dois
 * números. O que existe deste lado é o tipo e a chamada.
 *
 * Formatação de duração e de data vem de `lib/painel.ts` pela mesma razão — "3 d 4 h"
 * precisa ser a mesma frase nas duas telas.
 */

import { CREDENCIAIS, cabecalhos, urlApi } from "./api";
import type { Tom } from "./painel";

export interface IndicadorDoEscritorio {
  codigo: string;
  rotulo: string;
  /** `null` quando a amostra não sustenta o número — o detalhe diz por quê. */
  valor: number | null;
  unidade: string;
  detalhe: string;
  tom: Tom;
}

export interface FaixaDoFunil {
  codigo: string;
  titulo: string;
  descricao: string;
  tom: Tom;
  casos: number;
  percentual: number | null;
  /** Ids dos casos do estágio, para a fila poder ser filtrada por ele. */
  ids: string[];
}

export interface EtapaDoEscritorio {
  codigo: string;
  titulo: string;
  descricao: string;
  horas_totais: number;
  percentual: number | null;
  mediana_horas: number | null;
  amostra: number;
  /** Casos cujo relógio ainda corre nesta etapa. */
  em_curso: number;
  mais_antigo_horas: number | null;
  motivo: string | null;
}

export interface CategoriaDoEscritorio {
  codigo: string;
  nome: string;
  casos: number;
  em_andamento: number;
  instruidos: number;
  parados: number;
  /** Só dos casos que chegaram ao fim. */
  ciclo_mediano_horas: number | null;
  ciclo_amostra: number;
  /** Só dos que ainda correm — não é ciclo, é idade. */
  idade_mediana_horas: number | null;
  idade_amostra: number;
  motivo: string | null;
}

export interface CasoParado {
  id: string;
  cliente: string;
  categoria: string;
  estagio: string;
  estagio_titulo: string;
  dias: number | null;
  ultima_movimentacao: string | null;
  tom: Tom;
}

export interface MesDoMovimento {
  mes: string;
  rotulo: string;
  abertos: number;
  entrevistas: number;
  contratos_assinados: number;
  /** Mês incompleto: a coluna não é comparável com as anteriores. */
  parcial: boolean;
}

export interface PessoaDaEquipe {
  nome: string;
  informado: boolean;
  entrevistas: number;
  lidas: number;
  fatos_gerados: number;
  casos: number;
}

/** O caso como o panorama o lista — o bastante para abrir a lista de um estágio. */
export interface CasoDoPanorama {
  id: string;
  cliente: string;
  categoria: string;
  estagio: string;
  estagio_titulo: string;
  aberto_em: string | null;
  ultima_movimentacao: string | null;
  dias_sem_movimentacao: number | null;
  parado: boolean;
  instruido: boolean;
}

export interface Panorama {
  cobertura: {
    casos_no_acervo: number;
    casos_medidos: number;
    fora_da_leitura: number;
    motivo: string | null;
  };
  casos: CasoDoPanorama[];
  indicadores: IndicadorDoEscritorio[];
  funil: FaixaDoFunil[];
  tempo: { total_horas: number; etapas: EtapaDoEscritorio[]; base: string };
  categorias: CategoriaDoEscritorio[];
  parados: { total: number; mostrando: number; limiar_dias: number; itens: CasoParado[] };
  movimento: { meses: MesDoMovimento[]; base: string };
  equipe: { pessoas: PessoaDaEquipe[]; total_entrevistas: number; sem_atribuicao: number };
  qualidade: {
    entregas: number;
    aproveitadas: number;
    a_conferir: number;
    com_erro: number;
    em_leitura: number;
    percentual_aproveitado: number | null;
    legibilidade_media: number | null;
    legibilidade_amostra: number;
    base: string;
  };
  ausencias: { campo: string; motivo: string }[];
  gerado_em: string;
}

export async function buscarPanorama(): Promise<Panorama> {
  const resposta = await fetch(urlApi("/api/panorama"), {
    headers: cabecalhos(),
    credentials: CREDENCIAIS,
  });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe =
      corpo && typeof corpo === "object" && "detail" in corpo
        ? String((corpo as { detail: unknown }).detail)
        : `Erro ${resposta.status}`;
    throw new Error(detalhe);
  }
  return corpo as Panorama;
}
