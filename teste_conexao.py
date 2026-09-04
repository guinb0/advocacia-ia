#!/usr/bin/env python3
"""Teste de conexão com bancos de dados PostgreSQL."""

import os
import sys
from pathlib import Path

# Carregar .env manualmente
def load_env():
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().strip().split("\n"):
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if key.strip():
                    os.environ[key.strip()] = value.strip()

load_env()

# Importar psycopg
try:
    import psycopg
    from psycopg import sql
except ImportError:
    print("❌ psycopg não instalado. Instalando...")
    os.system("pip install psycopg[binary]")
    import psycopg

def test_connection(url: str, name: str) -> bool:
    """Testa conexão com um banco PostgreSQL."""
    print(f"\n🔍 Testando {name}...")
    print(f"   URL: {url[:50]}...")
    
    try:
        conn = psycopg.connect(url, connect_timeout=10)
        cursor = conn.cursor()
        
        # Test basic query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"   ✅ Conexão OK")
        print(f"   📊 PostgreSQL: {version[:80]}")
        
        # Test database
        cursor.execute("SELECT current_database();")
        db = cursor.fetchone()[0]
        print(f"   📁 Database: {db}")
        
        # Test user
        cursor.execute("SELECT current_user;")
        user = cursor.fetchone()[0]
        print(f"   👤 Usuário: {user}")
        
        # Test table count
        cursor.execute("""
            SELECT count(*) FROM information_schema.tables 
            WHERE table_schema = 'public';
        """)
        table_count = cursor.fetchone()[0]
        print(f"   📋 Tabelas: {table_count}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"   ❌ Erro: {type(e).__name__}: {e}")
        return False


def main():
    """Executa testes de conexão."""
    print("=" * 70)
    print("🧪 TESTE DE CONEXÃO - PostgreSQL")
    print("=" * 70)
    
    results = {}
    
    # Test DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        results["DATABASE_URL (advocacia_ia)"] = test_connection(db_url, "DATABASE_URL (advocacia_ia)")
    else:
        print("❌ DATABASE_URL não configurada")
        results["DATABASE_URL"] = False
    
    # Test JOBS_DATABASE_URL
    jobs_url = os.getenv("JOBS_DATABASE_URL")
    if jobs_url:
        results["JOBS_DATABASE_URL (advocacia_jobs)"] = test_connection(jobs_url, "JOBS_DATABASE_URL (advocacia_jobs)")
    else:
        print("❌ JOBS_DATABASE_URL não configurada")
        results["JOBS_DATABASE_URL"] = False
    
    # Test JURIMETRIA_DATABASE_URL
    juri_url = os.getenv("JURIMETRIA_DATABASE_URL")
    if juri_url:
        results["JURIMETRIA_DATABASE_URL (juri)"] = test_connection(juri_url, "JURIMETRIA_DATABASE_URL (juri)")
    else:
        print("❌ JURIMETRIA_DATABASE_URL não configurada")
        results["JURIMETRIA_DATABASE_URL"] = False
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 RESUMO")
    print("=" * 70)
    
    for name, success in results.items():
        status = "✅ OK" if success else "❌ FALHA"
        print(f"{status:6} {name}")
    
    all_ok = all(results.values())
    print("\n" + "=" * 70)
    if all_ok:
        print("✅ TODOS OS TESTES PASSARAM!")
    else:
        print("❌ ALGUNS TESTES FALHARAM")
    print("=" * 70)
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
