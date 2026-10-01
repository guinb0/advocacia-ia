"""Qual skill comanda a geração da petição: conteúdo, estrutura, validações e layout.

O escritório troca a skill pela tela Skills (cartão "Skill de geração de petição"),
sem deploy. Sem escolha gravada vale a que vem com o sistema
(`ia/skills/escritorio-trabalhista`). A escolhida é uma skill importada
(`skills_juridicas`) que passou por `peticao_skill_arquivos.verificar`.

Um caso pode escolher a própria skill (`casos.skill_juridica_id`): tudo o que é feito
para ele dentro de `do_caso` — gerar, revisar, montar DOCX/PDF — segue essa skill.

A escolha mora no Postgres porque vale para todos os workers ao mesmo tempo; cada
processo a relê no máximo a cada `_VALIDADE_S`. Banco fora do ar nunca derruba a
geração: fica a última skill lida, ou a do sistema.
"""

from __future__ import annotations

import functools
import io
import logging
import threading
import time
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

import psycopg

from . import peticao_skills, skills_juridicas
from .caminhos import SKILLS

log = logging.getLogger("skill_peticao")

T = TypeVar("T")

PADRAO = "escritorio-trabalhista"
_PASTA_PADRAO = SKILLS / PADRAO
_LOGO_PADRAO = Path(__file__).with_name("assets") / "lara-melo-logo.png"
_VALIDADE_S = 30.0


@dataclass(frozen=True)
class SkillAtiva:
    id: str
    nome: str
    #: `SKILL.md` e caminhos relativos a `references/`. None: skill do sistema, lida do disco.
    textos: Mapping[str, str] | None = None
    #: (bytes, extensão, caminho no pacote) da imagem que a skill manda usar no cabeçalho.
    logo: tuple[bytes, str, str] | None = None

    @property
    def do_sistema(self) -> bool:
        return self.textos is None


_DO_SISTEMA = SkillAtiva(PADRAO, "Skill padrão do sistema (escritório trabalhista)")
_trava = threading.Lock()
_lida: tuple[float, SkillAtiva] | None = None

#: A skill fixada por `do_caso` para o caso em trabalho (a dele, ou a do escritório
#: naquele momento). `None`: fora de qualquer caso.
_DO_CASO: ContextVar[tuple[SkillAtiva | None] | None] = ContextVar("skill_peticao_do_caso", default=None)
_do_caso_lidas: dict[str, tuple[float, SkillAtiva | None]] = {}


def inicializar() -> None:
    with peticao_skills._conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS skill_peticao_ativa (
                unica       boolean PRIMARY KEY DEFAULT true CHECK (unica),
                skill_id    varchar(80),
                ativada_por varchar(200) NOT NULL DEFAULT '',
                ativada_em  timestamptz NOT NULL DEFAULT now()
            )
        """)


def _escolha() -> dict[str, Any] | None:
    with peticao_skills._conectar(row_factory=peticao_skills.dict_row) as con:
        try:
            linha = con.execute(
                "SELECT skill_id, ativada_por, ativada_em FROM skill_peticao_ativa WHERE unica"
            ).fetchone()
        except psycopg.errors.UndefinedTable:
            return None
    if linha:
        linha["ativada_em"] = str(linha["ativada_em"])
    return linha


def _relativo_a_references(caminho: str) -> str | None:
    partes = caminho.replace("\\", "/").split("/")
    if "references" not in partes:
        return None
    return "/".join(partes[partes.index("references") + 1:]) or None


def textos_do_registro(registro: Mapping[str, Any]) -> dict[str, str]:
    """Uma skill importada no formato de `peticao_skill_arquivos._ler`."""
    textos = {"SKILL.md": str(registro.get("skill_md") or "")}
    for caminho, texto in dict(registro.get("referencias") or {}).items():
        relativo = _relativo_a_references(caminho)
        if relativo:
            textos[relativo] = str(texto)
    return textos


def _logo(imagens: list[tuple[str, str, bytes]]) -> tuple[bytes, str, str] | None:
    """A imagem com "logo" no nome; sem nenhuma assim, a primeira da pasta assets/."""
    if not imagens:
        return None
    caminho, mime, dados = min(imagens, key=lambda a: ("logo" not in Path(a[0]).stem.lower(), a[0]))
    return dados, ".jpg" if mime == "image/jpeg" else ".png", caminho


def _carregar(skill_id: str) -> SkillAtiva | None:
    from . import skill_de_arquivo

    registro = skills_juridicas.obter(skill_id)
    if not registro:
        return None
    return SkillAtiva(
        id=skill_id,
        nome=skill_de_arquivo.rotulo(skill_id, str(registro.get("nome") or "")),
        textos=textos_do_registro(registro),
        logo=_logo(skills_juridicas.assets(skill_id)),
    )


def _carregar_valida(skill_id: str) -> SkillAtiva | None:
    """A skill `skill_id` se ela gera petição; senão, a última versão do histórico que gera."""
    skill = _carregar(skill_id)
    if skill is None or verificar(skill.textos or {})["ok"]:
        return skill
    try:
        for item in skills_juridicas.versoes(skill_id):
            registro = skills_juridicas.versao(skill_id, int(item["id"]))
            textos = textos_do_registro(registro or {})
            if registro and verificar(textos)["ok"]:
                log.warning("skill %s está quebrada; usando a versão de %s", skill_id, item["gravado_em"])
                return replace(skill, textos=textos)
    except Exception:
        log.warning("histórico da skill %s ilegível", skill_id, exc_info=True)
    log.warning("skill %s não gera petição e não tem versão boa no histórico", skill_id)
    return None


def conferir_substituicao(
    skill_id: str, antes: tuple[str, Mapping[str, str]], depois: tuple[str, Mapping[str, str]]
) -> None:
    """Recusa trocar uma skill que gera petição por um conteúdo que não gera.

    Vale para todo caminho de gravação (tela de edição, pacote enviado, "Adicionar
    outra skill" com o mesmo nome): nada grava por cima de uma skill de petição boa.
    """
    anterior = verificar(textos_do_registro({"skill_md": antes[0], "referencias": antes[1]}))
    if not anterior["ok"]:
        return
    nova = verificar(textos_do_registro({"skill_md": depois[0], "referencias": depois[1]}))
    if not nova["ok"]:
        raise ValueError(
            f'"{skill_id}" é uma skill de geração de petição e essa alteração a deixaria sem conseguir '
            "gerar a peça: " + " ".join(nova["problemas"]) + " Nada foi gravado."
        )


def ativa() -> SkillAtiva:
    """A skill que a geração em curso segue: a do caso, se ele tiver uma; senão a do escritório."""
    do_caso = _DO_CASO.get()
    if do_caso and do_caso[0] is not None:
        return do_caso[0]
    return ativa_do_escritorio()


def ativa_do_escritorio() -> SkillAtiva:
    """A skill que vale para os casos sem escolha própria."""
    global _lida
    lida = _lida
    if lida and time.monotonic() - lida[0] < _VALIDADE_S:
        return lida[1]
    with _trava:
        if _lida and time.monotonic() - _lida[0] < _VALIDADE_S:
            return _lida[1]
        anterior = _lida[1] if _lida else _DO_SISTEMA
        try:
            escolha = _escolha()
            skill_id = (escolha or {}).get("skill_id")
            skill = (_carregar_valida(skill_id) if skill_id else None) or _DO_SISTEMA
            if skill_id and skill.do_sistema:
                log.warning("skill de petição %s não existe mais; usando a do sistema", skill_id)
        except RuntimeError:
            skill = _DO_SISTEMA  # sem DATABASE_URL: não há como ter outra
        except Exception:
            log.warning("skill de petição ativa ilegível; mantendo %s", anterior.id, exc_info=True)
            skill = anterior
        _lida = (time.monotonic(), skill)
        return skill


def esquecer() -> None:
    """A próxima leitura vai ao banco (depois de trocar a skill neste processo)."""
    global _lida
    _lida = None
    _do_caso_lidas.clear()


def _skill_de_peticao(skill_id: str) -> SkillAtiva | None:
    """A skill importada `skill_id`, se ela cobrir a peça inteira; releitura a cada `_VALIDADE_S`."""
    lida = _do_caso_lidas.get(skill_id)
    if lida and time.monotonic() - lida[0] < _VALIDADE_S:
        return lida[1]
    skill = _carregar_valida(skill_id)
    if skill is None:
        log.warning("skill %s escolhida no caso não serve para petição; usando a do escritório", skill_id)
    _do_caso_lidas[skill_id] = (time.monotonic(), skill)
    return skill


def validar_para_caso(skill_id: str) -> None:
    """Recusa, com o motivo, a escolha de uma skill que não gera petição."""
    if not skill_id or skill_id == PADRAO:
        return
    registro = skills_juridicas.obter(skill_id)
    if not registro:
        raise ValueError("Skill não encontrada.")
    verificacao = verificar(textos_do_registro(registro))
    if not verificacao["ok"]:
        raise ValueError(_mensagem_de_recusa(verificacao))


@contextmanager
def do_caso(caso_id: str) -> Iterator[None]:
    """Durante o bloco, `ativa()` devolve a skill escolhida no caso (se houver e for válida).

    A skill fica fixa do começo ao fim do bloco: uma edição gravada no meio de uma
    geração só vale para a próxima, sem misturar duas versões na mesma peça.
    """
    if _DO_CASO.get() is not None:
        yield  # já dentro de um caso: chamadas internas não reconsultam o banco
        return
    skill: SkillAtiva | None = None
    try:
        from . import armazenamento

        skill_id = str((armazenamento.obter_caso(caso_id) or {}).get("skill_juridica_id") or "").strip()
        if skill_id and skill_id != PADRAO:
            skill = _skill_de_peticao(skill_id)
    except Exception:
        log.warning("skill do caso %s ilegível; usando a do escritório", caso_id, exc_info=True)
    token = _DO_CASO.set((skill or ativa_do_escritorio(),))
    try:
        yield
    finally:
        _DO_CASO.reset(token)


def com_skill_do_caso(funcao: Callable[..., T]) -> Callable[..., T]:
    """Decorador para funções cujo primeiro argumento é o `caso_id`."""

    @functools.wraps(funcao)
    def envolvida(caso_id: str, *args: Any, **kwargs: Any) -> T:
        with do_caso(caso_id):
            return funcao(caso_id, *args, **kwargs)

    return envolvida


def verificar(textos: Mapping[str, str]) -> dict[str, Any]:
    from . import peticao_skill_arquivos

    return peticao_skill_arquivos.verificar(textos)


def _mensagem_de_recusa(verificacao: dict[str, Any]) -> str:
    return "A skill não pode gerar petições: " + " ".join(verificacao["problemas"])


def estado() -> dict[str, Any]:
    """A skill ativa, o que ela cobre e as outras skills de petição já enviadas."""
    from . import peticao_skill_arquivos

    esquecer()
    atual = ativa_do_escritorio()
    escolha = None
    try:
        escolha = _escolha()
    except Exception:
        log.warning("não leu quem ativou a skill de petição", exc_info=True)
    textos = atual.textos if atual.textos is not None else peticao_skill_arquivos.textos_do_disco()
    disponiveis = []
    try:
        for item in skills_juridicas.listar():
            if item["id"] == PADRAO:
                continue  # cópia da skill do sistema, gravada na instalação
            registro = skills_juridicas.obter(item["id"])
            if registro and verificar(textos_do_registro(registro))["ok"]:
                disponiveis.append({
                    "id": item["id"],
                    "nome": _nome(item["id"], item.get("nome") or ""),
                    "atualizado_em": item["atualizado_em"],
                })
    except Exception:
        log.warning("skills importadas indisponíveis para a petição", exc_info=True)
    return {
        "ativa": {
            "id": atual.id,
            "nome": atual.nome,
            "do_sistema": atual.do_sistema,
            "logo": atual.logo[2] if atual.logo else "",
            "ativada_por": (escolha or {}).get("ativada_por", "") if not atual.do_sistema else "",
            "ativada_em": (escolha or {}).get("ativada_em", "") if not atual.do_sistema else "",
            "verificacao": verificar(textos),
        },
        "disponiveis": disponiveis,
    }


def _nome(skill_id: str, nome: str) -> str:
    from . import skill_de_arquivo

    return skill_de_arquivo.rotulo(skill_id, nome)


def ativar(skill_id: str | None, *, por: str = "") -> dict[str, Any]:
    """Passa a gerar com `skill_id`; vazio (ou o id da do sistema) volta para a do sistema."""
    skill_id = (skill_id or "").strip() or None
    if skill_id == PADRAO:
        skill_id = None
    if skill_id:
        registro = skills_juridicas.obter(skill_id)
        if not registro:
            raise ValueError("Skill não encontrada.")
        verificacao = verificar(textos_do_registro(registro))
        if not verificacao["ok"]:
            raise ValueError(_mensagem_de_recusa(verificacao))
    inicializar()
    with peticao_skills._conectar() as con:
        con.execute(
            """INSERT INTO skill_peticao_ativa (unica, skill_id, ativada_por) VALUES (true, %s, %s)
               ON CONFLICT (unica) DO UPDATE SET skill_id = EXCLUDED.skill_id,
                   ativada_por = EXCLUDED.ativada_por, ativada_em = now()""",
            (skill_id, por[:200]),
        )
    log.info("skill de petição ativa: %s (por %s)", skill_id or PADRAO, por or "?")
    return estado()


def importar(nome_arquivo: str, conteudo: bytes, *, por: str = "") -> dict[str, Any]:
    """Confere o pacote ANTES de gravar; só uma skill que cobre a peça inteira vira a ativa."""
    principal, referencias, _ = skills_juridicas.ler_zip(conteudo)
    verificacao = verificar(textos_do_registro({"skill_md": principal, "referencias": referencias}))
    if not verificacao["ok"]:
        raise ValueError(_mensagem_de_recusa(verificacao))
    from . import peticao_skill_arquivos

    nome = nome_arquivo or "skill-peticao.skill.zip"
    if skills_juridicas.id_do_nome(nome) == PADRAO:
        # O id da do sistema já é a cópia gravada na instalação; não a sobrescreve.
        nome = f"{PADRAO}-escritorio.skill.zip"
    # Reenviar a skill sem o arquivo de observações não apaga as que o escritório já escreveu.
    existente = skills_juridicas.obter(skills_juridicas.id_do_nome(nome))
    observacoes = textos_do_registro(existente or {}).get(peticao_skill_arquivos.OBSERVACOES, "")
    registro = skills_juridicas.importar_zip(
        nome, conteudo, "Skill de geração de petição enviada pelo escritório.",
        por=por, motivo="Pacote .skill.zip enviado na tela da skill de petição",
        manter={f"references/{peticao_skill_arquivos.OBSERVACOES}": observacoes} if observacoes.strip() else None,
    )
    return ativar(str(registro["id"]), por=por)


#: Onde vai parar a skill do sistema quando o escritório a edita pela tela: a pasta
#: das skills é parte da imagem e não pode ser regravada em produção.
COPIA_EDITAVEL = f"{PADRAO}-editada"
_MAX_TEXTO = 300_000


@dataclass
class _ParaEditar:
    id: str
    nome: str
    descricao: str
    textos: dict[str, str]
    #: `atualizado_em` da skill no banco quando foi lida; None para a do sistema.
    lida_em: str | None


def _para_editar(skill_id: str) -> _ParaEditar:
    """A skill como está agora; vazio = a do escritório."""
    from . import peticao_skill_arquivos

    skill_id = skill_id.strip() or ativa_do_escritorio().id
    if skill_id == PADRAO:
        return _ParaEditar(PADRAO, _DO_SISTEMA.nome, "", peticao_skill_arquivos.textos_do_disco(), None)
    registro = skills_juridicas.obter(skill_id)
    if not registro:
        raise ValueError("Skill não encontrada.")
    return _ParaEditar(
        skill_id,
        _nome(skill_id, str(registro.get("nome") or "")),
        str(registro.get("descricao") or ""),
        textos_do_registro(registro),
        str(registro.get("atualizado_em") or ""),
    )


def arquivos(skill_id: str = "") -> dict[str, Any]:
    """Os arquivos de texto da skill, para editar na tela. Sempre inclui as observações."""
    from . import peticao_skill_arquivos

    skill = _para_editar(skill_id)
    skill.textos.setdefault(peticao_skill_arquivos.OBSERVACOES, "")
    return {
        "skill_id": skill.id,
        "nome": skill.nome,
        "do_sistema": skill.id == PADRAO,
        "arquivos": [{"caminho": caminho, "texto": texto} for caminho, texto in skill.textos.items()],
    }


def _caminho_editavel(caminho: str) -> str:
    caminho = caminho.strip().replace("\\", "/").removeprefix("references/")
    partes = caminho.split("/")
    if caminho != "SKILL.md" and (
        not caminho.endswith(".md") or caminho.startswith("/") or ".." in partes or len(caminho) > 200
    ):
        raise ValueError("Arquivo inválido: só dá para editar o SKILL.md e os .md de references/.")
    return caminho


def _em_pacote(textos: Mapping[str, str]) -> dict[str, str]:
    return {f"references/{rel}": conteudo for rel, conteudo in textos.items() if rel != "SKILL.md"}


def salvar_arquivo(
    skill_id: str, caminho: str, texto: str, *, texto_lido: str | None = None, por: str = ""
) -> dict[str, Any]:
    """Regrava um arquivo da skill, conferindo a skill inteira antes de gravar.

    `texto_lido` é o arquivo como estava quando a pessoa abriu: se alguém o mudou
    desde então, nada é gravado. Alterações de outras pessoas em OUTROS arquivos
    são preservadas (a skill é relida na hora de gravar).

    Editar a skill do sistema grava a `COPIA_EDITAVEL`; se era ela a do escritório,
    a cópia passa a valer no lugar dela.
    """
    from . import peticao_skill_arquivos

    caminho = _caminho_editavel(caminho)
    if len(texto) > _MAX_TEXTO:
        raise ValueError("O texto passou do limite de 300 mil caracteres.")
    rotulo = "Observações" if caminho == peticao_skill_arquivos.OBSERVACOES else (
        caminho if caminho == "SKILL.md" else f"references/{caminho}"
    )
    for tentativa in range(3):
        skill = _para_editar(skill_id)
        em_uso = ativa_do_escritorio().id
        if skill.id == PADRAO and em_uso != PADRAO:
            raise skills_juridicas.AlteradaNoMeioTempo(
                "A skill em uso mudou enquanto você editava. Recarregue a página e refaça a alteração."
            )
        if caminho not in skill.textos and caminho != peticao_skill_arquivos.OBSERVACOES:
            raise ValueError("Esse arquivo não existe na skill.")
        if texto_lido is not None and skill.textos.get(caminho, "") != texto_lido:
            raise skills_juridicas.AlteradaNoMeioTempo(
                f"Outra pessoa alterou {rotulo} enquanto você editava. Nada foi gravado: copie o seu texto, "
                "recarregue a página e junte as duas versões."
            )
        skill.textos[caminho] = texto
        verificacao = verificar(skill.textos)
        if not verificacao["ok"]:
            raise ValueError("A alteração não foi gravada: " + " ".join(verificacao["problemas"]))
        destino, nome, descricao = skill.id, skill.nome, skill.descricao
        if skill.id == PADRAO:
            destino = COPIA_EDITAVEL
            nome = "Skill do escritório (editada a partir da padrão)"
            descricao = "Cópia da skill padrão do sistema, editada pelo escritório na tela Skills."
        try:
            skills_juridicas.gravar_textos(
                destino, nome, descricao, skill.textos["SKILL.md"], _em_pacote(skill.textos),
                motivo=f"{rotulo} alterado na tela", por=por,
                lida_em=skill.lida_em if skill.id != PADRAO else None,
            )
            break
        except skills_juridicas.AlteradaNoMeioTempo:
            if tentativa == 2:
                raise
            # Outra gravação entrou entre a leitura e a escrita: relê e reaplica só este arquivo.
    log.info("skill de petição %s: %s editado por %s", destino, caminho, por or "?")
    esquecer()
    if em_uso == skill.id and destino != skill.id:
        return ativar(destino, por=por)
    return estado()


def historico(skill_id: str = "") -> dict[str, Any]:
    """As gravações da skill (vazio = a do escritório), da mais nova para a mais antiga."""
    skill_id = skill_id.strip() or ativa_do_escritorio().id
    if skill_id == PADRAO:
        return {"skill_id": PADRAO, "do_sistema": True, "versoes": []}
    return {"skill_id": skill_id, "do_sistema": False, "versoes": skills_juridicas.versoes(skill_id)}


def restaurar(skill_id: str, versao_id: int, *, por: str = "") -> dict[str, Any]:
    """Volta a skill para uma versão do histórico. A restauração vira uma versão nova."""
    skill = _para_editar(skill_id)
    if skill.id == PADRAO:
        raise ValueError("A skill padrão do sistema não tem histórico: ela nunca é alterada.")
    registro = skills_juridicas.versao(skill.id, versao_id)
    if not registro:
        raise ValueError("Versão não encontrada.")
    textos = textos_do_registro(registro)
    verificacao = verificar(textos)
    if not verificacao["ok"]:
        raise ValueError(_mensagem_de_recusa(verificacao))
    gravada_em = str(registro["gravado_em"])[:16]
    skills_juridicas.gravar_textos(
        skill.id, skill.nome, skill.descricao, textos["SKILL.md"], _em_pacote(textos),
        motivo=f"Restaurada a versão de {gravada_em}", por=por,
    )
    log.info("skill de petição %s restaurada para a versão %s por %s", skill.id, versao_id, por or "?")
    esquecer()
    return estado()


def pacote(skill_id: str | None = None) -> tuple[bytes, str]:
    """A skill como `.skill.zip`, pronta para editar e enviar de volta."""
    skill_id = (skill_id or "").strip() or PADRAO
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zipado:
        if skill_id == PADRAO:
            for caminho in sorted(_PASTA_PADRAO.rglob("*")):
                if caminho.is_file() and "__pycache__" not in caminho.parts:
                    zipado.write(caminho, f"{PADRAO}/{caminho.relative_to(_PASTA_PADRAO).as_posix()}")
            if not (_PASTA_PADRAO / "assets").is_dir() and _LOGO_PADRAO.is_file():
                zipado.write(_LOGO_PADRAO, f"{PADRAO}/assets/logo.png")
        else:
            registro = skills_juridicas.obter(skill_id)
            if not registro:
                raise ValueError("Skill não encontrada.")
            for relativo, texto in textos_do_registro(registro).items():
                destino = relativo if relativo == "SKILL.md" else f"references/{relativo}"
                zipado.writestr(f"{skill_id}/{destino}", texto)
            for caminho, _, dados in skills_juridicas.assets(skill_id):
                partes = caminho.split("/")
                relativo = "/".join(partes[partes.index("assets"):]) if "assets" in partes else caminho
                zipado.writestr(f"{skill_id}/{relativo}", dados)
    return saida.getvalue(), f"{skill_id}.skill.zip"
