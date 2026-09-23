-- ============================================================================
-- Resource Utilization Reporting System - Production SQL Server Schema
-- Supports Ingestion, Task Auditing, Dynamic AI Analytics, and Performance Indexes
-- ============================================================================

IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = N'ResourceUtilizationDB')
BEGIN
    CREATE DATABASE [ResourceUtilizationDB];
END
GO

USE [ResourceUtilizationDB];
GO

-- 1. UPLOADS AUDIT TABLE
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[uploads]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[uploads] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id] NVARCHAR(100) NOT NULL,
        [filename] NVARCHAR(500) NULL,
        [period_label] NVARCHAR(255) NULL,
        [uploaded_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL,
        [employee_hint] NVARCHAR(255) NULL,
        [row_count] INT NULL
    );
END
GO

-- 2. INGESTED TASKS TABLE
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[tasks]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[tasks] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id] NVARCHAR(100) NOT NULL,
        [upload_id] INT NULL,
        [date] NVARCHAR(50) NULL,
        [service] NVARCHAR(255) NULL,
        [employee] NVARCHAR(255) NULL,
        [task] NVARCHAR(500) NULL,
        [description] NVARCHAR(MAX) NULL,
        [status] NVARCHAR(100) NULL,
        [expected_hrs] FLOAT NULL,
        [actual_hrs] FLOAT NULL,
        [task_type] NVARCHAR(255) NULL,
        [stack] NVARCHAR(255) NULL,
        [priority] NVARCHAR(100) NULL,
        [start_date] NVARCHAR(50) NULL,
        [end_date] NVARCHAR(50) NULL,
        [week] NVARCHAR(100) NULL,
        [university] NVARCHAR(255) NULL,
        [created_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
    );
END
GO

-- 3. NORMALIZATION LOG AUDIT TABLE
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[normalization_log]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[normalization_log] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id] NVARCHAR(100) NOT NULL,
        [field_name] NVARCHAR(100) NULL,
        [raw_value] NVARCHAR(500) NULL,
        [normalized_value] NVARCHAR(500) NULL,
        [row_count_affected] INT NULL,
        [logged_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
    );
END
GO

-- 4. GENERATED REPORTS TABLE
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[reports]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[reports] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id] NVARCHAR(100) NOT NULL,
        [period_label] NVARCHAR(255) NULL,
        [cadence] NVARCHAR(50) DEFAULT 'monthly' NULL,
        [summary_json] NVARCHAR(MAX) NULL,
        [variance_json] NVARCHAR(MAX) NULL,
        [ai_insights_json] NVARCHAR(MAX) NULL,
        [excel_path] NVARCHAR(1000) NULL,
        [pdf_path] NVARCHAR(1000) NULL,
        [generated_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
    );
END
GO

-- 5. SYSTEM SETTINGS TABLE
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[settings]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[settings] (
        [key] NVARCHAR(100) NOT NULL PRIMARY KEY,
        [value] NVARCHAR(MAX) NULL,
        [updated_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
    );
END
GO

-- INDEXES
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_reports_gen' AND object_id = OBJECT_ID('[dbo].[reports]'))
    CREATE NONCLUSTERED INDEX [IX_reports_gen] ON [dbo].[reports]([generated_at] DESC);

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_session' AND object_id = OBJECT_ID('[dbo].[tasks]'))
    CREATE NONCLUSTERED INDEX [IX_tasks_session] ON [dbo].[tasks]([session_id]);

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_emp' AND object_id = OBJECT_ID('[dbo].[tasks]'))
    CREATE NONCLUSTERED INDEX [IX_tasks_emp] ON [dbo].[tasks]([employee]);
GO
