/* ============================================================================
   EmpStats — Complete Database Setup
   Run this script once on a fresh SQL Server instance.
   ============================================================================ */

/* ── Create database ─────────────────────────────────────────────────────── */
IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE name = 'EmpStats')
BEGIN
    CREATE DATABASE EmpStats;
    PRINT 'Created database EmpStats';
END
ELSE
    PRINT 'Database EmpStats already exists';
GO

USE EmpStats;
GO

SET NOCOUNT ON;
GO

/* ============================================================================
   1. employee_identity — The ONLY table with real PII.
      Maps real employee_id / name / designation / title to an opaque_id.
      Snapshot table: same opaque_id across months, but name/title can change.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'employee_identity')
BEGIN
    CREATE TABLE dbo.employee_identity (
        opaque_id       VARCHAR(10)     NOT NULL,
        year            INT             NOT NULL,
        month           INT             NOT NULL,
        employee_id     VARCHAR(20)     NOT NULL,
        employee_name   NVARCHAR(100)   NOT NULL,
        designation     NVARCHAR(150)   NULL,
        title           NVARCHAR(100)   NULL,
        CONSTRAINT pk_employee_identity PRIMARY KEY (opaque_id, year, month)
    );
    CREATE INDEX ix_ei_empid ON dbo.employee_identity (employee_id);
    CREATE INDEX ix_ei_name  ON dbo.employee_identity (employee_name);
    PRINT 'Created table employee_identity';
END
GO

/* ============================================================================
   2. employees — Monthly snapshots, NO PII.
      All columns from CSV except employee_name, designation, title, and the
      dropped manager columns (team_leader, reviewer, functional_head, cxo).
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'employees')
BEGIN
    CREATE TABLE dbo.employees (
        opaque_id               VARCHAR(10)     NOT NULL,
        year                    INT             NOT NULL,
        month                   INT             NOT NULL,
        sr_no                   INT             NULL,
        location                NVARCHAR(100)   NULL,
        date_of_joining         DATE            NULL,
        technova_experience     FLOAT           NULL,
        outside_experience      FLOAT           NULL,
        total_experience        FLOAT           NULL,
        total_experience_range  VARCHAR(20)     NULL,
        date_of_birth           DATE            NULL,
        age                     INT             NULL,
        age_range               VARCHAR(20)     NULL,
        gender                  VARCHAR(10)     NULL,
        core_group              NVARCHAR(100)   NULL,
        super_function          NVARCHAR(100)   NULL,
        [function]              NVARCHAR(100)   NULL,
        division                NVARCHAR(100)   NULL,
        vertical                NVARCHAR(100)   NULL,
        [role]                  NVARCHAR(100)   NULL,
        role_function           NVARCHAR(100)   NULL,
        employee_category       NVARCHAR(50)    NULL,
        employee_sub_category   NVARCHAR(50)    NULL,
        band                    VARCHAR(20)     NULL,
        [level]                 VARCHAR(20)     NULL,
        basic_qualification     NVARCHAR(150)   NULL,
        other_qualifications    NVARCHAR(250)   NULL,
        qualification_category  NVARCHAR(100)   NULL,
        zone                    NVARCHAR(50)    NULL,
        budget_code             VARCHAR(50)     NULL,
        blood_group             VARCHAR(10)     NULL,
        level_code              VARCHAR(20)     NULL,
        sub_sect                NVARCHAR(50)    NULL,
        city                    NVARCHAR(50)    NULL,
        pin_code                VARCHAR(10)     NULL,
        [state]                 NVARCHAR(50)    NULL,
        CONSTRAINT pk_employees PRIMARY KEY (opaque_id, year, month),
        CONSTRAINT fk_emp_identity FOREIGN KEY (opaque_id, year, month)
            REFERENCES dbo.employee_identity (opaque_id, year, month)
    );
    CREATE INDEX ix_emp_yrmo ON dbo.employees (opaque_id, year DESC, month DESC);
    PRINT 'Created table employees';
END
GO

/* ============================================================================
   3. health_records — AHC data, NO PII.
      Dropped: email, phone, relative_id, relationship, sponsor_id,
      insurer_id, health_id, plan_number, policy_start_date, policy_end_date,
      product_name, raw_package_name, customer_name.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'health_records')
BEGIN
    CREATE TABLE dbo.health_records (
        ahc_id                      BIGINT          PRIMARY KEY,
        case_id                     BIGINT          NULL,
        application_id              BIGINT          NULL,
        user_id                     BIGINT          NULL,
        opaque_id                   VARCHAR(10)     NOT NULL,
        gender                      VARCHAR(10)     NULL,
        age_group                   VARCHAR(20)     NULL,
        city                        NVARCHAR(50)    NULL,
        [state]                     NVARCHAR(50)    NULL,
        dc_name                     NVARCHAR(150)   NULL,
        appointment_booked_on       DATETIME        NULL,
        appointment_completed_on    DATETIME        NULL,
        reports_upload_on           DATETIME        NULL,
        overall_health_score        INT             NULL,
        overall_risk_category       VARCHAR(50)     NULL,
        risk_stage                  INT             NULL,
        cardiac_stage               VARCHAR(50)     NULL,
        blood_stage                 VARCHAR(50)     NULL,
        hepatic_stage               VARCHAR(50)     NULL,
        renal_stage                 VARCHAR(50)     NULL,
        diabetic_stage              VARCHAR(50)     NULL,
        vitamind_stage              VARCHAR(50)     NULL,
        thyroid_stage               VARCHAR(50)     NULL,
        cancer_stage                VARCHAR(50)     NULL,
        parameter_name              NVARCHAR(200)   NULL,
        value                       FLOAT           NULL,
        value_unit                  VARCHAR(50)     NULL,
        normal_range                VARCHAR(100)    NULL,
        risk_level                  VARCHAR(50)     NULL,
        category                    VARCHAR(100)    NULL,
        normal                      VARCHAR(5)      NULL,
        low_risk                    VARCHAR(5)      NULL,
        medium_risk                 VARCHAR(5)      NULL,
        high_risk                   VARCHAR(5)      NULL,
        rn                          INT             NULL,
        report_year                 INT             NULL
    );
    CREATE INDEX ix_hr_opaque_year ON dbo.health_records (opaque_id, report_year DESC);
    CREATE INDEX ix_hr_risk        ON dbo.health_records (risk_level, parameter_name);
    PRINT 'Created table health_records';
END
GO

/* ============================================================================
   4. employee_profiles — Persistent patient background (doctor-entered).
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'employee_profiles')
BEGIN
    CREATE TABLE dbo.employee_profiles (
        id                  INT IDENTITY(1,1)   PRIMARY KEY,
        opaque_id           VARCHAR(10)         NOT NULL UNIQUE,
        blood_group         VARCHAR(10)         NULL,
        family_history      NVARCHAR(MAX)       NULL,
        allergies           NVARCHAR(MAX)       NULL,
        chronic_conditions  NVARCHAR(MAX)       NULL,
        updated_at          DATETIME            NOT NULL
            DEFAULT (DATEADD(MINUTE, 330, GETUTCDATE()))
    );
    PRINT 'Created table employee_profiles';
END
GO

/* ============================================================================
   5. consultations — Doctor visit records, NO PII (no employee_name).
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'consultations')
BEGIN
    CREATE TABLE dbo.consultations (
        id                      INT IDENTITY(1,1)   PRIMARY KEY,
        opaque_id               VARCHAR(10)         NOT NULL,
        visit_date              DATE                NOT NULL,
        doctor_name             NVARCHAR(100)       NULL,
        bp                      VARCHAR(20)         NULL,
        pulse                   VARCHAR(10)         NULL,
        weight                  VARCHAR(10)         NULL,
        height                  VARCHAR(10)         NULL,
        bmi                     VARCHAR(10)         NULL,
        complaint               NVARCHAR(MAX)       NULL,
        diagnosis               NVARCHAR(MAX)       NULL,
        prev_medicine_history   NVARCHAR(MAX)       NULL,
        diet                    NVARCHAR(MAX)       NULL,
        exercise                NVARCHAR(MAX)       NULL,
        follow_up_date          DATE                NULL,
        referral                NVARCHAR(200)       NULL,
        goal_notes              NVARCHAR(MAX)       NULL,
        goal_doctor_score       INT                 NULL,
        progress_verdict        VARCHAR(20)         NULL,
        progress_note           NVARCHAR(500)       NULL,
        new_checkup_reports     NVARCHAR(MAX)       NULL,
        created_at              DATETIME            NOT NULL
            DEFAULT (DATEADD(MINUTE, 330, GETUTCDATE())),
        CONSTRAINT ck_progress_verdict
            CHECK (progress_verdict IS NULL
                   OR progress_verdict IN ('improved', 'no_change', 'worsened'))
    );
    CREATE INDEX ix_cons_opaque_date ON dbo.consultations (opaque_id, visit_date DESC);
    CREATE INDEX ix_cons_visit       ON dbo.consultations (visit_date DESC);
    PRINT 'Created table consultations';
END
GO

/* ============================================================================
   6. medicines — FK cascade to consultations.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'medicines')
BEGIN
    CREATE TABLE dbo.medicines (
        id                  INT IDENTITY(1,1)   PRIMARY KEY,
        consultation_id     INT                 NOT NULL,
        name                NVARCHAR(200)       NULL,
        dose                VARCHAR(100)        NULL,
        frequency           VARCHAR(100)        NULL,
        duration            VARCHAR(100)        NULL,
        CONSTRAINT fk_med_consultation
            FOREIGN KEY (consultation_id)
            REFERENCES dbo.consultations(id) ON DELETE CASCADE
    );
    CREATE INDEX ix_meds_con ON dbo.medicines (consultation_id);
    PRINT 'Created table medicines';
END
GO

/* ============================================================================
   7. consultation_readings — Structured readings with risk scoring.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'consultation_readings')
BEGIN
    CREATE TABLE dbo.consultation_readings (
        id                  INT IDENTITY(1,1)   PRIMARY KEY,
        consultation_id     INT                 NOT NULL,
        opaque_id           VARCHAR(10)         NOT NULL,
        parameter_name      NVARCHAR(200)       NOT NULL,
        value               FLOAT               NOT NULL,
        unit                NVARCHAR(50)        NULL,
        normal_range        NVARCHAR(100)       NULL,
        reading_date        DATE                NOT NULL,
        risk_level          VARCHAR(50)         NULL,
        risk_override       BIT                 NOT NULL DEFAULT 0,
        created_at          DATETIME            NOT NULL
            DEFAULT (DATEADD(MINUTE, 330, GETUTCDATE())),
        CONSTRAINT fk_cread_consultation
            FOREIGN KEY (consultation_id)
            REFERENCES dbo.consultations(id) ON DELETE CASCADE
    );
    CREATE INDEX ix_cread_opaque_param  ON dbo.consultation_readings (opaque_id, parameter_name, reading_date DESC);
    CREATE INDEX ix_cread_date          ON dbo.consultation_readings (reading_date DESC);
    PRINT 'Created table consultation_readings';
END
GO

/* ============================================================================
   8. goals — Health goals set by doctor.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'goals')
BEGIN
    CREATE TABLE dbo.goals (
        id                          INT IDENTITY(1,1)   PRIMARY KEY,
        consultation_id             INT                 NOT NULL,
        opaque_id                   VARCHAR(10)         NOT NULL,
        goal_type                   VARCHAR(50)         NULL,
        custom_text                 NVARCHAR(200)       NULL,
        target_value                VARCHAR(100)        NULL,
        target_date                 DATE                NULL,
        status                      VARCHAR(20)         NOT NULL DEFAULT 'open',
        set_on                      DATE                NULL,
        closed_on                   DATE                NULL,
        closed_in_consultation_id   INT                 NULL,
        points                      INT                 NULL,
        CONSTRAINT fk_goal_consultation
            FOREIGN KEY (consultation_id)
            REFERENCES dbo.consultations(id),
        CONSTRAINT fk_goal_closed_con
            FOREIGN KEY (closed_in_consultation_id)
            REFERENCES dbo.consultations(id)
    );
    CREATE INDEX ix_goals_opaque_status ON dbo.goals (opaque_id, status);
    CREATE INDEX ix_goals_status        ON dbo.goals (status, set_on DESC);
    CREATE INDEX ix_goals_closed_con    ON dbo.goals (closed_in_consultation_id);
    PRINT 'Created table goals';
END
GO

/* ============================================================================
   9. users — Authentication.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'users')
BEGIN
    CREATE TABLE dbo.users (
        id              INT IDENTITY(1,1)   PRIMARY KEY,
        username        VARCHAR(50)         NOT NULL UNIQUE,
        [role]          VARCHAR(20)         NOT NULL,
        password_hash   VARCHAR(255)        NOT NULL
    );
    PRINT 'Created table users';
END
GO

/* ============================================================================
   10. goal_types — Reference table for health goal categories.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'goal_types')
BEGIN
    CREATE TABLE dbo.goal_types (
        id          INT IDENTITY(1,1)   PRIMARY KEY,
        name        NVARCHAR(100)       NOT NULL UNIQUE,
        is_active   BIT                 NOT NULL DEFAULT 1
    );
    PRINT 'Created table goal_types';
END
GO

/* ============================================================================
   11. checkup_types — Reference table for checkup parameters.
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'checkup_types')
BEGIN
    CREATE TABLE dbo.checkup_types (
        id              INT IDENTITY(1,1)   PRIMARY KEY,
        name            NVARCHAR(200)       NOT NULL UNIQUE,
        unit            NVARCHAR(50)        NULL,
        normal_range    NVARCHAR(100)       NULL,
        is_active       BIT                 NOT NULL DEFAULT 1,
        created_at      DATETIME            NOT NULL
            DEFAULT (DATEADD(MINUTE, 330, GETUTCDATE()))
    );
    PRINT 'Created table checkup_types';
END
GO

/* ============================================================================
   12. Seed users — Doctor, HR, Organisation, Admin
   ============================================================================ */
IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE username = 'Admin')
BEGIN
    INSERT INTO dbo.users (username, [role], password_hash) VALUES
        ('Doctor',       'doctor', '$2b$12$Yq4kJKmFN4XB4i3sJWmAWOv.n58MyKF3wS0udOQPEbJxqc0rz5fyC'),
        ('HR',           'hr',     '$2b$12$n0PWWqf7VteAwmumbtQb0OzTzLeblkZ2dZ4nVF3oYJ1gcXAsNvpU2'),
        ('Organisation', 'org',    '$2b$12$xm2.d3rzBIHMvo1Le/AijuiciUqEhgYFqa1eUiofn5MdD9EzNl8vG'),
        ('Admin',        'admin',  '$2b$12$J9RzsR7keAjKuNmWZeZBcO2V7YX9bb3cQFK.ZEdwtUt5Uxdg3GTiC');
    PRINT 'Seeded 4 default users';
END
ELSE
    PRINT 'Users already seeded — skipping';
GO

/* ============================================================================
   Verify
   ============================================================================ */
SELECT t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0,1)
GROUP BY t.name
ORDER BY t.name;
GO

PRINT 'EmpStats database setup complete.';
GO
