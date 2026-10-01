"""A base de contexto do caso: o que o chat já levantou fica guardado com a petição.

Sem banco e sem modelo: o armazenamento é um dicionário na memória. Nenhum teste aqui
escreve no SQL Server.

O QUE ESTE TESTE PROTEGE

1. **o resumo dos documentos acompanha os anexos** — anexo novo, lido ou reclassificado
   refaz o resumo, e as buscas antigas (que podem ter deixado de valer) caem;
2. **as pesquisas na web ficam** quando os anexos mudam, valem 30 dias e não se repetem;
3. **só o que ACHOU fica** nas buscas em documentos;
4. **a base é otimização, nunca requisito**: falha de leitura ou de gravação não estoura;
5. **o bloco que vai ao modelo tem teto** e marca o documento ainda sem texto lido.

    .venv\\Scripts\\python.exe -m tests.test_contexto_caso
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agente import contexto_caso  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


ARMAZEM: dict[str, dict] = {}
gravacoes: list[str] = []


def _ler(caso_id):
    return json.loads(json.dumps(ARMAZEM.get(caso_id, {})))


def _gravar(caso_id, dados):
    gravacoes.append(caso_id)
    ARMAZEM[caso_id] = json.loads(json.dumps(dados, default=str))


contexto_caso._ler = _ler  # type: ignore[assignment]
contexto_caso._gravar = _gravar  # type: ignore[assignment]

CTPS = {
    "id": "a1",
    "arquivo": "IMG_4411.jpg",
    "tipo": "CTPS",
    "situacao": "lido",
    "texto": "CARTEIRA DE TRABALHO Nº 1234567 série 0012 admissão 03/03/2019 " * 30,
    "campos": [{"rotulo": "Número", "valor": "1234567"}, {"rotulo": "Série", "valor": "0012"}],
}
LAUDO = {"id": "a2", "arquivo": "laudo.pdf", "tipo": "Laudo médico", "situacao": "lido", "texto": "lesão no ombro direito", "campos": []}
ZAP = {"id": "a3", "arquivo": "WhatsApp Image.jpeg", "tipo": "", "situacao": "na_fila", "texto": "", "campos": []}

print("1. a assinatura acompanha os anexos")
base = contexto_caso.assinatura([CTPS, LAUDO])
checar(base == contexto_caso.assinatura([LAUDO, CTPS]), "a ordem dos anexos não muda a assinatura")
checar(base != contexto_caso.assinatura([CTPS, LAUDO, ZAP]), "anexo novo muda")
checar(base != contexto_caso.assinatura([CTPS, {**LAUDO, "tipo": "Atestado"}]), "reclassificação muda")
checar(base != contexto_caso.assinatura([CTPS, {**LAUDO, "texto": LAUDO["texto"] + " e no braço"}]), "texto lido a mais muda")
checar(
    contexto_caso.assinatura([CTPS, ZAP]) != contexto_caso.assinatura([CTPS, {**ZAP, "situacao": "lido", "texto": "texto"}]),
    "anexo que termina de ser lido muda",
)

print("2. o resumo dos documentos")
dados = contexto_caso.obter("caso-1", [CTPS, LAUDO, ZAP])
checar(len(dados["documentos"]) == 3 and len(gravacoes) == 1, "monta o resumo e grava uma vez")
ctps = dados["documentos"][0]
checar(len(ctps["inicio"]) <= contexto_caso.INICIO_DO_DOCUMENTO, "o início do texto tem teto")
checar({"rotulo": "Número", "valor": "1234567"} in ctps["campos"], "os campos extraídos vão junto")
checar(dados["documentos"][2]["inicio"] == "", "anexo sem texto lido não tem início")
contexto_caso.obter("caso-1", [CTPS, LAUDO, ZAP])
checar(len(gravacoes) == 1, "mesmos anexos: nada é regravado")

print("3. buscas e pesquisas")
contexto_caso.registrar_busca(
    "caso-1",
    "número da CTPS",
    {
        "encontrado": True,
        "resultados": [{"arquivo": "IMG_4411.jpg", "tipo": "CTPS", "trechos": ["… Nº 1234567 …"], "campos_extraidos": [{"rotulo": "Número", "valor": "1234567"}]}],
    },
)
contexto_caso.registrar_busca("caso-1", "termo que não existe", {"encontrado": False, "resultados": []})
contexto_caso.registrar_busca("caso-1", "número da CTPS", {"encontrado": True, "reaproveitada": True, "resultados": [{"arquivo": "x"}]})
checar(len(ARMAZEM["caso-1"]["buscas"]) == 1, "só a busca que ACHOU fica, e a reaproveitada não se duplica")
lembrada = contexto_caso.busca_lembrada(ARMAZEM["caso-1"], "Número da  CTPS")
checar(
    bool(lembrada) and lembrada["reaproveitada"] and lembrada["resultados"][0]["arquivo"] == "IMG_4411.jpg",
    "a busca é lembrada por termo, sem acento nem caixa",
)
checar(contexto_caso.busca_lembrada(ARMAZEM["caso-1"], "PIS") is None, "outro termo não é lembrado")

FONTE = [{"url": "https://tst.jus.br/s378", "titulo": "TST", "confianca": "TRIBUNAL", "trecho": "x" * 500}]
contexto_caso.registrar_pesquisa("caso-1", {"pergunta": "Súmula 378 TST", "resposta": "Garante.", "fontes": FONTE, "tem_fonte_oficial": True})
contexto_caso.registrar_pesquisa("caso-1", {"pergunta": "súmula 378  tst", "resposta": "Garante, atualizada.", "fontes": FONTE})
contexto_caso.registrar_pesquisa("caso-1", {"pergunta": "sem fonte", "resposta": "x", "fontes": []})
pesquisas = ARMAZEM["caso-1"]["pesquisas"]
checar(len(pesquisas) == 1 and pesquisas[0]["resposta"] == "Garante, atualizada.", "a mesma pergunta fica uma vez, a mais recente")
checar("trecho" not in pesquisas[0]["fontes"][0], "da fonte só vão url, título e confiança")
for i in range(20):
    contexto_caso.registrar_pesquisa("caso-1", {"pergunta": f"assunto número {i} distinto", "resposta": "r", "fontes": FONTE})
checar(len(ARMAZEM["caso-1"]["pesquisas"]) == contexto_caso.MAX_PESQUISAS, "há teto de pesquisas guardadas")

velha = {**ARMAZEM["caso-1"]["pesquisas"][0], "em": (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()}
validas = contexto_caso.pesquisas_validas({"pesquisas": [velha, ARMAZEM["caso-1"]["pesquisas"][-1]]})
checar(len(validas) == 1, "pesquisa com mais de 30 dias deixa de valer")

print("4. anexo novo: o resumo se refaz, as buscas caem, as pesquisas ficam")
pesquisas_antes = len(ARMAZEM["caso-1"]["pesquisas"])
dados = contexto_caso.obter("caso-1", [CTPS, LAUDO, {**ZAP, "situacao": "lido", "texto": "print da conversa"}])
checar(dados["buscas"] == [], "as buscas antigas saem (um «não achei» pode ter deixado de valer)")
checar(len(ARMAZEM["caso-1"]["pesquisas"]) == pesquisas_antes, "as pesquisas continuam")
checar(dados["documentos"][2]["inicio"] == "print da conversa", "e o anexo recém-lido entra no resumo")
refeita = contexto_caso.refazer("caso-1", [CTPS, LAUDO])
checar(len(refeita["documentos"]) == 2 and refeita["buscas"] == [], "«atualizar» refaz o levantamento dos documentos")

print("5. o bloco que vai ao modelo")
contexto_caso.registrar_busca(
    "caso-1", "número da CTPS",
    {"encontrado": True, "resultados": [{"arquivo": "IMG_4411.jpg", "tipo": "CTPS", "trechos": ["… Nº 1234567 …"], "campos_extraidos": []}]},
)
bloco = contexto_caso.bloco_para_o_modelo(ARMAZEM["caso-1"])
checar("BASE DE CONTEXTO DO CASO" in bloco and "IMG_4411.jpg — CTPS" in bloco, "leva os documentos com tipo")
checar("Número: 1234567" in bloco, "e os campos que o OCR extraiu")
checar("«número da CTPS»" in bloco and "Nº 1234567" in bloco, "e as buscas já feitas, com o trecho achado")
sem_leitura = contexto_caso.bloco_para_o_modelo({"documentos": contexto_caso._digerir([ZAP]), "buscas": []})
checar("SEM texto lido" in sem_leitura, "anexo ainda sem leitura é marcado: não dá para citar o conteúdo")
checar(contexto_caso.bloco_para_o_modelo({}) == "", "sem nada levantado, não há bloco")
enorme = [{**CTPS, "id": f"d{i}", "arquivo": f"doc{i}.jpg"} for i in range(60)]
grande = contexto_caso.bloco_para_o_modelo({"documentos": contexto_caso._digerir(enorme), "buscas": []})
checar(len(grande) <= contexto_caso.LIMITE_DO_BLOCO + 10, f"o bloco tem teto ({len(grande)} caracteres com 60 anexos)")

print("6. a base é otimização, nunca requisito")


def _quebra(*_):
    raise RuntimeError("banco fora do ar")


contexto_caso._ler = _quebra  # type: ignore[assignment]
contexto_caso._gravar = _quebra  # type: ignore[assignment]
falha = contexto_caso.obter("caso-2", [CTPS])
checar(falha["indisponivel"] is True and len(falha["documentos"]) == 1, "leitura que falha devolve o resumo montado na hora")
try:
    contexto_caso.registrar_pesquisa("caso-2", {"pergunta": "x y z", "resposta": "r", "fontes": FONTE})
    contexto_caso.registrar_busca("caso-2", "x", {"encontrado": True, "resultados": [{"arquivo": "a", "trechos": ["t"]}]})
    checar(contexto_caso.lida("caso-2") == {}, "e gravar/ler com o banco fora do ar não estoura")
except Exception as erro:  # noqa: BLE001
    checar(False, f"não deveria estourar: {erro}")

print("7. o que a tela mostra")
contexto_caso._ler = _ler  # type: ignore[assignment]
numeros = contexto_caso.resumo(ARMAZEM["caso-1"])
checar(numeros["documentos_lidos"] == 2 and numeros["buscas"] == 1 and numeros["pesquisas"] >= 1, "só números, sem conteúdo")

if __name__ == "__main__":
    print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
