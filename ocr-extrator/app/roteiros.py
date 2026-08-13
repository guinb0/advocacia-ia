"""Roteiros de entrevista — perguntas, tipo de resposta e roteamento.

Fiel ao documento "ENTREVISTA Empregado Público" da Lara & Melo.

O que decide se uma pergunta ganha o gravador é o campo `transcrever`, e o
critério é simples: transcreve-se o que o cliente **conta**, digita-se o que ele
**informa**.

    "Qual o seu CPF?"                          -> campo digitado
    "O que exatamente aconteceu?"              -> gravador

Transcrever um CPF seria pior que digitá-lo — o Whisper erra dígito, e ninguém
confere número lido de ouvido. Já o relato do acidente, ditado, sai melhor e
mais completo do que a atendente conseguiria resumir enquanto ouve.

O roteiro é ramificado: as 5 perguntas de rastreio do bloco inicial definem
quais módulos aparecem. Quem não sofreu assalto não vê o módulo de assalto.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

#: `escolha` vira fileira de botões; `lista`, um seletor. A diferença é o número
#: de opções: 27 UFs em botões viram uma parede, e 6 estados civis num seletor
#: escondem atrás de um clique o que cabe na tela.
TipoResposta = Literal["dado", "data", "sim_nao", "escolha", "lista", "documentos", "relato"]

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]

#: Documentos cujo dígito verificador a tela confere enquanto o campo é digitado.
#: Quem sabe que aquele campo é um CPF é o roteiro, não o componente — assim a
#: interface não precisa reconhecer perguntas pelo `id`.
Validacao = Literal["", "cpf"]

#: Campos que uma base pública preenche sozinha. O que existe e o que não existe
#: está discutido em `app/consultas.py` — resumo: CEP sim, CPF não.
Busca = Literal["", "cep"]


@dataclass
class Pergunta:
    id: str
    texto: str
    tipo: TipoResposta = "relato"
    #: Só as narrativas. Ver a explicação no topo do módulo.
    transcrever: bool = False
    opcoes: list[str] = field(default_factory=list)
    dica: str = ""
    obrigatoria: bool = False
    validacao: Validacao = ""
    busca: Busca = ""
    #: Id da pergunta que recebe o resultado da busca. Vazio = preenche a si.
    preenche: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Bloco:
    id: str
    titulo: str
    perguntas: list[Pergunta]
    #: `None` = sempre exibido. Caso contrário, só quando o rastreio deu positivo.
    modulo: str | None = None
    objetivo: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["perguntas"] = [p.to_dict() for p in self.perguntas]
        return d


@dataclass
class Roteiro:
    codigo: str
    nome: str
    descricao: str
    blocos: list[Bloco]

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "descricao": self.descricao,
            "blocos": [b.to_dict() for b in self.blocos],
        }


# --------------------------------------------------------------- blocos


IDENTIFICACAO = Bloco(
    id="identificacao",
    titulo="Identificação e qualificação",
    objetivo="Dados cadastrais do cliente. Tudo digitado — número ditado se perde.",
    perguntas=[
        Pergunta("nome", "Nome completo", "dado", obrigatoria=True),
        Pergunta("nacionalidade", "Nacionalidade", "dado"),
        Pergunta("nascimento", "Data de nascimento", "data"),
        # Escolha, não campo livre: estado civil digitado vira "casado",
        # "Casada", "casado(a)" e "amasiado" no mesmo escritório, e a
        # qualificação da petição precisa do termo certo. União estável entra na
        # lista porque muda dependente e pensão, ainda que juridicamente o
        # estado civil siga sendo outro.
        Pergunta(
            "estado_civil",
            "Estado civil",
            "escolha",
            opcoes=[
                "Solteiro(a)",
                "Casado(a)",
                "União estável",
                "Divorciado(a)",
                "Separado(a) judicialmente",
                "Viúvo(a)",
            ],
        ),
        Pergunta("profissao", "Profissão", "dado"),
        Pergunta("cpf", "CPF", "dado", obrigatoria=True, validacao="cpf"),
        # Três campos, não um: o contrato pede o número num lugar e o órgão
        # noutro ("portador(a) do RG nº ___, expedido por ___"). Perguntando
        # tudo junto, alguém teria de adivinhar onde termina o número — e o
        # palpite erraria em "12.345.678-9 SSP/PA" tanto quanto em "M-1234567".
        Pergunta("rg", "RG (número)", "dado"),
        Pergunta(
            "rg_orgao",
            "Órgão expedidor",
            "dado",
            dica="SSP, PC, DETRAN, IFP, Marinha, Exército…",
        ),
        Pergunta("rg_uf", "UF do RG", "lista", opcoes=UFS),
        Pergunta("mae", "Nome da mãe", "dado"),
        Pergunta("pai", "Nome do pai", "dado"),
        Pergunta(
            "cep",
            "CEP",
            "dado",
            busca="cep",
            preenche="endereco",
            dica="Digitado o CEP, o endereço vem sozinho — falta confirmar número e complemento.",
        ),
        Pergunta("endereco", "Endereço completo, com CEP", "dado"),
        Pergunta("telefone", "Telefone / WhatsApp", "dado", obrigatoria=True),
        Pergunta("email", "E-mail", "dado"),
        Pergunta("pis", "PIS / PASEP / NIT", "dado"),
    ],
)

VINCULO = Bloco(
    id="vinculo",
    titulo="Vínculo com os Correios",
    perguntas=[
        Pergunta("tempo_casa", "Há quanto tempo trabalha nos Correios?", "dado"),
        Pergunta(
            "funcao",
            "Função atual",
            "escolha",
            opcoes=[
                "Atendente", "OTT", "Carteiro motorizado", "Carteiro pedestre",
                "Carteiro motociclista", "Carteiro ciclista", "Outra",
            ],
        ),
        Pergunta(
            "desligamento",
            "Ainda trabalha na empresa? Se não, quando saiu e como foi o desligamento?",
            "relato",
            transcrever=True,
            dica="Demissão, pedido de demissão, acordo, aposentadoria…",
        ),
    ],
)

# As cinco perguntas que decidem o resto da entrevista.
RASTREIO = Bloco(
    id="rastreio",
    titulo="Rastreio inicial",
    objetivo="As respostas positivas abrem os módulos correspondentes.",
    perguntas=[
        Pergunta("r_assalto", "Foi vítima de assalto durante o trabalho?", "sim_nao", obrigatoria=True),
        Pergunta("r_acidente", "Sofreu algum acidente de trabalho?", "sim_nao", obrigatoria=True),
        Pergunta("r_doenca", "Desenvolveu alguma doença em razão do trabalho?", "sim_nao", obrigatoria=True),
        Pergunta(
            "r_sequela",
            "Sofreu acidente fora do trabalho que deixou sequela permanente?",
            "sim_nao",
            obrigatoria=True,
        ),
        Pergunta(
            "r_acao",
            "Já entrou com ação judicial contra os Correios sobre esses assuntos?",
            "sim_nao",
            obrigatoria=True,
        ),
        Pergunta("r_acao_quais", "Se sim, quais?", "relato", transcrever=True),
    ],
)

ASSALTO = Bloco(
    id="assalto",
    titulo="Módulo — Assalto",
    modulo="assalto",
    perguntas=[
        Pergunta(
            "as_ocorrencias",
            "Foi vítima de assalto nos últimos 5 anos? Quantas vezes e em que anos?",
            "relato",
            transcrever=True,
        ),
        Pergunta("as_funcao", "Qual era sua função na época?", "dado"),
        Pergunta("as_jornada", "O assalto ocorreu durante a jornada de trabalho?", "sim_nao"),
        Pergunta("as_cat", "Tem acesso às CATs?", "sim_nao"),
        Pergunta(
            "as_sintomas",
            "Após o assalto, passou a apresentar ansiedade, depressão, síndrome do pânico, "
            "estresse pós-traumático, insônia ou outro sintoma?",
            "relato",
            transcrever=True,
            dica="Se sim, perguntar se há laudos médicos relatando isso.",
        ),
        Pergunta("as_atendimento", "Procurou atendimento médico, psicológico ou psiquiátrico?", "sim_nao"),
        Pergunta("as_inss", "Ficou afastado pelo INSS em razão do assalto?", "sim_nao",
                 dica="Se sim, solicitar o processo do INSS e a senha gov.br."),
        Pergunta("as_ainda_trabalha", "Ainda trabalha na empresa?", "sim_nao"),
        Pergunta("as_acao", "Já ingressou com ação judicial relacionada a esse assalto?", "sim_nao"),
        Pergunta(
            "as_processo",
            "Se já entrou com ação: qual o número do processo? Quando? Já transitou em julgado? "
            "Já recebeu as indenizações?",
            "relato",
            transcrever=True,
            dica="ATENÇÃO: se ainda não recebeu, não é possível entrar com nova ação.",
        ),
        Pergunta("as_testemunhas", "Existem testemunhas que presenciaram o assalto?", "sim_nao"),
        Pergunta(
            "as_documentos",
            "Quais destes documentos possui?",
            "documentos",
            opcoes=[
                "Boletim de Ocorrência", "CAT", "Laudos médicos", "Relatórios psicológicos",
                "Relatórios psiquiátricos", "Receitas médicas", "Atestados", "Outros",
            ],
        ),
        Pergunta(
            "as_complemento",
            "Há mais alguma informação importante sobre o assalto que gostaria de contar?",
            "relato",
            transcrever=True,
        ),
    ],
)

ACIDENTE = Bloco(
    id="acidente",
    titulo="Módulo — Acidente de trabalho",
    modulo="acidente",
    perguntas=[
        Pergunta("ac_data", "Qual foi a data exata e o horário?", "dado"),
        Pergunta("ac_local", "Onde ocorreu?", "dado", dica="Dentro da empresa, no exercício do trabalho…"),
        Pergunta("ac_fazendo", "O que você estava fazendo no momento?", "relato", transcrever=True),
        Pergunta(
            "ac_como",
            "O que exatamente aconteceu? Descreva passo a passo.",
            "relato",
            transcrever=True,
            dica="A pergunta central do módulo — deixe o cliente contar sem interromper.",
        ),
        Pergunta("ac_testemunhas", "Havia colegas presentes? Quem?", "relato", transcrever=True,
                 dica="Anotar nomes e contatos."),
        Pergunta(
            "ac_comunicacao",
            "Houve comunicação imediata ao superior? Qual foi a reação da empresa?",
            "relato",
            transcrever=True,
        ),
        Pergunta("ac_cat", "Foi emitida a CAT?", "sim_nao"),
        Pergunta(
            "ac_cat_recusa",
            "Se não foi emitida: a empresa se recusou? Você comunicou por escrito?",
            "relato",
            transcrever=True,
        ),
        Pergunta("ac_hospital", "Foi levado ao médico/hospital pela empresa? Qual?", "dado"),
        Pergunta(
            "ac_atendimento",
            "Recebeu atendimento no mesmo dia? Ficou internado? Precisou de urgência?",
            "relato",
            transcrever=True,
            dica="Gesso, tala, soro, cirurgia…",
        ),
        Pergunta("ac_laudos", "Tem laudos e exames médicos do acidente?", "sim_nao"),
        Pergunta("ac_inss", "Foi afastado pelo INSS? Por quanto tempo?", "dado"),
        Pergunta("ac_nb", "Sabe qual foi o NB?", "escolha", opcoes=["NB 31", "NB 91", "NB 32", "Não sabe"],
                 dica="Se foi afastado, avisar que será preciso entrar no aplicativo do INSS."),
    ],
)

DOENCA = Bloco(
    id="doenca",
    titulo="Módulo — Doença ocupacional",
    modulo="doenca",
    perguntas=[
        Pergunta("do_inicio", "Quando percebeu os primeiros sintomas?", "relato", transcrever=True),
        Pergunta("do_atendimento", "Procurou atendimento assim que começaram os sintomas?", "sim_nao"),
        Pergunta("do_piora", "Os sintomas pioraram durante o trabalho ou após ele?", "relato", transcrever=True),
        Pergunta(
            "do_comunicou",
            "Comunicou à empresa que estava com dores ou limitações? Como foi a reação?",
            "relato",
            transcrever=True,
        ),
        Pergunta(
            "do_medico_trabalho",
            "A empresa encaminhou ao médico do trabalho? Ele reconheceu a relação com o trabalho?",
            "relato",
            transcrever=True,
        ),
        Pergunta("do_preexistente", "Já teve esse problema antes de trabalhar na empresa?", "sim_nao"),
        Pergunta(
            "do_agravou",
            "O trabalho agravou algum problema de saúde que já apresentava? De que forma?",
            "relato",
            transcrever=True,
        ),
        Pergunta("do_documentacao", "Possui documentação médica dessa doença?", "sim_nao"),
        Pergunta("do_cid", "Qual foi o diagnóstico? O CID foi relacionado ao trabalho?", "dado"),
    ],
)

HISTORICO = Bloco(
    id="historico",
    titulo="Histórico laboral e condições de trabalho",
    objetivo="Estabelecer o nexo entre as condições do trabalho e o dano sofrido.",
    perguntas=[
        Pergunta("hl_atividades", "Quais eram suas atividades no dia a dia?", "relato", transcrever=True),
        Pergunta("hl_tempo_funcao", "Há quanto tempo exerce essa função?", "dado"),
        Pergunta(
            "hl_epi",
            "A empresa fornecia EPI? Era obrigado a usar? Era fiscalizado? Quais usava?",
            "relato",
            transcrever=True,
        ),
        Pergunta(
            "hl_ambiente",
            "O ambiente tinha problemas estruturais, maquinário defeituoso ou sobrecarga?",
            "relato",
            transcrever=True,
        ),
        Pergunta(
            "hl_pressao",
            "Havia pressão excessiva, metas abusivas, assédio moral ou cobrança de metas?",
            "relato",
            transcrever=True,
        ),
    ],
)

SAUDE = Bloco(
    id="saude",
    titulo="Atendimento médico e afastamento",
    objetivo="Mapear o histórico de saúde para a instrução probatória.",
    perguntas=[
        Pergunta("sa_medicos", "Quais médicos e especialistas consultou?", "relato", transcrever=True,
                 dica="Especialidades e datas."),
        Pergunta("sa_exames", "Quais exames foram realizados?", "relato", transcrever=True,
                 dica="RX, ressonância, eletroneuromiografia…"),
        Pergunta("sa_laudos", "Tem laudos, prontuários e resultados de exames?", "sim_nao"),
        Pergunta("sa_diagnostico", "Qual foi o diagnóstico oficial (CID)?", "dado"),
        Pergunta("sa_tratamento", "Fez fisioterapia, cirurgia ou outro tratamento? Ainda faz?",
                 "relato", transcrever=True),
        Pergunta("sa_afastamento", "Foi afastado do trabalho? Quando e por quanto tempo?", "dado"),
        Pergunta("sa_especie", "Qual espécie de benefício?", "escolha",
                 opcoes=["B31 — comum", "B91 — acidentário", "Não sabe", "Não houve"]),
        Pergunta("sa_nexo", "Na perícia, o INSS reconheceu o nexo com o trabalho?", "sim_nao"),
        Pergunta(
            "sa_apos_alta",
            "O benefício foi cessado? Quando? Ainda apresenta dores ou sintomas após a alta? Quais?",
            "relato",
            transcrever=True,
        ),
    ],
)

SEQUELAS = Bloco(
    id="sequelas",
    titulo="Sequelas e impacto na capacidade laboral",
    modulo="sequela",
    objetivo="Dimensionar o dano para o pedido de auxílio-acidente.",
    perguntas=[
        Pergunta("se_quais", "Quais sequelas ficaram após o acidente ou a doença?", "relato", transcrever=True),
        Pergunta("se_limitacoes", "Há limitações de movimento ou função? Quais?", "relato", transcrever=True),
        Pergunta(
            "se_mesmo_trabalho",
            "Consegue fazer hoje o mesmo trabalho que fazia antes? Por que não?",
            "relato",
            transcrever=True,
        ),
        Pergunta("se_readaptado", "Precisou mudar de função ou foi readaptado?", "sim_nao"),
        Pergunta("se_permanente", "Ficou com limitação permanente reconhecida por médico?", "sim_nao"),
        Pergunta(
            "se_dia_a_dia",
            "Há dificuldade em atividades do dia a dia?",
            "relato",
            transcrever=True,
            dica="Dirigir, carregar peso, subir escadas, trabalhos domésticos.",
        ),
        Pergunta("se_dispositivo", "Usa algum dispositivo de auxílio?", "dado",
                 dica="Prótese, cadeira de rodas, bengala."),
        Pergunta("se_vida", "O problema afetou sua vida familiar e social? Como?", "relato", transcrever=True),
        Pergunta("se_medicacao", "Faz uso de medicação contínua? Qual o custo mensal?", "dado"),
    ],
)

ENCERRAMENTO = Bloco(
    id="encerramento",
    titulo="Encerramento",
    perguntas=[
        Pergunta(
            "en_colega_assalto",
            "Conhece colega que foi vítima de assalto durante o trabalho?",
            "relato",
            transcrever=True,
            dica="Se sim, pedir nome e telefone. Informar que a análise jurídica é gratuita.",
        ),
        Pergunta(
            "en_colega_acidente",
            "Conhece colega que sofreu acidente de trabalho ou fora dele?",
            "relato",
            transcrever=True,
            dica="Se sim, pedir nome e telefone.",
        ),
        Pergunta(
            "en_experiencia",
            "Como foi sua experiência durante este atendimento?",
            "relato",
            transcrever=True,
        ),
    ],
)


EMPREGADO_PUBLICO = Roteiro(
    codigo="empregado_publico",
    nome="Empregado Público (Correios)",
    descricao=(
        "Roteiro de acolhimento da Lara & Melo para empregado dos Correios. "
        "As cinco perguntas de rastreio definem quais módulos são percorridos."
    ),
    blocos=[
        IDENTIFICACAO, VINCULO, RASTREIO,
        ASSALTO, ACIDENTE, DOENCA,
        HISTORICO, SAUDE, SEQUELAS,
        ENCERRAMENTO,
    ],
)

ROTEIROS: dict[str, Roteiro] = {EMPREGADO_PUBLICO.codigo: EMPREGADO_PUBLICO}

#: Rastreio positivo -> módulos que passam a ser exibidos.
MAPA_RASTREIO = {
    "r_assalto": "assalto",
    "r_acidente": "acidente",
    "r_doenca": "doenca",
    "r_sequela": "sequela",
}


def listar() -> list[Roteiro]:
    return list(ROTEIROS.values())


def obter(codigo: str) -> Roteiro | None:
    return ROTEIROS.get(codigo)


def perguntas_transcritas(codigo: str) -> list[str]:
    """Ids das perguntas que abrem o gravador. Útil para conferência e testes."""
    roteiro = obter(codigo)
    if roteiro is None:
        return []
    return [p.id for b in roteiro.blocos for p in b.perguntas if p.transcrever]
