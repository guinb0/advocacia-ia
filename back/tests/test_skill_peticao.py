import io
import time
import zipfile

import pytest

from app import peticao_local, skill_peticao, skills_juridicas
from app import peticao_skill_arquivos as skill
from tests.test_modelo_visual_peticao import _FORMATACAO_ALTERNATIVA


def _zip(arquivos: dict[str, str | bytes]) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as zipado:
        for caminho, conteudo in arquivos.items():
            zipado.writestr(caminho, conteudo)
    return saida.getvalue()


def _usar(monkeypatch, ativa: skill_peticao.SkillAtiva, *, lida_em: float | None = None) -> None:
    monkeypatch.setattr(skill_peticao, "_lida", (time.monotonic() if lida_em is None else lida_em, ativa))


def test_skill_enviada_comanda_conteudo_estrutura_layout_e_logo(monkeypatch):
    textos = skill.textos_do_disco()
    textos["formatacao.md"] = _FORMATACAO_ALTERNATIVA
    textos["estrutura_peca.md"] = "1. **Primeiro bloco do escritório**\n2. **Segundo bloco do escritório**\n"
    textos["regras_de_geracao.md"] = "REGRA-EXCLUSIVA-DA-SKILL-ENVIADA"
    logo = b"\x89PNG\r\n\x1a\nlogo-da-skill"
    _usar(monkeypatch, skill_peticao.SkillAtiva("minha-skill", "Minha skill", textos, (logo, ".png", "x/assets/logo.png")))

    assert skill.configuracao_visual_padrao()["fonte"] == "Georgia"
    assert [b["titulo"] for b in skill.estrutura_da_skill()] == [
        "Primeiro bloco do escritório", "Segundo bloco do escritório",
    ]
    assert "REGRA-EXCLUSIVA-DA-SKILL-ENVIADA" in skill.carregar("Horas extras", "horas_extras")
    assert skill.resumo("Horas extras", "horas_extras")["skill"] == "minha-skill"
    conteudo = peticao_local.montar_docx([{"code": "X", "label": "", "content": "Texto."}])
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        assert arquivo.read("word/media/logo-escritorio.png") == logo
        assert 'w:ascii="Georgia"' in arquivo.read("word/styles.xml").decode("utf-8")


def test_pacote_incompleto_e_recusado_antes_de_gravar(monkeypatch):
    def nao_grava(*_a, **_k):
        raise AssertionError("pacote inválido não pode ser gravado")

    monkeypatch.setattr(skills_juridicas, "importar_zip", nao_grava)
    pacote = _zip({"SKILL.md": "# Skill", "references/formatacao.md": "Sem bloco de estilo."})
    with pytest.raises(ValueError) as erro:
        skill_peticao.importar("nova.skill.zip", pacote)
    assert "estilo" in str(erro.value) and "estrutura_peca.md" in str(erro.value)


def test_skill_baixada_volta_valida_e_com_logo():
    conteudo, nome = skill_peticao.pacote()
    assert nome == "escritorio-trabalhista.skill.zip"
    principal, referencias, assets = skills_juridicas.ler_zip(conteudo)
    verificacao = skill.verificar(skill_peticao.textos_do_registro({"skill_md": principal, "referencias": referencias}))
    assert verificacao["ok"], verificacao["problemas"]
    assert verificacao["blocos"] == [b["titulo"] for b in skill.estrutura_da_skill()]
    assert skill_peticao._logo(assets)[2].endswith("assets/logo.png")


def test_references_na_raiz_do_zip_sao_aceitas():
    principal, referencias, _ = skills_juridicas.ler_zip(_zip({"SKILL.md": "# S", "references/a.md": "A"}))
    assert principal == "# S" and referencias == {"references/a.md": "A"}


def _skill_alternativa(skill_id: str) -> skill_peticao.SkillAtiva:
    textos = skill.textos_do_disco()
    textos["formatacao.md"] = _FORMATACAO_ALTERNATIVA
    return skill_peticao.SkillAtiva(skill_id, skill_id, textos)


def test_skill_escolhida_no_caso_muda_a_geracao_so_daquele_caso(monkeypatch):
    from app import armazenamento

    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    escolhas = {"caso-a": "skill-do-caso", "caso-b": None}
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: {"skill_juridica_id": escolhas[caso_id]})
    monkeypatch.setattr(skill_peticao, "_carregar", _skill_alternativa)
    monkeypatch.setattr(skill_peticao, "_do_caso_lidas", {})

    @skill_peticao.com_skill_do_caso
    def fonte_da_peca(caso_id: str) -> str:
        return skill.configuracao_visual_padrao()["fonte"]

    assert fonte_da_peca("caso-a") == "Georgia"
    assert fonte_da_peca("caso-b") == "Arial"
    assert skill.configuracao_visual_padrao()["fonte"] == "Arial"  # fora do caso, vale a do escritório


def test_skill_do_caso_que_nao_gera_peticao_cai_na_do_escritorio(monkeypatch):
    from app import armazenamento

    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: {"skill_juridica_id": "documental"})
    monkeypatch.setattr(
        skill_peticao, "_carregar",
        lambda skill_id: skill_peticao.SkillAtiva(skill_id, skill_id, {"SKILL.md": "# só análise documental"}),
    )
    monkeypatch.setattr(skill_peticao, "_do_caso_lidas", {})
    with skill_peticao.do_caso("caso-x"):
        assert skill_peticao.ativa() is skill_peticao._DO_SISTEMA


def test_escolha_do_caso_segue_para_as_threads_da_geracao(monkeypatch):
    from app import armazenamento

    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: {"skill_juridica_id": "skill-do-caso"})
    monkeypatch.setattr(skill_peticao, "_carregar", _skill_alternativa)
    monkeypatch.setattr(skill_peticao, "_do_caso_lidas", {})
    with skill_peticao.do_caso("caso-a"):
        fontes = peticao_local._em_paralelo_com_contexto(
            lambda _: skill.configuracao_visual_padrao()["fonte"], [1, 2, 3]
        )
    assert list(fontes) == ["Georgia"] * 3


def test_observacoes_do_escritorio_entram_por_ultimo_no_prompt(monkeypatch):
    textos = skill.textos_do_disco()
    textos[skill.OBSERVACOES] = "OBSERVACAO-DO-ESCRITORIO"
    _usar(monkeypatch, skill_peticao.SkillAtiva("minha-skill", "Minha skill", textos))

    prompt = skill.carregar("Horas extras", "horas_extras")
    assert prompt.rstrip().endswith("OBSERVACAO-DO-ESCRITORIO")
    assert "prevalecem" in prompt
    assert skill.OBSERVACOES in skill.resumo("Horas extras", "horas_extras")["arquivos"]


def _gravacoes(monkeypatch) -> list[tuple]:
    gravadas: list[tuple] = []
    monkeypatch.setattr(skills_juridicas, "gravar_textos", lambda *a, **_k: gravadas.append(a))
    monkeypatch.setattr(skill_peticao, "estado", lambda: {"ok": True})
    return gravadas


def _registro(textos: dict[str, str], atualizado_em: str = "2026-09-28 10:00:00+00:00") -> dict:
    return {
        "nome": "Minha skill",
        "descricao": "",
        "skill_md": textos["SKILL.md"],
        "referencias": skill_peticao._em_pacote(textos),
        "atualizado_em": atualizado_em,
    }


def test_editar_a_skill_do_sistema_grava_copia_e_passa_a_usar_ela(monkeypatch):
    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    gravadas = _gravacoes(monkeypatch)
    ativadas: list[str] = []
    monkeypatch.setattr(skill_peticao, "ativar", lambda skill_id, por="": ativadas.append(skill_id) or {"ok": True})

    skill_peticao.salvar_arquivo("", "references/observacoes.md", "Sempre pedir justiça gratuita.", por="Ana")

    (destino, _nome, _descricao, skill_md, referencias), = gravadas
    assert destino == skill_peticao.COPIA_EDITAVEL and ativadas == [destino]
    assert skill_md == skill.textos_do_disco()["SKILL.md"]
    assert referencias["references/observacoes.md"] == "Sempre pedir justiça gratuita."
    assert "references/formatacao.md" in referencias


def test_edicao_que_quebra_a_skill_nao_e_gravada(monkeypatch):
    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    gravadas = _gravacoes(monkeypatch)
    with pytest.raises(ValueError, match="estilo"):
        skill_peticao.salvar_arquivo("", "formatacao.md", "Sem bloco de estilo.")
    with pytest.raises(ValueError, match="não existe"):
        skill_peticao.salvar_arquivo("", "novo.md", "x")
    with pytest.raises(ValueError, match="inválido"):
        skill_peticao.salvar_arquivo("", "../app/config.md", "x")
    assert gravadas == []


class _ConexaoFalsa:
    """Responde ao SELECT ... FOR UPDATE com a skill gravada e anota o resto."""

    def __init__(self, gravada: tuple | None):
        self.gravada = gravada
        self.comandos: list[str] = []
        self._ultima: tuple | None = None

    def execute(self, sql: str, _parametros=None):
        self.comandos.append(" ".join(sql.split()))
        self._ultima = self.gravada if "FOR UPDATE" in sql else None
        return self

    def fetchone(self):
        return self._ultima


def test_skill_de_peticao_nao_e_sobrescrita_por_pacote_quebrado():
    textos = skill.textos_do_disco()
    con = _ConexaoFalsa((textos["SKILL.md"], skill_peticao._em_pacote(textos), "2026-09-28 10:00:00+00:00"))
    with pytest.raises(ValueError, match="Nada foi gravado"):
        skills_juridicas._gravar_textos(
            con, "minha-skill", "Minha skill", "", "# Skill", {"references/notas.md": "x"}, motivo="Adicionar outra skill"
        )
    assert not any(c.startswith("INSERT INTO skills_juridicas ") for c in con.comandos)


def test_gravacao_recusa_skill_alterada_desde_a_leitura():
    con = _ConexaoFalsa(("# S", {}, "2026-09-28 10:05:00+00:00"))
    with pytest.raises(skills_juridicas.AlteradaNoMeioTempo):
        skills_juridicas._gravar_textos(
            con, "s", "S", "", "# S2", {}, motivo="x", lida_em="2026-09-28 10:00:00+00:00"
        )


def test_gravacao_guarda_versao_no_historico():
    con = _ConexaoFalsa(None)
    skills_juridicas._gravar_textos(con, "nova", "Nova", "", "# S", {"references/a.md": "A"}, motivo="criada", por="Ana")
    assert any(c.startswith("INSERT INTO skills_juridicas_versoes") for c in con.comandos)


def test_mesmo_arquivo_alterado_por_outra_pessoa_nao_e_sobrescrito(monkeypatch):
    textos = skill.textos_do_disco()
    _usar(monkeypatch, skill_peticao.SkillAtiva("minha-skill", "Minha skill", textos))
    gravadas = _gravacoes(monkeypatch)
    atual = dict(textos, **{"validacoes.md": "Versão que a Bia acabou de gravar."})
    monkeypatch.setattr(skills_juridicas, "obter", lambda _id: _registro(atual))
    with pytest.raises(skills_juridicas.AlteradaNoMeioTempo, match="Outra pessoa"):
        skill_peticao.salvar_arquivo(
            "minha-skill", "validacoes.md", "Minha versão.", texto_lido=textos["validacoes.md"]
        )
    assert gravadas == []


def test_edicao_concorrente_em_outro_arquivo_e_preservada(monkeypatch):
    textos = skill.textos_do_disco()
    _usar(monkeypatch, skill_peticao.SkillAtiva("minha-skill", "Minha skill", textos))
    monkeypatch.setattr(skill_peticao, "estado", lambda: {"ok": True})
    leituras = iter([
        _registro(textos),
        _registro(dict(textos, **{"validacoes.md": "GRAVADO PELA BIA"}), "2026-09-28 10:05:00+00:00"),
    ])
    monkeypatch.setattr(skills_juridicas, "obter", lambda _id: next(leituras))
    gravadas: list[dict] = []

    def gravar(*a, lida_em=None, **_k):
        if lida_em == "2026-09-28 10:00:00+00:00":
            raise skills_juridicas.AlteradaNoMeioTempo("a Bia gravou antes")
        gravadas.append(a[4])

    monkeypatch.setattr(skills_juridicas, "gravar_textos", gravar)
    skill_peticao.salvar_arquivo("minha-skill", skill.OBSERVACOES, "Minha observação.", texto_lido="")
    (referencias,) = gravadas
    assert referencias["references/validacoes.md"] == "GRAVADO PELA BIA"
    assert referencias[f"references/{skill.OBSERVACOES}"] == "Minha observação."


def test_skill_fica_fixa_durante_a_operacao_do_caso(monkeypatch):
    from app import armazenamento

    _usar(monkeypatch, skill_peticao._DO_SISTEMA)
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: {"skill_juridica_id": None})
    with skill_peticao.do_caso("caso-a"):
        _usar(monkeypatch, _skill_alternativa("editada-no-meio"))
        assert skill_peticao.ativa() is skill_peticao._DO_SISTEMA
    assert skill_peticao.ativa().id == "editada-no-meio"


def test_skill_quebrada_no_banco_usa_a_ultima_versao_boa(monkeypatch):
    boa = skill.textos_do_disco()
    monkeypatch.setattr(
        skill_peticao, "_carregar", lambda skill_id: skill_peticao.SkillAtiva(skill_id, "S", {"SKILL.md": "# quebrada"})
    )
    monkeypatch.setattr(skills_juridicas, "versoes", lambda _id: [
        {"id": 3, "gravado_em": "hoje"}, {"id": 2, "gravado_em": "ontem"},
    ])
    monkeypatch.setattr(
        skills_juridicas, "versao",
        lambda _id, versao_id: _registro({"SKILL.md": "# quebrada"}) if versao_id == 3 else _registro(boa),
    )
    carregada = skill_peticao._carregar_valida("minha-skill")
    assert carregada is not None and carregada.textos == boa


def test_reenviar_pacote_sem_observacoes_mantem_as_do_escritorio(monkeypatch):
    textos = skill.textos_do_disco()
    monkeypatch.setattr(
        skills_juridicas, "obter", lambda _id: _registro(dict(textos, **{skill.OBSERVACOES: "Pedir justiça gratuita."}))
    )
    recebido: dict = {}
    monkeypatch.setattr(
        skills_juridicas, "importar_zip", lambda nome, _c, _d, **k: recebido.update(k) or {"id": "minha-skill"}
    )
    monkeypatch.setattr(skill_peticao, "ativar", lambda skill_id, por="": {"ok": True})
    skill_peticao.importar("minha-skill.skill.zip", _zip({"SKILL.md": textos["SKILL.md"], **skill_peticao._em_pacote(textos)}))
    assert recebido["manter"] == {f"references/{skill.OBSERVACOES}": "Pedir justiça gratuita."}


def test_restaurar_versao_grava_como_nova_versao(monkeypatch):
    textos = skill.textos_do_disco()
    _usar(monkeypatch, skill_peticao.SkillAtiva("minha-skill", "Minha skill", textos))
    monkeypatch.setattr(skills_juridicas, "obter", lambda _id: _registro(textos))
    monkeypatch.setattr(skills_juridicas, "versao", lambda _id, _v: {**_registro(textos), "gravado_em": "2026-09-27 09:30:00"})
    monkeypatch.setattr(skill_peticao, "estado", lambda: {"ok": True})
    motivos: list[str] = []
    monkeypatch.setattr(skills_juridicas, "gravar_textos", lambda *a, motivo, **_k: motivos.append(motivo))
    skill_peticao.restaurar("minha-skill", 7, por="Ana")
    assert motivos == ["Restaurada a versão de 2026-09-27 09:30"]


def test_banco_fora_do_ar_mantem_a_ultima_skill_lida(monkeypatch):
    enviada = skill_peticao.SkillAtiva("minha-skill", "Minha skill", {"SKILL.md": "# S"})
    _usar(monkeypatch, enviada, lida_em=time.monotonic() - 3600)

    def banco_caiu():
        raise ConnectionError("sem banco")

    monkeypatch.setattr(skill_peticao, "_escolha", banco_caiu)
    assert skill_peticao.ativa() is enviada
