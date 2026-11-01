-- =====================================================================
--  Class codes (course QR join). For databases created before the
--  columns were added to 01_schema.sql; fresh installs already have them.
--  Run as the DBA user against attendance_db (and attendance_test).
-- =====================================================================
ALTER TABLE courses
  ADD COLUMN join_code CHAR(6) NULL COMMENT 'class code students scan (QR) or type to join' AFTER teacher_id,
  ADD COLUMN join_open BOOLEAN NOT NULL DEFAULT TRUE AFTER join_code,
  ADD CONSTRAINT uq_courses_join_code UNIQUE (join_code);
