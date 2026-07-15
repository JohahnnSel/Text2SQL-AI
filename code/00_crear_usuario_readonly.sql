/* ============================================================
   Usuario de SOLO LECTURA para la capa Text-to-SQL
   Ejecutar en SSMS, conectado como admin, una sola vez.
   La API nunca debe conectarse con tu usuario de admin.
   ============================================================ */

USE GastosRRHH;
GO

-- 1) Login a nivel de servidor (cambiar la contraseña por una fuerte,
--    y que coincida con SQL_READONLY_PASSWORD en tu .env)
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'text2sql_reader')
BEGIN
    CREATE LOGIN text2sql_reader WITH PASSWORD = 'CambiaEstaClave!2026';
END
GO

-- 2) Usuario a nivel de base de datos, ligado al login
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'text2sql_reader')
BEGIN
    CREATE USER text2sql_reader FOR LOGIN text2sql_reader;
END
GO

-- 3) Solo lectura. Nada de db_datawriter, db_ddladmin ni db_owner.
ALTER ROLE db_datareader ADD MEMBER text2sql_reader;
GO

-- 4) Denegar explícitamente permisos de escritura/estructura, como cinturón
--    de seguridad además del rol (defensa en profundidad: aunque alguien
--    agregue el usuario a otro rol por error, esto bloquea).
--    OJO: nunca incluir CONTROL acá. CONTROL es el permiso máximo sobre la
--    base de datos e implica TODOS los demás, incluida la posibilidad de
--    conectarse. Denegarlo bloquea el acceso completo (error 4060 "Cannot
--    open database"), no solo la escritura -- ya nos pasó una vez.
DENY INSERT, UPDATE, DELETE, ALTER ON DATABASE::GastosRRHH TO text2sql_reader;
GO

-- Verificación: debería devolver una fila con text2sql_reader / db_datareader
SELECT
    dp.name AS usuario,
    dp.type_desc,
    r.name AS rol
FROM sys.database_role_members drm
JOIN sys.database_principals dp ON drm.member_principal_id = dp.principal_id
JOIN sys.database_principals r ON drm.role_principal_id = r.principal_id
WHERE dp.name = 'text2sql_reader';
