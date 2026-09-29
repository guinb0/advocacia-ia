IF DB_ID(N'$(database)') IS NULL
BEGIN
    EXEC(N'CREATE DATABASE [$(database)]');
END;
