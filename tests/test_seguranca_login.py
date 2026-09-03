import time

import pytest
from fastapi import HTTPException

from app import auth, usuarios


def test_senha_nova_usa_pbkdf2_com_sal_e_aceita_contrato_md5():
    credencial_md5 = usuarios._md5("uma senha longa e segura")
    primeiro = usuarios._hash_de(credencial_md5)
    segundo = usuarios._hash_de(credencial_md5)

    assert primeiro.startswith("pbkdf2_sha256$600000$")
    assert primeiro != segundo
    assert usuarios._verificar_senha(primeiro, credencial_md5)
    assert not usuarios._verificar_senha(primeiro, usuarios._md5("outra senha"))


def test_hash_md5_legado_continua_valido_para_migracao():
    legado = usuarios._md5("senha anterior")

    assert usuarios._verificar_senha(legado, legado)
    assert not usuarios._verificar_senha(legado, usuarios._md5("senha errada"))


def test_senha_padrao_e_detectada_mesmo_depois_do_pbkdf2():
    salvo = usuarios._hash_de(auth.SENHA_PADRAO_MD5)

    assert usuarios._senha_padrao(salvo)


def test_limite_por_conta_recusa_excesso(monkeypatch):
    monkeypatch.setattr(usuarios, "_tentativas_conta", {})
    monkeypatch.setattr(usuarios, "_tentativas_ip", {})
    agora = time.monotonic()
    usuarios._tentativas_conta["pessoa@example.com"] = [
        agora for _ in range(usuarios._LOGIN_MAX_CONTA)
    ]

    with pytest.raises(HTTPException) as erro:
        usuarios._conferir_limite_login("pessoa@example.com", "203.0.113.5")

    assert erro.value.status_code == 429
