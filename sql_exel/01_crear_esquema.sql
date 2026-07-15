/* ============================================================
   NetOps Analytics — Esquema copo de nieve (Gastos RRHH)
   Base: SQL Server
   Ejecutar una sola vez antes de correr migrate_excel_to_sql.py
   ============================================================ */

IF DB_ID('GastosRRHH') IS NULL
BEGIN
    CREATE DATABASE GastosRRHH;
END
GO

USE GastosRRHH;
GO

-- Orden de creación pensado para las FKs (padres primero)

IF OBJECT_ID('dbo.Gastos', 'U') IS NOT NULL DROP TABLE dbo.Gastos;
IF OBJECT_ID('dbo.Empleados', 'U') IS NOT NULL DROP TABLE dbo.Empleados;
IF OBJECT_ID('dbo.Departamentos', 'U') IS NOT NULL DROP TABLE dbo.Departamentos;
IF OBJECT_ID('dbo.Conceptos', 'U') IS NOT NULL DROP TABLE dbo.Conceptos;
GO

-- ------------------------------------------------------------
-- CONCEPTOS (dimensión simple)
-- ------------------------------------------------------------
CREATE TABLE dbo.Conceptos (
    cod_concepto    INT             NOT NULL PRIMARY KEY,
    concepto        NVARCHAR(100)   NOT NULL,
    iva             DECIMAL(5,4)    NOT NULL
);
GO

-- ------------------------------------------------------------
-- DEPARTAMENTOS (clave compuesta: el copo de nieve real del
-- dataset — cada depto tiene una fila distinta por jornada,
-- con su propio plazo_pago y extra)
-- ------------------------------------------------------------
CREATE TABLE dbo.Departamentos (
    cod_dpto        INT             NOT NULL,
    jornada         NVARCHAR(20)    NOT NULL,
    nombre_dpto     NVARCHAR(100)   NOT NULL,
    plazo_pago      INT             NOT NULL,
    extra           DECIMAL(5,4)    NOT NULL,
    CONSTRAINT PK_Departamentos PRIMARY KEY (cod_dpto, jornada)
);
GO

-- ------------------------------------------------------------
-- EMPLEADOS (FK compuesta hacia Departamentos)
-- NIF y fecha_nacimiento admiten NULL: así vienen en el Excel
-- ------------------------------------------------------------
CREATE TABLE dbo.Empleados (
    cod_empleado         VARCHAR(10)    NOT NULL PRIMARY KEY,
    nombre               NVARCHAR(100)  NOT NULL,
    apellidos            NVARCHAR(150)  NOT NULL,
    fecha_incorporacion  DATE           NOT NULL,
    cod_dpto             INT            NOT NULL,
    jornada              NVARCHAR(20)   NOT NULL,
    tipo_contrato        NVARCHAR(50)   NOT NULL,
    sexo                 NVARCHAR(10)   NOT NULL,
    casado               BIT            NOT NULL,
    fecha_nacimiento     DATE           NULL,
    nif                  VARCHAR(20)    NULL,
    CONSTRAINT FK_Empleados_Departamentos
        FOREIGN KEY (cod_dpto, jornada)
        REFERENCES dbo.Departamentos (cod_dpto, jornada)
);
GO

-- ------------------------------------------------------------
-- GASTOS (tabla de hechos, ~50.000 filas)
-- fecha_pagado es NULL mientras pagado = 0
-- ------------------------------------------------------------
CREATE TABLE dbo.Gastos (
    num_gasto       INT             NOT NULL PRIMARY KEY,
    cod_concepto    INT             NOT NULL,
    cod_empleado    VARCHAR(10)     NOT NULL,
    fecha_gasto     DATE            NOT NULL,
    importe         DECIMAL(10,4)   NOT NULL,
    pagado          BIT             NOT NULL,
    fecha_pagado    DATE            NULL,
    CONSTRAINT FK_Gastos_Conceptos
        FOREIGN KEY (cod_concepto) REFERENCES dbo.Conceptos (cod_concepto),
    CONSTRAINT FK_Gastos_Empleados
        FOREIGN KEY (cod_empleado) REFERENCES dbo.Empleados (cod_empleado)
);
GO

-- Índices para acelerar las consultas típicas de BI / Text-to-SQL
CREATE INDEX IX_Gastos_fecha_gasto ON dbo.Gastos (fecha_gasto);
CREATE INDEX IX_Gastos_cod_empleado ON dbo.Gastos (cod_empleado);
CREATE INDEX IX_Empleados_cod_dpto_jornada ON dbo.Empleados (cod_dpto, jornada);
GO
