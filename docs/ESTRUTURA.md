# Estrutura do projeto

| Diretório | Responsabilidade |
|---|---|
| `app/` | API FastAPI e regras de negócio |
| `app/agente/` | Integração com o agente jurídico e dossiê |
| `frontend/` | Interface Next.js |
| `frontend/src/components/entrevista/` | Entrevista, roteiro, revisão e gravação |
| `frontend/src/components/documentacao/` | Fila e atendimento da documentação |
| `tests/` | Testes automatizados do backend |
| `docs/` | Documentação funcional e operacional |
| `scripts/` | Importações, migrações e rotinas administrativas |
| `sql/` | Consultas e migrações SQL |
| `observability/` | Prometheus, Grafana e coleta de logs |
| `static/` | Recursos estáticos do backend |
| `dados/` | Dados locais e documentos; não versionados |
| `logs/` | Saídas locais dos serviços; não versionadas |
| `tmp/` | Arquivos temporários; não versionados |

## Convenções

- Backend novo fica em `app/`, separado por domínio.
- Interface fica em `frontend/src/`; não recriar as pastas legadas
  `frontend/components`, `frontend/lib` ou `frontend/app`.
- Arquivos gerados, logs e estados de workers nunca ficam na raiz nem entram no Git.
- Segredos ficam somente no `.env`; `NEXT_PUBLIC_` nunca recebe chaves privadas.
- Documentos de arquitetura e operação ficam em `docs/`.

O projeto foi achatado na raiz do repositório; não existe mais uma pasta
intermediária para o antigo extrator de OCR.
