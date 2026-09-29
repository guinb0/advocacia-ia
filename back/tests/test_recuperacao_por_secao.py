"""Recuperação por tópico: divisão, reranking, diversidade, densidade e renderização de citações."""

import io
import re
import zipfile

from app import peticao_local as pl
from app import recuperacao_por_secao as rs


def test_topicos_dividem_por_subcapitulo_e_remontam_sem_perder_nada():
    texto = "Intro.\n\n### a) Da responsabilidade\n\nCorpo um.\n\n### b) Do dano moral\n\nCorpo dois."
    topicos = rs.dividir_em_topicos(texto)
    assert [t["titulo"] for t in topicos] == ["", "a) Da responsabilidade", "b) Do dano moral"]
    assert rs.remontar(topicos).replace("\n\n", "\n") == texto.replace("\n\n", "\n")
    assert len(rs.dividir_em_topicos("Sem cabeçalhos.\n\nSó texto.")) == 1


def _c(peca, chunk, sim, texto, assunto="x", tipo="recurso"):
    return {"peca_id": peca, "chunk_id": chunk, "similaridade": sim, "texto": texto, "assunto": assunto,
            "tipo_peca": tipo, "subteses": [], "nome_arquivo": peca, "categoria": "pecas_complexas"}


def test_rerank_promove_termos_do_topico_e_assunto_e_diversidade_limita_por_peca():
    cands = [
        _c("A", "1", .80, "trabalhista horas extras cartão de ponto intervalo"),
        _c("B", "2", .74, "responsabilidade objetiva atividade de risco assalto agência dano moral in re ipsa", assunto="alvo"),
        _c("B", "3", .73, "responsabilidade objetiva atividade de risco fortuito interno assalto", assunto="alvo"),
        _c("B", "4", .72, "responsabilidade objetiva risco assalto agência"),
        _c("C", "5", .70, "dano moral assalto responsabilidade objetiva empregador risco", assunto="alvo"),
    ]
    ordenados = rs.rerank(cands, ["responsabilidade objetiva assalto agência dano moral atividade de risco"], ["alvo"], [])
    assert ordenados[0]["peca_id"] in ("B", "C") and ordenados[-1]["peca_id"] == "A"  # o vetor sozinho poria A primeiro
    escolhidos = rs.diversificar(ordenados)
    assert sum(1 for c in escolhidos if c["peca_id"] == "B") <= rs.MAXIMO_POR_PECA


def test_metricas_de_densidade_e_criterio_de_revisao():
    curto = "\n\n".join(["O autor sofreu assalto no caixa da agência."] * 6)
    denso = ("O reclamante foi rendido no caixa da agência (Documento 04), o que caracteriza atividade de risco, nos termos "
             "do art. 927, parágrafo único, do Código Civil, aplicável porque a exposição a assaltos é inerente ao manuseio "
             "de numerário, como reconhece a própria empregadora na CAT (Documento 10) e no LISA (Documento 09), de modo que "
             "a responsabilidade independe de culpa.")
    m1, m2 = rs.metricas(curto), rs.metricas(denso)
    assert m1["fragmentacao"] == 1.0 and m2["fragmentacao"] == 0.0 and m2["artigos_por_mil"] > 0
    assert m2["referencias_a_documentos"] == 3
    assert rs.precisa_de_revisao(m1, {"p25": 38}) and not rs.precisa_de_revisao(m2, {"p25": 38})


def test_material_do_topico_registra_consultas_candidatos_reranking_e_o_que_foi_enviado(monkeypatch):
    monkeypatch.setattr(rs.rag, "candidatos_de_pecas", lambda q, limite=40: [
        _c("P1", "a", .8, "responsabilidade objetiva art. 927 atividade de risco assalto", assunto="alvo"),
        _c("P2", "b", .7, "dano moral in re ipsa art. 927 assalto", assunto="alvo")])
    monkeypatch.setattr(rs.recuperacao_por_tese, "precedentes", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(rs.recuperacao_por_tese, "legislacao", lambda *a, **k: ([], [], []))
    plano = {"cronologia": [{"fato": "Assalto na agência"}],
             "teses": [{"tese": "Responsabilidade objetiva", "fatos_que_sustentam": ["caixa"]}]}
    mat = rs.material_do_topico("a) Da responsabilidade objetiva", "texto atual", "VII. Do direito", plano=plano,
                                categoria="Acidente", assuntos=["alvo"], contexto_uf="")
    tel = mat.telemetria
    assert len(tel["consultas"]) >= 2 and tel["acervo"]["candidatos"] == 2 and tel["acervo"]["escolhidos"][0]["final"]
    assert "[E1]" in mat.texto and "NUNCA transporte fatos" in mat.texto and tel["chars_enviados"] == len(mat.texto)
    assert "art. 927" in tel["dispositivos_frequentes_no_acervo"][0]


# ------------------------------------------------------------------ ritmo vertical e citações no renderer
def _xml(conteudo):
    with zipfile.ZipFile(io.BytesIO(pl.montar_docx([{"code": "X", "label": "", "content": conteudo, "formato": 2}]))) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_linhas_de_citacao_consecutivas_sao_um_bloco_e_blocos_se_separam_por_linha_em_branco():
    xml = _xml("Nesse sentido:\n\n> “Primeira linha da ementa\n> segunda linha.” (TST, A)\n\n> “Outro julgado.” (TST, B)\n\nAplicação ao caso.")
    paras = re.findall(r"<w:p>.*?</w:p>", xml, re.S)
    assert len(paras) == 4
    citacoes = [p for p in paras if 'w:left="2268"' in p]
    assert len(citacoes) == 2
    assert "Primeira linha da ementa segunda linha." in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", citacoes[0]))
    assert all('w:after="240"' in p for p in citacoes)  # o espaço do bloco de citação vem da skill (12 pt)


def test_titulo_tem_espaco_antes_e_depois_definidos_pela_skill():
    xml = _xml("Corpo.\n\n## a) Da responsabilidade\n\nOutro corpo.")
    titulo = next(p for p in re.findall(r"<w:p>.*?</w:p>", xml, re.S) if "<w:keepNext/>" in p)
    assert 'w:before="120" w:after="240"' in titulo
