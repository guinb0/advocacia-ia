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

import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

log = logging.getLogger(__name__)

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
    #: Texto que a atendente LÊ EM VOZ ALTA, palavra por palavra, quando esta
    #: resposta cai num certo valor. É diferente de `dica`, que é orientação
    #: interna e nunca é lida ao cliente.
    #:
    #: Chave "sim"/"não" para as de rastreio; "*" para qualquer resposta. Vem do
    #: roteiro do escritório — ver `docs/ENTREVISTA*.docx`.
    fala: dict[str, str] = field(default_factory=dict)
    #: Esta pergunta só existe quando OUTRA foi respondida de certo jeito.
    #:
    #: O roteiro do escritório escreve a condição no próprio enunciado — "Se já
    #: entrou com ação: qual o número do processo?" — e o sistema a ignorava: a
    #: pergunta ficava pendente para sempre em quem respondeu "não", e o painel
    #: mandava perguntar de novo algo que já tinha sido respondido.
    #:
    #: Sem o pai respondido, a pergunta fica FECHADA: o enunciado pressupõe a
    #: resposta anterior, e lê-lo antes dela confunde o cliente.
    depende_de: str = ""
    #: O valor do pai que ABRE esta pergunta. Nem sempre é "sim": a CAT tem uma
    #: pergunta que só faz sentido quando ela NÃO foi emitida.
    depende_valor: str = ""
    #: Resposta que IMPEDE o prosseguimento, com o motivo. O roteiro tem um caso:
    #: quem já ganhou ação sobre o mesmo fato e ainda não recebeu não pode entrar
    #: com outra. Ver `ALERTAS` no fim do módulo.
    impedimento: str = ""

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
    #: Lido em voz alta ao ENTRAR no bloco. O roteiro do escritório abre vários
    #: blocos com uma transição ("Agora vou lhe fazer algumas perguntas sobre…"),
    #: e o escritório pediu que ele fosse seguido estritamente.
    abertura: str = ""
    #: Instrução de conduta para a atendente. NÃO é lida ao cliente.
    instrucao: str = ""
    #: O bloco sai da entrevista e passa para outra equipe. Hoje só a
    #: qualificação: o roteiro reserva um Departamento de Documentação para ela.
    delegado_a: str = ""

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
    #: Os parágrafos de abertura, na ordem, lidos antes da primeira pergunta.
    saudacao: list[str] = field(default_factory=list)
    #: Os de encerramento, depois da última.
    encerramento: list[str] = field(default_factory=list)
    #: O que LER quando o cliente sai do assunto, da mais gentil à mais firme.
    #: Ver `RETOMADAS`.
    retomadas: list[str] = field(default_factory=list)
    #: Complemento da retomada conforme o tipo da resposta. Ver `FECHOS_POR_TIPO`.
    fechos_por_tipo: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "descricao": self.descricao,
            "saudacao": self.saudacao,
            "encerramento": self.encerramento,
            "retomadas": self.retomadas,
            "fechos_por_tipo": self.fechos_por_tipo,
            "blocos": [b.to_dict() for b in self.blocos],
        }


# --------------------------------------------------------------- blocos


# A entrevista abre com cinco campos de localização e identificação.
#
# O escritório tirou a qualificação do começo: perguntar nacionalidade, filiação
# e órgão expedidor antes de ouvir a história é o que fazia a conversa começar
# como um formulário. Nome, CPF e estado civil identificam o atendimento; UF e
# município definem desde o início onde o caso será tratado e evitam voltar ao cliente.
#
# Os cinco são digitados. A escuta automática pode SUGERI-los a partir da fala,
# nunca preenchê-los sozinha — ver `app/escuta.py`.
ABERTURA = Bloco(
    id="abertura",
    titulo="Identificação",
    objetivo="Dados mínimos do atendimento, sempre editáveis pela equipe.",
    perguntas=[
        # CPF primeiro: é o que abre a consulta à base (DirectD) e traz o resto
        # preenchido. Digitar o CPF antes do nome economiza datilografia — nome,
        # nascimento, mãe, endereço, telefone e e-mail vêm da fonte.
        Pergunta("cpf", "CPF", "dado", obrigatoria=True, validacao="cpf"),
        Pergunta("nome", "Nome completo", "dado", obrigatoria=True),
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
            obrigatoria=True,
        ),
        Pergunta("uf", "UF onde reside", "lista", opcoes=UFS, obrigatoria=True),
        Pergunta("municipio", "Município onde reside", "dado", obrigatoria=True),
        # Puxados pela consulta por CPF (DirectD) e editáveis à mão. Ficam aqui,
        # e não no bloco "Qualificação completa" (delegado à documentação), para
        # aparecerem já na identificação: quem digita o CPF confere na hora o que
        # a base devolveu, em vez de descobrir depois que veio escondido.
        # Texto, não "data": a consulta e o contrato usam dd/mm/aaaa, e um
        # <input type="date"> só aceita aaaa-mm-dd — a data puxada não apareceria.
        Pergunta("nascimento", "Data de nascimento", "dado", dica="dd/mm/aaaa"),
        Pergunta("sexo", "Sexo", "dado"),
        Pergunta("mae", "Nome da mãe", "dado"),
        # O CEP puxa endereço, município e UF de uma vez. Vem preenchido pela
        # consulta por CPF (a base devolve o CEP) e também aceita digitação: é o
        # caminho de preencher o município quando o cadastro não o trouxe pronto.
        Pergunta(
            "cep",
            "CEP",
            "dado",
            busca="cep",
            preenche="endereco",
            dica="Digitado o CEP, endereço, município e UF vêm sozinhos — falta o número.",
        ),
        Pergunta("endereco", "Endereço completo, com CEP", "dado"),
        Pergunta("telefone", "Telefone / WhatsApp", "dado"),
        Pergunta("email", "E-mail", "dado"),
        Pergunta(
            "renda_estimada",
            "Renda estimada",
            "dado",
            dica="Estimativa da base de dados por CPF — confirmar com o cliente.",
        ),
    ],
)


IDENTIFICACAO = Bloco(
    id="identificacao",
    titulo="Qualificação completa",
    objetivo="Dados cadastrais do cliente. Tudo digitado — número ditado se perde.",
    perguntas=[
        Pergunta("nacionalidade", "Nacionalidade", "dado"),
        Pergunta("nascimento", "Data de nascimento", "data"),
        # Preenchidos pela consulta por CPF (DirectD); editáveis à mão.
        Pergunta("sexo", "Sexo", "dado"),
        Pergunta(
            "renda_estimada",
            "Renda estimada",
            "dado",
            dica="Estimativa da base de dados por CPF — confirmar com o cliente.",
        ),
        Pergunta("profissao", "Profissão", "dado"),
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
            dica=(
                "Se sim: descobrir se já transitou em julgado e se JÁ RECEBEU. "
                "Não tendo recebido, não é possível entrar com nova ação."
            ),
        ),
        Pergunta(
            "r_acao_quais",
            "Qual ação foi ajuizada, qual é o número do processo, já transitou em julgado e já recebeu os valores?",
            "relato",
            transcrever=True,
            depende_de="r_acao",
            depende_valor="sim",
            dica="Registrar separadamente o assunto, o processo, o trânsito em julgado e o recebimento.",
        ),
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
            depende_de="as_acao",
            depende_valor="sim",
            dica="ATENÇÃO: se ainda não recebeu, não é possível entrar com nova ação.",
        ),
        # O único impedimento explícito do roteiro (§62 do .docx, em caixa alta):
        # "SE AINDA NÃO RECEBEU, NÃO É POSSÍVEL ENTRAR". Fica como pergunta
        # própria, e não como dica, porque a resposta precisa ser registrada — é
        # ela que decide se o atendimento segue para contrato ou para.
        Pergunta(
            "as_recebeu",
            "Já recebeu as indenizações dessa ação anterior?",
            "sim_nao",
            depende_de="as_acao",
            depende_valor="sim",
            impedimento="não",
            dica=(
                "Se NÃO recebeu: não é possível entrar com nova ação sobre o mesmo "
                "fato. Informar o cliente e não seguir para o contrato."
            ),
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
            # A única que abre no "não": não há recusa a apurar se a CAT saiu.
            depende_de="ac_cat",
            depende_valor="não",
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


# ------------------------------------------------- abertura e encerramento
#
# Transcritos de `ENTREVISTA Empregado Publico Atualizada 11082026.docx`,
# parágrafo por parágrafo, sem reescrita.
#
# Por que copiado e não resumido: é o que a atendente LÊ ao cliente. O texto
# promete sigilo, explica a finalidade do tratamento dos dados e diz o que será
# feito com eles — resumir isso é alterar o que o escritório declara a quem está
# do outro lado. `[Nome]` e `[Nome da Atendente]` continuam entre colchetes pelo
# mesmo motivo do contrato: lacuna visível não passa despercebida.

SAUDACAO = [
    "Bom dia/boa tarde, Sr.(a) [Nome]. Tudo bem? Seja muito bem-vindo(a).",
    "Meu nome é [Nome da Atendente] e faço parte da equipe de acolhimento ao "
    "cliente da Lara & Melo Advogados Associados.",
    "Antes de iniciarmos, gostaríamos de agradecer pela confiança depositada em "
    "nosso escritório.",
    "A Lara & Melo Advogados Associados atua em todo o território nacional e é "
    "especializada na defesa dos direitos dos trabalhadores, com forte atuação nas "
    "ações envolvendo acidentes do trabalho, doenças ocupacionais, assaltos "
    "sofridos durante a atividade profissional e benefícios previdenciários, como "
    "o auxílio-acidente.",
    "Esta entrevista integra o nosso protocolo interno de atendimento e tem como "
    "finalidade compreender, de forma detalhada, toda a sua história. Nosso "
    "objetivo é identificar todos os direitos que o(a) senhor(a) eventualmente "
    "possa possuir e fornecer à nossa equipe jurídica todas as informações "
    "necessárias para uma análise técnica completa e personalizada.",
    "Por esse motivo, durante nossa conversa, farei algumas perguntas bastante "
    "específicas. Elas são essenciais para que nenhuma informação relevante deixe "
    "de ser considerada pela equipe jurídica.",
    "Fique tranquilo(a), pois esta conversa é totalmente sigilosa e costuma durar "
    "entre 20 e 30 minutos, dependendo da complexidade do caso.",
    "Ao final da entrevista, todas as informações serão encaminhadas para análise "
    "da equipe jurídica LARA & MELO ADVOGADOS ASSOCIADOS, que avaliarão "
    "cuidadosamente a viabilidade das medidas cabíveis e, se necessário, entrarão "
    "em contato para solicitar alguma informação complementar.",
    "Se, durante a entrevista, surgir qualquer dúvida, fique à vontade para me "
    "interromper. Será um prazer esclarecer tudo o que for necessário.",
    "Podemos começar?",
]

FECHAMENTO = [
    "Sr.(a) [Nome], concluímos a nossa entrevista. Primeiramente gostaria de "
    "agradecer, em nome do Dr. Gustavo Lara e de toda a equipe da Lara & Melo "
    "Advogados Associados, pela confiança em compartilhar conosco a sua história.",
    "Pode ter certeza de que todas as informações prestadas hoje serão analisadas "
    "com muita atenção.",
    "Antes de encerrarmos, posso lhe fazer apenas uma última pergunta?",
    "Como foi a sua experiência durante este atendimento? O(a) senhor(a) gostou da "
    "forma como foi atendido(a)? Existe alguma sugestão ou algo que poderíamos "
    "melhorar?",
    "(Aguardar a resposta do cliente.)",
    "Fico muito feliz em ouvir isso. Trabalhamos diariamente para oferecer um "
    "atendimento de excelência para todos os trabalhadores que confiam no nosso "
    "escritório.",
    "Se o(a) senhor(a) permitir, gostaria de lhe encaminhar um link de avaliação. "
    "A sua opinião é extremamente importante para nós, pois nos ajuda a "
    "aperfeiçoar continuamente nossos atendimentos e também auxilia outras pessoas "
    "a conhecerem o trabalho desenvolvido pela nossa equipe.",
    "Posso lhe enviar esse link agora?",
    "(Se o cliente responder “sim”:) Perfeito! Acabei de encaminhar o link.",
    "Se o atendimento correspondeu às suas expectativas e o(a) senhor(a) acredita "
    "que fiz um bom trabalho, peço, por gentileza, que nos avalie com cinco "
    "estrelas. Essa avaliação é muito importante para o nosso escritório e também "
    "para mim, pois ela faz parte da avaliação do meu desempenho profissional e "
    "contribui para o meu crescimento dentro da equipe.",
    "Se o(a) senhor(a) se sentir à vontade, ficaremos muito felizes se puder "
    "deixar também um breve comentário relatando como foi a sua experiência "
    "durante esta entrevista. Seu depoimento é muito valioso para nós.",
    "Se não houver problema, peço apenas que realize a avaliação agora. Eu "
    "permanecerei na videoconferência aguardando para confirmar que deu tudo certo "
    "e, caso tenha qualquer dificuldade durante o preenchimento, terei o maior "
    "prazer em ajudá-lo(a).",
    "(Aguardar a conclusão da avaliação.)",
    "Muito obrigada pela sua avaliação e, principalmente, pela confiança "
    "depositada em nossa Equipe.",
    "Sr.(a) [Nome], concluímos a nossa entrevista e, a partir de agora, o seu "
    "atendimento passará a ser acompanhado pelo Departamento de Documentação da "
    "Lara & Melo Advogados Associados.",
    "A responsável pelo seu atendimento, Cristielen, dará continuidade ao "
    "acompanhamento e alinhará com o(a) senhor(a), ainda nesta mesma "
    "videoconferência, toda a documentação necessária para darmos prosseguimento "
    "ao seu atendimento.",
    "Ela irá explicar detalhadamente quais documentos serão necessários, como "
    "deverão ser encaminhados e esclarecerá qualquer dúvida que o(a) senhor(a) "
    "possa ter.",
    "Fique tranquilo(a), pois estaremos acompanhando cada etapa e permanecemos à "
    "disposição para auxiliá-lo(a) no que for necessário.",
    "Foi um prazer atendê-lo. Em nome da Lara & Melo Advogados Associados, desejo "
    "um ótimo dia.",
]


# ------------------------------------------------------------- retomadas
#
# O que a atendente LÊ quando o cliente sai do assunto — e sai, sempre: fala do
# filho, da vizinha, da cirurgia que não é a do processo. Sem uma frase pronta na
# tela, cortar um cliente que está desabafando é constrangedor, e o resultado é
# que ninguém corta: a entrevista de 20 minutos vira uma de 50 e as perguntas do
# fim ficam sem resposta.
#
# O texto não foi inventado aqui. Ele se apoia no que a saudação JÁ prometeu ao
# cliente, palavra por palavra:
#
#   "durante nossa conversa, farei algumas perguntas bastante específicas"
#   "Elas são essenciais para que nenhuma informação relevante deixe de ser
#    considerada pela equipe jurídica"
#   "costuma durar entre 20 e 30 minutos"
#
# Cortar lembrando o que foi combinado no início não é grosseria — é o combinado.
# Por isso cada retomada devolve o cliente ao que ele mesmo ouviu e aceitou.
#
# A ORDEM É DE FIRMEZA, e é assim que a tela as usa: a primeira aos dez
# segundos, e a seguinte a cada vez que ele continua sem responder. É como um
# entrevistador experiente faz — não se sobe o tom de uma vez, e não se fica
# repetindo a mesma frase gentil enquanto a entrevista escorre.
#
# Todas terminam em dois-pontos: quem lê emenda com a pergunta, que está logo
# abaixo na barra de condução, em corpo grande.
RETOMADAS = [
    "Sr.(a), me perdoe interromper. Como eu comentei no início, farei algumas "
    "perguntas bastante específicas — e ainda preciso desta:",
    "Esse ponto eu anotei, pode ficar tranquilo(a). Mas preciso fechar esta "
    "pergunta antes de seguir, senão a equipe jurídica fica sem ela:",
    "Sr.(a), nossa conversa costuma durar de 20 a 30 minutos e ainda temos "
    "algumas perguntas pela frente. Vou pedir que me responda especificamente esta:",
    "Vamos guardar esse assunto para o final do atendimento — está anotado aqui "
    "comigo. Agora eu preciso da resposta desta pergunta para poder seguir:",
]

#: Fecho da retomada conforme o que a pergunta espera. Dito depois do enunciado,
#: encurta a resposta de quem se perde porque não sabe o tamanho do que foi
#: perguntado — o cliente que ouve "basta sim ou não" responde em dois segundos.
#: Sem entrada para `relato`: ali o que se quer é justamente que ele conte.
FECHOS_POR_TIPO = {
    "sim_nao": "Aqui basta o(a) senhor(a) me dizer sim ou não.",
    "escolha": "Posso ler as opções, se ajudar — é só escolher uma.",
    "lista": "Posso ler as opções, se ajudar — é só escolher uma.",
    "documentos": "Só preciso saber quais desses o(a) senhor(a) tem em mãos.",
    "dado": "É só esse dado mesmo, bem rapidinho.",
    "data": "Se não lembrar a data exata, o mês e o ano já me ajudam.",
}


EMPREGADO_PUBLICO = Roteiro(
    codigo="empregado_publico",
    nome="Empregado Público (Correios)",
    descricao=(
        "Roteiro de acolhimento da Lara & Melo para empregado dos Correios. "
        "As cinco perguntas de rastreio definem quais módulos são percorridos."
    ),
    saudacao=SAUDACAO,
    encerramento=FECHAMENTO,
    retomadas=RETOMADAS,
    fechos_por_tipo=FECHOS_POR_TIPO,
    # A qualificação cadastral completa pertence à etapa de documentação, não ao
    # roteiro da conversa. Somente a identificação mínima permanece aqui.
    blocos=[
        ABERTURA, VINCULO, RASTREIO,
        ASSALTO, ACIDENTE, DOENCA,
        HISTORICO, SAUDE, SEQUELAS,
        ENCERRAMENTO,
    ],
)

ROTEIROS: dict[str, Roteiro] = {EMPREGADO_PUBLICO.codigo: EMPREGADO_PUBLICO}

#: Códigos que continuam existindo, mas não aparecem no catálogo da tela.
#:
#: O escritório parou de atender pelo roteiro dos Correios e não quer mais vê-lo
#: na lista. Ocultar em vez de apagar é deliberado: `ROTEIROS` é a única fonte
#: embutida, e remover a entrada faria `obter()` devolver `None` para todo mundo
#: que ainda chamasse por este código — relatório antigo, auditoria, escuta.
#: Aqui ele some da vitrine e continua resolvendo para quem pedir pelo nome.
OCULTOS_NO_CATALOGO = {"empregado_publico"}

#: Roteiro assumido quando quem chama não informa qual usar.
#:
#: ATENÇÃO: este código vive no BANCO (foi importado), não neste módulo. Com o
#: Postgres fora do ar `obter()` devolve `None` e quem dependia do padrão recebe
#: erro — comportamento diferente do antigo `empregado_publico`, que era
#: embutido e funcionava offline. Foi uma escolha explícita do escritório.
ROTEIRO_PADRAO = "auxilio_acidente"

#: Rastreio positivo -> módulos que passam a ser exibidos.
MAPA_RASTREIO = {
    "r_assalto": "assalto",
    "r_acidente": "acidente",
    "r_doenca": "doenca",
    "r_sequela": "sequela",
}


def _palavras(texto: str) -> list[str]:
    limpo = unicodedata.normalize("NFKD", str(texto or "").lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", limpo)


def mapa_rastreio(roteiro: Roteiro) -> dict[str, str]:
    modulos = list(dict.fromkeys(bloco.modulo for bloco in roteiro.blocos if bloco.modulo))
    if not modulos:
        return {}
    candidatas = [
        pergunta
        for bloco in roteiro.blocos
        if not bloco.modulo
        for pergunta in bloco.perguntas
        if pergunta.tipo == "sim_nao"
    ]
    ids = {pergunta.id for pergunta in candidatas}
    mapa = {pid: modulo for pid, modulo in MAPA_RASTREIO.items() if pid in ids and modulo in modulos}
    for modulo in modulos:
        if modulo in mapa.values():
            continue
        raizes = [palavra[:5] for palavra in _palavras(modulo.replace("_", " ")) if len(palavra) > 2]
        if not raizes:
            continue
        melhor, melhor_pontos = None, 0
        for pergunta in candidatas:
            if pergunta.id in mapa:
                continue
            palavras = {p[:5] for p in _palavras(pergunta.id.replace("_", " ") + " " + pergunta.texto)}
            if raizes[0] not in palavras:
                continue
            pontos = sum(1 for raiz in raizes if raiz in palavras) + (10 if pergunta.id == modulo else 0)
            if pontos > melhor_pontos:
                melhor, melhor_pontos = pergunta, pontos
        if melhor is not None:
            mapa[melhor.id] = modulo
    return mapa


def impedimentos(codigo: str, respostas: dict[str, Any]) -> list[dict[str, str]]:
    """As respostas que barram o prosseguimento, com o motivo.

    Hoje há um caso, e ele vem em caixa alta no roteiro do escritório: quem já
    tem ação sobre o mesmo fato e AINDA NÃO RECEBEU não pode entrar com outra.

    Isto é consultado antes de oferecer o contrato. Não é conselho jurídico
    automatizado — é o próprio roteiro, escrito pelo escritório, aplicado onde
    ele mandou aplicar. Quem decide continua sendo o advogado; o sistema só
    deixa de esconder a regra no meio de 86 perguntas.
    """
    roteiro = obter(codigo)
    if roteiro is None:
        return []

    def igual(a: str, b: str) -> bool:
        """"não" e "nao" são a mesma resposta.

        A tela grava com acento (os botões são "sim"/"não"), mas a escuta
        automática e o preenchimento por API podem chegar sem. Uma regra que
        barra o ajuizamento não pode depender de cedilha.
        """
        def limpar(s: str) -> str:
            s = unicodedata.normalize("NFKD", s.strip().lower())
            return s.encode("ascii", "ignore").decode()

        return limpar(a) == limpar(b)

    achados = []
    for bloco in roteiro.blocos:
        for pergunta in bloco.perguntas:
            if not pergunta.impedimento:
                continue
            valor = str(respostas.get(pergunta.id, "")).strip().lower()
            if valor and igual(valor, pergunta.impedimento):
                achados.append(
                    {
                        "pergunta_id": pergunta.id,
                        "pergunta": pergunta.texto,
                        "resposta": valor,
                        "motivo": pergunta.dica,
                    }
                )
    return achados


def listar() -> list[Roteiro]:
    """Os roteiros escritos em código e os importados de documento, nesta ordem.

    O do escritório vem primeiro porque é o que se usa todo dia; os importados
    aparecem depois, na ordem em que foram salvos.
    """
    catalogo = dict(ROTEIROS)
    catalogo.update(_importados())
    return list(catalogo.values())


def obter(codigo: str) -> Roteiro | None:
    """A versão salva tem precedência sobre a escrita em código.

    É o que faz o botão "Editar roteiro" valer para `empregado_publico` também: a
    edição vira uma linha no banco com o mesmo código, e essa linha passa a ser o
    roteiro. Apagá-la devolve o roteiro do módulo — o escritório nunca fica sem
    saída se uma edição sair errada.
    """
    salvo, registro = _importado_por_codigo(codigo)
    embutido = ROTEIROS.get(codigo)

    if salvo is not None and embutido is not None:
        # A ARMADILHA QUE ISTO FECHA, E ELA JA MORDEU.
        #
        # A precedencia acima vale para roteiro que so existe no banco. Quando o
        # MESMO codigo tambem existe em `ROTEIROS`, a copia salva passava a
        # esconder o modulo para sempre: alguem editava `roteiros.py`, subia, e
        # nada acontecia -- sem aviso, sem log, sem sintoma.
        #
        # Aconteceu com o `empregado_publico`: o campo `estado_civil` entrou no
        # bloco de abertura pelo codigo, o frontend passou a exigi-lo para
        # comecar a entrevista, e a tela servia a versao salva, que nao o tinha.
        # A entrevista travou num campo que ela cobrava e nao mostrava. So deu
        # para achar porque a contradicao paralisou a tela; um enunciado
        # reescrito teria passado semanas sem ninguem notar.
        #
        # Agora quem chegou por ultimo vence. O modulo carrega a data do arquivo
        # em `_VERSAO_MODULO`: deploy novo tem carimbo novo, e uma edicao feita
        # DEPOIS do deploy continua valendo, que e o que o botao "Editar
        # roteiro" promete.
        if _VERSAO_MODULO > str((registro or {}).get("atualizado_em") or ""):
            log.info(
                "Roteiro '%s' foi alterado no codigo depois da edicao salva; "
                "o do modulo passa a valer. Apague a linha do catalogo para "
                "silenciar este aviso.",
                codigo,
            )
            return embutido
        return salvo

    if salvo is not None:
        return salvo
    return embutido


def perguntas_transcritas(codigo: str) -> list[str]:
    """Ids das perguntas que abrem o gravador. Útil para conferência e testes."""
    roteiro = obter(codigo)
    if roteiro is None:
        return []
    return [p.id for b in roteiro.blocos for p in b.perguntas if p.transcrever]


# ------------------------------------------------- roteiros vindos de fora
#
# Até aqui o módulo é uma transcrição do documento do escritório, em código. O
# que segue existe porque cada categoria de causa tem o seu documento, e
# transcrever 86 perguntas à mão não escala: `app/roteiro_ia.py` lê o arquivo e
# devolve o mesmo formato em dicionário, que estas funções validam e convertem.
#
# A validação é aqui, e não no `roteiro_ia`, porque o editor da tela salva pelo
# mesmo caminho. Um roteiro escrito por um advogado às onze da noite merece a
# mesma conferência que um escrito pelo modelo.

#: Os tipos que a tela sabe desenhar. Um tipo fora desta lista viraria um campo
#: que o `CampoResposta` não renderiza — pergunta invisível no meio da entrevista.
TIPOS_RESPOSTA: tuple[str, ...] = (
    "dado", "data", "sim_nao", "escolha", "lista", "documentos", "relato",
)

VALIDACOES: tuple[str, ...] = ("", "cpf")
BUSCAS: tuple[str, ...] = ("", "cep")


class RoteiroInvalido(ValueError):
    """Roteiro que a tela não conseguiria exibir, com o motivo em português."""


def identificador(bruto: Any, usados: set[str], prefixo: str) -> str:
    """Um id estável, em ascii, garantidamente único dentro de `usados`.

    Ids saem de duas fontes pouco confiáveis — o modelo e o campo de texto do
    editor — e são a chave das respostas: dois iguais fariam a segunda pergunta
    sobrescrever a resposta da primeira, silenciosamente.
    """
    texto = unicodedata.normalize("NFKD", str(bruto or "").strip().lower())
    limpo = texto.encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-z0-9]+", "_", limpo).strip("_")[:48]
    base = limpo or prefixo

    candidato = base
    sufixo = 2
    while candidato in usados:
        candidato = f"{base}_{sufixo}"
        sufixo += 1
    usados.add(candidato)
    return candidato


def de_dict(dados: Any) -> Roteiro:
    """Reconstrói o roteiro a partir do JSON, ou explica o que está errado."""
    if not isinstance(dados, dict):
        raise RoteiroInvalido("O roteiro precisa ser um objeto JSON.")

    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise RoteiroInvalido("O roteiro precisa de um nome.")

    codigo_bruto = str(dados.get("codigo") or "").strip()
    codigo = identificador(codigo_bruto or nome, set(), "roteiro")

    brutos = dados.get("blocos")
    if not isinstance(brutos, list) or not brutos:
        raise RoteiroInvalido("O roteiro precisa de pelo menos um bloco.")

    usados: set[str] = set()
    blocos = [_bloco_de_dict(bruto, usados) for bruto in brutos]
    if not any(bloco.perguntas for bloco in blocos):
        raise RoteiroInvalido("O roteiro precisa de pelo menos uma pergunta.")

    blocos = _garantir_identificacao(blocos)
    _soltar_dependencias_orfas(blocos)

    return Roteiro(
        codigo=codigo,
        nome=nome[:200],
        descricao=str(dados.get("descricao") or "").strip()[:1000],
        blocos=blocos,
        saudacao=_lista_de_texto(dados.get("saudacao")),
        encerramento=_lista_de_texto(dados.get("encerramento")),
        retomadas=_lista_de_texto(dados.get("retomadas")),
        fechos_por_tipo=_mapa_de_texto(dados.get("fechos_por_tipo")),
    )


_TEXTOS_EQUIVALENTES_IDENTIFICACAO = {"endereco residencial completo incluindo cep"}


def _garantir_identificacao(blocos: list[Bloco]) -> list[Bloco]:
    ids_fixos = {pergunta.id for pergunta in ABERTURA.perguntas}
    textos_fixos = {" ".join(_palavras(p.texto)) for p in ABERTURA.perguntas} | _TEXTOS_EQUIVALENTES_IDENTIFICACAO
    abertura = next((bloco for bloco in blocos if bloco.id == ABERTURA.id), None)
    for bloco in blocos:
        if bloco is not abertura:
            bloco.perguntas = [
                p
                for p in bloco.perguntas
                if p.id not in ids_fixos and " ".join(_palavras(p.texto)) not in textos_fixos
            ]
    restantes = [bloco for bloco in blocos if bloco is not abertura and bloco.perguntas]
    if abertura is None:
        abertura = replace(ABERTURA, perguntas=[replace(p) for p in ABERTURA.perguntas])
    else:
        existentes = {p.id for p in abertura.perguntas}
        faltando = [replace(p) for p in ABERTURA.perguntas if p.id not in existentes]
        abertura.perguntas = faltando + abertura.perguntas
    return [abertura, *restantes]


def snapshot_ativo(codigo: str, dados: Any | None) -> Roteiro | None:
    """Valida a versão enviada pela tela e confere a identidade do roteiro."""
    if dados is None:
        return None
    atual = de_dict(dados)
    if atual.codigo != codigo:
        raise RoteiroInvalido(
            "O código do roteiro ativo não corresponde ao snapshot enviado."
        )
    return atual


def _bloco_de_dict(dados: Any, usados: set[str]) -> Bloco:
    if not isinstance(dados, dict):
        raise RoteiroInvalido("Cada bloco precisa ser um objeto JSON.")

    titulo = str(dados.get("titulo") or "").strip()
    if not titulo:
        raise RoteiroInvalido("Todo bloco precisa de um título.")

    modulo = str(dados.get("modulo") or "").strip() or None
    perguntas_brutas = dados.get("perguntas")
    perguntas = (
        [_pergunta_de_dict(p, usados) for p in perguntas_brutas]
        if isinstance(perguntas_brutas, list)
        else []
    )
    return Bloco(
        id=identificador(dados.get("id") or titulo, usados, "bloco"),
        titulo=titulo[:200],
        perguntas=perguntas,
        modulo=modulo,
        objetivo=str(dados.get("objetivo") or "").strip()[:1000],
        abertura=str(dados.get("abertura") or "").strip()[:2000],
        instrucao=str(dados.get("instrucao") or "").strip()[:2000],
        delegado_a=str(dados.get("delegado_a") or "").strip()[:120],
    )


def _pergunta_de_dict(dados: Any, usados: set[str]) -> Pergunta:
    if not isinstance(dados, dict):
        raise RoteiroInvalido("Cada pergunta precisa ser um objeto JSON.")

    texto = str(dados.get("texto") or "").strip()
    if not texto:
        raise RoteiroInvalido("Toda pergunta precisa de um enunciado.")

    tipo = str(dados.get("tipo") or "relato").strip()
    if tipo not in TIPOS_RESPOSTA:
        raise RoteiroInvalido(
            f"Tipo de resposta '{tipo}' não existe. Use um destes: "
            f"{', '.join(TIPOS_RESPOSTA)}."
        )

    opcoes = dados.get("opcoes")
    opcoes = (
        [str(o).strip()[:120] for o in opcoes if str(o).strip()]
        if isinstance(opcoes, list)
        else []
    )
    if tipo in {"escolha", "lista"} and not opcoes:
        raise RoteiroInvalido(
            f"A pergunta “{texto[:60]}” é de {tipo} e não tem nenhuma opção."
        )

    validacao = str(dados.get("validacao") or "").strip()
    if validacao not in VALIDACOES:
        validacao = ""
    busca = str(dados.get("busca") or "").strip()
    if busca not in BUSCAS:
        busca = ""

    return Pergunta(
        id=identificador(dados.get("id") or texto, usados, "p"),
        texto=texto[:500],
        tipo=tipo,  # type: ignore[arg-type]
        transcrever=bool(dados.get("transcrever")),
        opcoes=opcoes[:60],
        dica=str(dados.get("dica") or "").strip()[:500],
        obrigatoria=bool(dados.get("obrigatoria")),
        validacao=validacao,  # type: ignore[arg-type]
        busca=busca,  # type: ignore[arg-type]
        preenche=str(dados.get("preenche") or "").strip()[:60],
        fala=_mapa_de_texto(dados.get("fala")),
        depende_de=str(dados.get("depende_de") or "").strip()[:60],
        depende_valor=str(dados.get("depende_valor") or "").strip()[:60],
        impedimento=str(dados.get("impedimento") or "").strip()[:60],
    )


def _soltar_dependencias_orfas(blocos: list[Bloco]) -> None:
    """Abre as perguntas cujo `depende_de` não leva a lugar nenhum.

    Sem um pai respondível, `depende_de` mantém a pergunta FECHADA para sempre —
    ela some da entrevista sem avisar ninguém. Dois jeitos banais de chegar lá:

        órfã          o pai não existe (o modelo inventou o id, ou o advogado
                      apagou a pergunta-pai no editor)
        auto-referente  a pergunta depende de si mesma, e como ela só é
                      respondida depois de aberta, nunca abre

    Soltar é o lado seguro de errar. Uma pergunta a mais na tela é um segundo de
    conversa; uma pergunta que sumiu é um dado que ninguém colheu e que só
    aparece na hora de redigir a petição.
    """
    existentes = {p.id for bloco in blocos for p in bloco.perguntas}
    for bloco in blocos:
        for pergunta in bloco.perguntas:
            if not pergunta.depende_de:
                continue
            if pergunta.depende_de == pergunta.id:
                motivo = "dependia de si mesma"
            elif pergunta.depende_de not in existentes:
                motivo = f"dependia de '{pergunta.depende_de}', que não existe no roteiro"
            else:
                continue
            log.warning("Pergunta '%s' %s. Ela passa a aparecer sempre.", pergunta.id, motivo)
            pergunta.depende_de = ""
            pergunta.depende_valor = ""


def _lista_de_texto(valor: Any) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    return [str(item).strip()[:2000] for item in valor if str(item).strip()][:40]


def _mapa_de_texto(valor: Any) -> dict[str, str]:
    if not isinstance(valor, dict):
        return {}
    return {
        str(chave).strip().lower()[:20]: str(texto).strip()[:2000]
        for chave, texto in valor.items()
        if str(texto).strip()
    }


# ----------------------------------------------------------- cache do banco
#
# `obter` é chamado a cada trecho de fala pela escuta automática — várias vezes
# por minuto durante a entrevista inteira. Ir ao SQL Server em todas seria trocar
# uma consulta de dicionário por um ida-e-volta de rede no meio da conversa.
#
# O TTL é curto porque o preço de um cache velho aqui é baixo (a tela recarrega o
# roteiro ao abrir) e `invalidar_cache` zera na hora em que alguém salva.

_TTL_CACHE_S = 30.0
_cache: dict[str, Roteiro] = {}
_cache_metadados: dict[str, dict[str, Any]] = {}
_cache_ate: float = 0.0
_cache_resumos: list[dict[str, Any]] = []
_cache_resumos_ate: float = 0.0
_cache_resumos_banco_disponivel: bool | None = None
_cache_codigos_salvos: set[str] = set()
_cache_por_codigo: dict[str, tuple[float, Roteiro | None, dict[str, Any] | None]] = {}

#: Quando este arquivo foi escrito — o "carimbo" do roteiro que vem em código.
#:
#: A data do arquivo, e não uma constante que alguém teria de lembrar de subir a
#: cada alteração: esquecer de incrementá-la traria de volta exatamente o defeito
#: que ela existe para evitar. Numa imagem Docker o arquivo é gravado no build,
#: então cada deploy nasce com carimbo novo.
_VERSAO_MODULO = datetime.fromtimestamp(
    Path(__file__).stat().st_mtime, tz=timezone.utc
).isoformat(timespec="seconds")


def invalidar_cache() -> None:
    """Chamado depois de salvar ou excluir. Idempotente e barato."""
    global _cache_ate, _cache_resumos_ate, _cache_resumos_banco_disponivel
    _cache_ate = 0.0
    _cache_resumos_ate = 0.0
    _cache_resumos_banco_disponivel = None
    _cache_codigos_salvos.clear()
    _cache_por_codigo.clear()


def _importado_por_codigo(
    codigo: str,
) -> tuple[Roteiro | None, dict[str, Any] | None]:
    """Carrega somente o roteiro escolhido, nunca o catálogo completo."""
    agora = time.monotonic()
    em_cache = _cache_por_codigo.get(codigo)
    if em_cache is not None and agora < em_cache[0]:
        return em_cache[1], em_cache[2]

    # Se o seletor acabou de consultar o catálogo, ele já sabe se há uma versão
    # salva deste código. Não repita uma conexão que acabou de falhar nem procure
    # no banco por um roteiro que o catálogo confirmou ser apenas embutido.
    if agora < _cache_resumos_ate and (
        _cache_resumos_banco_disponivel is False
        or (
            _cache_resumos_banco_disponivel is True
            and codigo not in _cache_codigos_salvos
        )
    ):
        resultado = (None, None)
        _cache_por_codigo[codigo] = (agora + _TTL_CACHE_S, *resultado)
        return resultado

    try:
        from . import armazenamento

        registro = armazenamento.obter_roteiro(codigo)
    except Exception:
        log.debug("Roteiro salvo '%s' indisponível.", codigo, exc_info=True)
        registro = None

    salvo: Roteiro | None = None
    if registro is not None:
        try:
            salvo = de_dict(registro.get("conteudo"))
        except RoteiroInvalido:
            log.warning("Roteiro salvo '%s' está inválido e foi ignorado.", codigo)

    _cache_por_codigo[codigo] = (agora + _TTL_CACHE_S, salvo, registro)
    return salvo, registro


def listar_resumos() -> list[dict[str, Any]]:
    """Catálogo leve e coerente com a versão que `obter` entregará no clique."""
    global _cache_resumos, _cache_resumos_ate, _cache_resumos_banco_disponivel
    agora = time.monotonic()
    if agora < _cache_resumos_ate:
        return [dict(item) for item in _cache_resumos]

    try:
        from . import armazenamento

        salvos = armazenamento.listar_resumos_roteiros()
        _cache_resumos_banco_disponivel = True
    except Exception:
        log.debug("Resumos de roteiros indisponíveis; usando os do módulo.", exc_info=True)
        salvos = []
        _cache_resumos_banco_disponivel = False

    _cache_codigos_salvos.clear()
    _cache_codigos_salvos.update(
        str(item.get("codigo") or "") for item in salvos if item.get("codigo")
    )

    por_codigo = {
        str(item.get("codigo") or ""): item
        for item in salvos
        if str(item.get("codigo") or "")
    }
    resultado: list[dict[str, Any]] = []
    for codigo, embutido in ROTEIROS.items():
        salvo = por_codigo.pop(codigo, None)
        # O `pop` acontece ANTES de ocultar, e a ordem importa: sem ele, a versão
        # editada de um roteiro oculto sobraria em `por_codigo` e reapareceria no
        # laço de baixo como roteiro importado — com selo de origem e botão de
        # excluir —, que é exatamente o card que se quer fora da tela.
        if codigo in OCULTOS_NO_CATALOGO:
            continue
        salvo_ativo = bool(
            salvo and str(salvo.get("atualizado_em") or "") >= _VERSAO_MODULO
        )
        resultado.append(
            {
                "codigo": codigo,
                "nome": salvo.get("nome", embutido.nome) if salvo_ativo else embutido.nome,
                "descricao": (
                    salvo.get("descricao", embutido.descricao)
                    if salvo_ativo
                    else embutido.descricao
                ),
                "importado": salvo is not None,
                "original_do_sistema": True,
                "origem": str((salvo or {}).get("origem") or ""),
                "criado_por": str((salvo or {}).get("criado_por") or ""),
                "atualizado_em": str((salvo or {}).get("atualizado_em") or ""),
            }
        )

    # `salvos` já veio em ordem de criação; dicionários preservam essa ordem.
    for codigo, salvo in por_codigo.items():
        resultado.append(
            {
                "codigo": codigo,
                "nome": str(salvo.get("nome") or codigo),
                "descricao": str(salvo.get("descricao") or ""),
                "importado": True,
                "original_do_sistema": False,
                "origem": str(salvo.get("origem") or ""),
                "criado_por": str(salvo.get("criado_por") or ""),
                "atualizado_em": str(salvo.get("atualizado_em") or ""),
            }
        )

    _cache_resumos = resultado
    _cache_resumos_ate = agora + _TTL_CACHE_S
    return [dict(item) for item in resultado]


def catalogo_resumos_parcial() -> bool:
    """Verdadeiro quando só os roteiros embutidos puderam ser listados."""
    return _cache_resumos_banco_disponivel is False


def metadados_importados() -> dict[str, dict[str, Any]]:
    """Metadados das mesmas linhas já carregadas para montar o catálogo.

    A listagem precisa de origem, autor e datas. Reaproveitar esta cópia evita
    uma segunda ida ao SQL Server na mesma requisição.
    """
    _importados()
    return dict(_cache_metadados)


def _importados() -> dict[str, Roteiro]:
    global _cache, _cache_ate, _cache_metadados

    agora = time.monotonic()
    if agora < _cache_ate:
        return _cache

    try:
        from . import armazenamento

        linhas = armazenamento.listar_roteiros()
    except Exception:
        # Sem banco (testes, boot antes do schema) o sistema tem de continuar
        # servindo o roteiro do escritório. Um catálogo vazio faz exatamente
        # isso; levantar aqui derrubaria a entrevista inteira.
        log.debug("Catálogo de roteiros indisponível; usando só os do módulo.", exc_info=True)
        _cache, _cache_metadados, _cache_ate = {}, {}, agora + _TTL_CACHE_S
        return _cache

    _cache_metadados = {
        str(linha.get("codigo") or ""): linha
        for linha in linhas
        if str(linha.get("codigo") or "")
    }
    catalogo: dict[str, Roteiro] = {}
    for linha in linhas:
        try:
            catalogo[linha["codigo"]] = de_dict(linha["conteudo"])
        except RoteiroInvalido:
            # Uma linha corrompida não pode esconder as outras do catálogo.
            log.warning("Roteiro salvo '%s' está inválido e foi ignorado.", linha.get("codigo"))

    _cache, _cache_ate = catalogo, agora + _TTL_CACHE_S
    return _cache
