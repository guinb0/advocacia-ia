-- SQL Server (não pgvector). Registro do schema; app/tactiq.py::inicializar() aplica o mesmo comando.
-- Guarda o client OAuth do fluxo em andamento sem apagar os tokens da conexão ativa.
IF COL_LENGTH('dbo.acervo_tactiq_conexoes', 'pendente_client_id') IS NULL
    ALTER TABLE dbo.acervo_tactiq_conexoes ADD pendente_client_id nvarchar(300) NULL;
