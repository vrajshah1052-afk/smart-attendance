-- =====================================================================
--  Smart Face Recognition Attendance System
--  MySQL 8 schema: tables, constraints, indexes, views, procedures, triggers
--  Executed automatically by the mysql:8.0 image on first start.
--  Normal form: 3NF (see README "Normalisation" for the justification).
-- =====================================================================

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS attendance_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE attendance_db;

-- ---------------------------------------------------------------------
-- app_meta: tiny key/value table for schema version & tunable rules
-- (shortage threshold lives here so views and the API agree on it)
-- ---------------------------------------------------------------------
CREATE TABLE app_meta (
  meta_key    VARCHAR(50)  NOT NULL,
  meta_value  VARCHAR(255) NOT NULL,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_app_meta PRIMARY KEY (meta_key)
) ENGINE=InnoDB;

INSERT INTO app_meta (meta_key, meta_value) VALUES
  ('schema_version', '1.0.0'),
  ('shortage_threshold', '75');

-- ---------------------------------------------------------------------
-- branches: CS, IT, ENTC ...  (lookup table)
-- ---------------------------------------------------------------------
CREATE TABLE branches (
  branch_id  SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code       VARCHAR(10)  NOT NULL,
  name       VARCHAR(100) NOT NULL,
  CONSTRAINT pk_branches PRIMARY KEY (branch_id),
  CONSTRAINT uq_branches_code UNIQUE (code),
  CONSTRAINT chk_branches_code CHECK (REGEXP_LIKE(code, '^[A-Z]{2,10}$', 'c'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- divisions: (branch, year, division letter) -> division_id
-- Removes the transitive dependency prn -> division -> (branch, year)
-- ---------------------------------------------------------------------
CREATE TABLE divisions (
  division_id    SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  branch_id      SMALLINT UNSIGNED NOT NULL,
  year_of_study  TINYINT UNSIGNED  NOT NULL,
  name           VARCHAR(5)        NOT NULL,
  CONSTRAINT pk_divisions PRIMARY KEY (division_id),
  CONSTRAINT uq_divisions UNIQUE (branch_id, year_of_study, name),
  CONSTRAINT fk_divisions_branch FOREIGN KEY (branch_id)
    REFERENCES branches (branch_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT chk_divisions_year CHECK (year_of_study BETWEEN 1 AND 4),
  CONSTRAINT chk_divisions_name CHECK (REGEXP_LIKE(name, '^[A-Z][0-9]?$', 'c'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- students: PRN is the natural key AND the cross-database join key with
-- MongoDB (face_embeddings.prn). It is therefore immutable
-- (ON UPDATE RESTRICT everywhere).
-- ---------------------------------------------------------------------
CREATE TABLE students (
  prn            VARCHAR(20)       NOT NULL,
  full_name      VARCHAR(120)      NOT NULL,
  email          VARCHAR(150)      NOT NULL,
  phone          VARCHAR(15)       NOT NULL,
  division_id    SMALLINT UNSIGNED NOT NULL,
  roll_no        SMALLINT UNSIGNED NOT NULL,
  consent_given  BOOLEAN           NOT NULL DEFAULT FALSE,
  consent_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- PENDING acts as a "semantic lock" while the registration saga runs
  face_status    ENUM('PENDING','PENDING_APPROVAL','ENROLLED','REENROLL_REQUIRED') NOT NULL DEFAULT 'PENDING',
  created_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_students PRIMARY KEY (prn),
  CONSTRAINT uq_students_email UNIQUE (email),
  CONSTRAINT uq_students_div_roll UNIQUE (division_id, roll_no),
  CONSTRAINT fk_students_division FOREIGN KEY (division_id)
    REFERENCES divisions (division_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT chk_students_prn     CHECK (REGEXP_LIKE(prn, '^[A-Z0-9]{6,20}$', 'c')),
  CONSTRAINT chk_students_email   CHECK (REGEXP_LIKE(email, '^[^@ ]+@[^@ ]+[.][^@ ]+$')),
  CONSTRAINT chk_students_phone   CHECK (REGEXP_LIKE(phone, '^[+]?[0-9]{10,14}$')),
  CONSTRAINT chk_students_roll    CHECK (roll_no BETWEEN 1 AND 300),
  -- biometric data may only be stored with explicit consent (DPDP Act 2023 / GDPR Art. 9)
  CONSTRAINT chk_students_consent CHECK (consent_given = TRUE),
  INDEX idx_students_face_status (face_status),
  INDEX idx_students_name (full_name)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- teachers
-- ---------------------------------------------------------------------
CREATE TABLE teachers (
  teacher_id     INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  employee_code  VARCHAR(20)       NOT NULL,
  full_name      VARCHAR(120)      NOT NULL,
  email          VARCHAR(150)      NOT NULL,
  phone          VARCHAR(15)       NULL,
  branch_id      SMALLINT UNSIGNED NOT NULL,
  designation    VARCHAR(60)       NOT NULL DEFAULT 'Assistant Professor',
  created_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_teachers PRIMARY KEY (teacher_id),
  CONSTRAINT uq_teachers_code UNIQUE (employee_code),
  CONSTRAINT uq_teachers_email UNIQUE (email),
  CONSTRAINT fk_teachers_branch FOREIGN KEY (branch_id)
    REFERENCES branches (branch_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT chk_teachers_email CHECK (REGEXP_LIKE(email, '^[^@ ]+@[^@ ]+[.][^@ ]+$'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- users: authentication principal (bcrypt hash). Exactly one of
-- prn / teacher_id is linked depending on role (enforced by trigger,
-- because MySQL forbids CHECKs on columns used by FK cascade actions).
-- password_hash NULL = account not activated yet.
-- ---------------------------------------------------------------------
CREATE TABLE users (
  user_id               INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  username              VARCHAR(150)  NOT NULL,
  password_hash         VARCHAR(255)  NULL,
  role                  ENUM('ADMIN','TEACHER','STUDENT') NOT NULL,
  prn                   VARCHAR(20)   NULL,
  teacher_id            INT UNSIGNED  NULL,
  is_active             BOOLEAN       NOT NULL DEFAULT TRUE,
  must_change_password  BOOLEAN       NOT NULL DEFAULT FALSE,
  failed_logins         TINYINT UNSIGNED NOT NULL DEFAULT 0,
  locked_until          DATETIME      NULL,
  last_login_at         DATETIME      NULL,
  created_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_users PRIMARY KEY (user_id),
  CONSTRAINT uq_users_username UNIQUE (username),
  CONSTRAINT uq_users_prn UNIQUE (prn),
  CONSTRAINT uq_users_teacher UNIQUE (teacher_id),
  CONSTRAINT fk_users_student FOREIGN KEY (prn)
    REFERENCES students (prn) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_users_teacher FOREIGN KEY (teacher_id)
    REFERENCES teachers (teacher_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  INDEX idx_users_role (role)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- courses (a "class" in reports). semester must match year of study.
-- ---------------------------------------------------------------------
CREATE TABLE courses (
  course_id      INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  code           VARCHAR(15)       NOT NULL,
  name           VARCHAR(150)      NOT NULL,
  credits        TINYINT UNSIGNED  NOT NULL DEFAULT 3,
  branch_id      SMALLINT UNSIGNED NOT NULL,
  year_of_study  TINYINT UNSIGNED  NOT NULL,
  semester       TINYINT UNSIGNED  NOT NULL,
  teacher_id     INT UNSIGNED      NULL COMMENT 'course coordinator',
  join_code      CHAR(6)           NULL COMMENT 'class code students scan (QR) or type to join',
  join_open      BOOLEAN           NOT NULL DEFAULT TRUE,
  is_active      BOOLEAN           NOT NULL DEFAULT TRUE,
  created_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_courses PRIMARY KEY (course_id),
  CONSTRAINT uq_courses_code UNIQUE (code),
  CONSTRAINT uq_courses_join_code UNIQUE (join_code),
  CONSTRAINT fk_courses_branch FOREIGN KEY (branch_id)
    REFERENCES branches (branch_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_courses_teacher FOREIGN KEY (teacher_id)
    REFERENCES teachers (teacher_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT chk_courses_credits  CHECK (credits BETWEEN 1 AND 6),
  CONSTRAINT chk_courses_year     CHECK (year_of_study BETWEEN 1 AND 4),
  CONSTRAINT chk_courses_semester CHECK (semester BETWEEN year_of_study * 2 - 1 AND year_of_study * 2),
  INDEX idx_courses_branch_year (branch_id, year_of_study)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- enrollments: M:N students <-> courses. Composite natural PK.
-- ---------------------------------------------------------------------
CREATE TABLE enrollments (
  prn          VARCHAR(20)  NOT NULL,
  course_id    INT UNSIGNED NOT NULL,
  enrolled_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_enrollments PRIMARY KEY (prn, course_id),
  CONSTRAINT fk_enrollments_student FOREIGN KEY (prn)
    REFERENCES students (prn) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_enrollments_course FOREIGN KEY (course_id)
    REFERENCES courses (course_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  -- reverse lookup "roster of a course" (PK only serves prn-first lookups)
  INDEX idx_enrollments_course (course_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- sessions: one lecture of a course. Attendance window = [start, end].
-- SCHEDULED -> OPEN -> CLOSED   (or CANCELLED)
-- ---------------------------------------------------------------------
CREATE TABLE sessions (
  session_id      INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  course_id       INT UNSIGNED     NOT NULL,
  teacher_id      INT UNSIGNED     NULL,
  session_date    DATE             NOT NULL,
  start_time      TIME             NOT NULL,
  end_time        TIME             NOT NULL,
  late_after_min  TINYINT UNSIGNED NOT NULL DEFAULT 10 COMMENT 'grace period before LATE',
  status          ENUM('SCHEDULED','OPEN','CLOSED','CANCELLED') NOT NULL DEFAULT 'SCHEDULED',
  opened_at       DATETIME         NULL,
  closed_at       DATETIME         NULL,
  room            VARCHAR(20)      NULL,
  topic           VARCHAR(200)     NULL,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT pk_sessions PRIMARY KEY (session_id),
  CONSTRAINT uq_sessions_slot UNIQUE (course_id, session_date, start_time),
  CONSTRAINT fk_sessions_course FOREIGN KEY (course_id)
    REFERENCES courses (course_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_sessions_teacher FOREIGN KEY (teacher_id)
    REFERENCES teachers (teacher_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT chk_sessions_time  CHECK (end_time > start_time),
  CONSTRAINT chk_sessions_grace CHECK (late_after_min <= 60),
  CONSTRAINT chk_sessions_close CHECK (closed_at IS NULL OR opened_at IS NULL OR closed_at >= opened_at),
  INDEX idx_sessions_date_status (session_date, status),
  INDEX idx_sessions_teacher_date (teacher_id, session_date),
  INDEX idx_sessions_status_date (status, session_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- attendance: one row per (session, student). UNIQUE prevents duplicate
-- marking even under concurrent requests (race-free at the DB level).
-- late_minutes is maintained by trigger (controlled denormalisation).
-- ---------------------------------------------------------------------
CREATE TABLE attendance (
  attendance_id  BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
  session_id     INT UNSIGNED      NOT NULL,
  prn            VARCHAR(20)       NOT NULL,
  status         ENUM('PRESENT','LATE','ABSENT') NOT NULL,
  method         ENUM('FACE_GROUP','FACE_SOLO','FACE_LIVE','QR','MANUAL','AUTO') NOT NULL,
  confidence     DECIMAL(5,4)      NULL,
  marked_at      DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  late_minutes   SMALLINT UNSIGNED NULL,
  marked_by      INT UNSIGNED      NULL,
  remarks        VARCHAR(255)      NULL,
  updated_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT pk_attendance PRIMARY KEY (attendance_id),
  CONSTRAINT uq_attendance_session_prn UNIQUE (session_id, prn),
  CONSTRAINT fk_attendance_session FOREIGN KEY (session_id)
    REFERENCES sessions (session_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_attendance_student FOREIGN KEY (prn)
    REFERENCES students (prn) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_attendance_marked_by FOREIGN KEY (marked_by)
    REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT chk_attendance_conf CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  CONSTRAINT chk_attendance_late CHECK (late_minutes IS NULL OR late_minutes <= 1440),
  CONSTRAINT chk_attendance_face_conf CHECK (method NOT IN ('FACE_GROUP','FACE_SOLO','FACE_LIVE') OR confidence IS NOT NULL),
  INDEX idx_attendance_prn_status (prn, status),
  INDEX idx_attendance_marked_at (marked_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- override_requests: manual correction workflow (student requests,
-- teacher approves). Applying an override is audited by triggers.
-- ---------------------------------------------------------------------
CREATE TABLE override_requests (
  override_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_id        INT UNSIGNED NOT NULL,
  prn               VARCHAR(20)  NOT NULL,
  current_status    ENUM('PRESENT','LATE','ABSENT') NULL COMMENT 'NULL = no attendance row',
  requested_status  ENUM('PRESENT','LATE','ABSENT') NOT NULL,
  late_minutes      SMALLINT UNSIGNED NULL,
  reason            VARCHAR(500) NOT NULL,
  status            ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
  requested_by      INT UNSIGNED NULL,
  reviewed_by       INT UNSIGNED NULL,
  review_note       VARCHAR(255) NULL,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at       DATETIME     NULL,
  CONSTRAINT pk_override_requests PRIMARY KEY (override_id),
  CONSTRAINT fk_override_session FOREIGN KEY (session_id)
    REFERENCES sessions (session_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_override_student FOREIGN KEY (prn)
    REFERENCES students (prn) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_override_requested_by FOREIGN KEY (requested_by)
    REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT fk_override_reviewed_by FOREIGN KEY (reviewed_by)
    REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT chk_override_reason CHECK (CHAR_LENGTH(TRIM(reason)) >= 5),
  CONSTRAINT chk_override_change CHECK (current_status IS NULL OR requested_status <> current_status),
  CONSTRAINT chk_override_review CHECK ((status = 'PENDING') = (reviewed_at IS NULL)),
  INDEX idx_override_status (status, created_at),
  INDEX idx_override_prn (prn)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- audit_log: append-only. No FK on changed_by on purpose: the audit
-- trail must survive deletion of the user who made the change.
-- The application DB user only has SELECT here (see 03_roles.sh);
-- rows are written by triggers running with DEFINER rights.
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
  audit_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  table_name  VARCHAR(64)     NOT NULL,
  record_id   VARCHAR(64)     NOT NULL,
  action      ENUM('INSERT','UPDATE','DELETE','OVERRIDE','ERASE') NOT NULL,
  old_values  JSON            NULL,
  new_values  JSON            NULL,
  changed_by  INT UNSIGNED    NULL,
  reason      VARCHAR(500)    NULL,
  db_user     VARCHAR(100)    NOT NULL,
  changed_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT pk_audit_log PRIMARY KEY (audit_id),
  INDEX idx_audit_record (table_name, record_id),
  INDEX idx_audit_time (changed_at),
  INDEX idx_audit_action (action, changed_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- saga_log: durable state machine of cross-database (MySQL + MongoDB)
-- sagas, used for compensation and crash recovery.
-- ---------------------------------------------------------------------
CREATE TABLE saga_log (
  saga_id        CHAR(36)     NOT NULL,
  saga_type      ENUM('REGISTER','ADD_PHOTOS','DELETE','FORGET') NOT NULL,
  subject        VARCHAR(64)  NOT NULL COMMENT 'PRN, or SHA-256 of PRN for FORGET',
  status         ENUM('STARTED','COMPLETED','COMPENSATING','COMPENSATED','FAILED') NOT NULL DEFAULT 'STARTED',
  steps          JSON         NOT NULL,
  error_message  TEXT         NULL,
  created_by     INT UNSIGNED NULL,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  CONSTRAINT pk_saga_log PRIMARY KEY (saga_id),
  INDEX idx_saga_status (status, updated_at),
  INDEX idx_saga_subject (subject)
) ENGINE=InnoDB;


-- =====================================================================
--  VIEWS  (derived data is never stored -> no update anomalies)
-- =====================================================================

-- per student x course. Percentages are computed over CLOSED sessions.
CREATE OR REPLACE VIEW v_student_course_attendance AS
SELECT
  s.prn,
  s.full_name,
  c.course_id,
  c.code AS course_code,
  c.name AS course_name,
  COUNT(ses.session_id)                          AS sessions_held,
  COALESCE(SUM(a.status = 'PRESENT'), 0)         AS present_count,
  COALESCE(SUM(a.status = 'LATE'), 0)            AS late_count,
  COUNT(ses.session_id)
    - COALESCE(SUM(a.status IN ('PRESENT','LATE')), 0) AS absent_count,
  ROUND(100 * COALESCE(SUM(a.status IN ('PRESENT','LATE')), 0)
        / NULLIF(COUNT(ses.session_id), 0), 2)   AS attendance_pct
FROM students s
JOIN enrollments e   ON e.prn = s.prn
JOIN courses c       ON c.course_id = e.course_id
LEFT JOIN sessions ses ON ses.course_id = e.course_id AND ses.status = 'CLOSED'
LEFT JOIN attendance a ON a.session_id = ses.session_id AND a.prn = s.prn
GROUP BY s.prn, s.full_name, c.course_id, c.code, c.name;

-- overall per student across all enrolled courses
CREATE OR REPLACE VIEW v_student_attendance_pct AS
SELECT
  s.prn,
  s.full_name,
  s.email,
  b.code          AS branch,
  d.year_of_study AS year_of_study,
  d.name          AS division,
  s.roll_no,
  s.face_status,
  COALESCE(SUM(x.sessions_held), 0) AS total_sessions,
  COALESCE(SUM(x.present_count), 0) AS present_count,
  COALESCE(SUM(x.late_count), 0)    AS late_count,
  COALESCE(SUM(x.absent_count), 0)  AS absent_count,
  ROUND(100 * (COALESCE(SUM(x.present_count), 0) + COALESCE(SUM(x.late_count), 0))
        / NULLIF(SUM(x.sessions_held), 0), 2) AS attendance_pct,
  (COALESCE(SUM(x.sessions_held), 0) > 0
   AND 100 * (COALESCE(SUM(x.present_count), 0) + COALESCE(SUM(x.late_count), 0))
       / SUM(x.sessions_held)
       < (SELECT CAST(meta_value AS DECIMAL(5,2)) FROM app_meta WHERE meta_key = 'shortage_threshold')
  ) AS is_shortage
FROM students s
JOIN divisions d ON d.division_id = s.division_id
JOIN branches b  ON b.branch_id = d.branch_id
LEFT JOIN v_student_course_attendance x ON x.prn = s.prn
GROUP BY s.prn, s.full_name, s.email, b.code, d.year_of_study, d.name, s.roll_no, s.face_status;

-- per session counts (used for date reports, dashboards, teacher e-mails)
CREATE OR REPLACE VIEW v_session_summary AS
SELECT
  ses.session_id,
  ses.course_id,
  c.code       AS course_code,
  c.name       AS course_name,
  ses.teacher_id,
  t.full_name  AS teacher_name,
  ses.session_date,
  ses.start_time,
  ses.end_time,
  ses.late_after_min,
  ses.status,
  ses.room,
  ses.topic,
  ses.opened_at,
  ses.closed_at,
  (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = ses.course_id) AS enrolled,
  COALESCE(SUM(a.status = 'PRESENT'), 0) AS present_count,
  COALESCE(SUM(a.status = 'LATE'), 0)    AS late_count,
  COALESCE(SUM(a.status = 'ABSENT'), 0)  AS absent_count
FROM sessions ses
JOIN courses c        ON c.course_id = ses.course_id
LEFT JOIN teachers t  ON t.teacher_id = ses.teacher_id
LEFT JOIN attendance a ON a.session_id = ses.session_id
GROUP BY ses.session_id, ses.course_id, c.code, c.name, ses.teacher_id, t.full_name,
         ses.session_date, ses.start_time, ses.end_time, ses.late_after_min, ses.status,
         ses.room, ses.topic, ses.opened_at, ses.closed_at;

-- per course
CREATE OR REPLACE VIEW v_course_summary AS
SELECT
  c.course_id,
  c.code,
  c.name,
  c.credits,
  c.semester,
  c.teacher_id,
  t.full_name AS coordinator,
  (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.course_id) AS enrolled,
  (SELECT COUNT(*) FROM sessions s WHERE s.course_id = c.course_id AND s.status = 'CLOSED') AS sessions_held,
  ROUND(AVG(x.attendance_pct), 2) AS avg_attendance_pct,
  COALESCE(SUM(x.attendance_pct < (SELECT CAST(meta_value AS DECIMAL(5,2))
                                   FROM app_meta WHERE meta_key = 'shortage_threshold')), 0) AS shortage_count
FROM courses c
LEFT JOIN teachers t ON t.teacher_id = c.teacher_id
LEFT JOIN v_student_course_attendance x ON x.course_id = c.course_id
GROUP BY c.course_id, c.code, c.name, c.credits, c.semester, c.teacher_id, t.full_name;

-- students below the threshold in at least one course (per course rows)
CREATE OR REPLACE VIEW v_shortage_list AS
SELECT
  x.prn,
  x.full_name,
  s.email,
  x.course_id,
  x.course_code,
  x.course_name,
  x.sessions_held,
  x.present_count,
  x.late_count,
  x.absent_count,
  x.attendance_pct,
  (SELECT CAST(meta_value AS DECIMAL(5,2)) FROM app_meta WHERE meta_key = 'shortage_threshold') AS threshold_pct
FROM v_student_course_attendance x
JOIN students s ON s.prn = x.prn
WHERE x.sessions_held > 0
  AND x.attendance_pct < (SELECT CAST(meta_value AS DECIMAL(5,2)) FROM app_meta WHERE meta_key = 'shortage_threshold');


-- =====================================================================
--  TRIGGERS
-- =====================================================================
DELIMITER $$

-- auto-calc late minutes on insert (single source of truth for the rule)
CREATE TRIGGER trg_attendance_bi BEFORE INSERT ON attendance
FOR EACH ROW
BEGIN
  DECLARE v_start DATETIME;
  IF NEW.marked_at IS NULL THEN
    SET NEW.marked_at = NOW();
  END IF;
  IF NEW.status = 'LATE' THEN
    SELECT TIMESTAMP(session_date, start_time) INTO v_start
      FROM sessions WHERE session_id = NEW.session_id;
    SET NEW.late_minutes = GREATEST(0, TIMESTAMPDIFF(MINUTE, v_start, NEW.marked_at));
  ELSE
    SET NEW.late_minutes = NULL;
  END IF;
END$$

-- recompute late minutes when status / time changes
CREATE TRIGGER trg_attendance_bu BEFORE UPDATE ON attendance
FOR EACH ROW
BEGIN
  DECLARE v_start DATETIME;
  IF NEW.status = 'LATE' THEN
    IF OLD.status <> 'LATE' OR NEW.marked_at <> OLD.marked_at OR NEW.late_minutes IS NULL THEN
      SELECT TIMESTAMP(session_date, start_time) INTO v_start
        FROM sessions WHERE session_id = NEW.session_id;
      SET NEW.late_minutes = GREATEST(0, TIMESTAMPDIFF(MINUTE, v_start, NEW.marked_at));
    END IF;
  ELSE
    SET NEW.late_minutes = NULL;
  END IF;
END$$

-- audit manual inserts (automatic face/QR inserts are logged in MongoDB instead)
CREATE TRIGGER trg_attendance_ai AFTER INSERT ON attendance
FOR EACH ROW
BEGIN
  IF NEW.method = 'MANUAL' THEN
    INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
    VALUES ('attendance', CAST(NEW.attendance_id AS CHAR),
            IF(@audit_action = 'OVERRIDE', 'OVERRIDE', 'INSERT'),
            NULL,
            JSON_OBJECT('session_id', NEW.session_id, 'prn', NEW.prn, 'status', NEW.status,
                        'method', NEW.method, 'late_minutes', NEW.late_minutes,
                        'marked_at', NEW.marked_at),
            COALESCE(@app_user_id, NEW.marked_by), @audit_reason, USER());
  END IF;
END$$

-- audit every update (who / when / why / old -> new)
CREATE TRIGGER trg_attendance_au AFTER UPDATE ON attendance
FOR EACH ROW
BEGIN
  INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
  VALUES ('attendance', CAST(NEW.attendance_id AS CHAR),
          IF(@audit_action = 'OVERRIDE', 'OVERRIDE', 'UPDATE'),
          JSON_OBJECT('session_id', OLD.session_id, 'prn', OLD.prn, 'status', OLD.status,
                      'method', OLD.method, 'confidence', OLD.confidence,
                      'late_minutes', OLD.late_minutes, 'marked_at', OLD.marked_at),
          JSON_OBJECT('session_id', NEW.session_id, 'prn', NEW.prn, 'status', NEW.status,
                      'method', NEW.method, 'confidence', NEW.confidence,
                      'late_minutes', NEW.late_minutes, 'marked_at', NEW.marked_at),
          COALESCE(@app_user_id, NEW.marked_by), @audit_reason, USER());
END$$

-- audit deletes (note: NOT fired by FK cascades - by MySQL design)
CREATE TRIGGER trg_attendance_ad AFTER DELETE ON attendance
FOR EACH ROW
BEGIN
  INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
  VALUES ('attendance', CAST(OLD.attendance_id AS CHAR), 'DELETE',
          JSON_OBJECT('session_id', OLD.session_id, 'prn', OLD.prn, 'status', OLD.status,
                      'method', OLD.method, 'confidence', OLD.confidence,
                      'late_minutes', OLD.late_minutes, 'marked_at', OLD.marked_at),
          NULL, @app_user_id, @audit_reason, USER());
END$$

-- users: role <-> link consistency
CREATE TRIGGER trg_users_bi BEFORE INSERT ON users
FOR EACH ROW
BEGIN
  IF (NEW.role = 'STUDENT' AND (NEW.prn IS NULL OR NEW.teacher_id IS NOT NULL))
     OR (NEW.role = 'TEACHER' AND (NEW.teacher_id IS NULL OR NEW.prn IS NOT NULL))
     OR (NEW.role = 'ADMIN' AND NEW.prn IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'USER_ROLE_LINK_INVALID';
  END IF;
END$$

CREATE TRIGGER trg_users_bu BEFORE UPDATE ON users
FOR EACH ROW
BEGIN
  IF (NEW.role = 'STUDENT' AND (NEW.prn IS NULL OR NEW.teacher_id IS NOT NULL))
     OR (NEW.role = 'TEACHER' AND (NEW.teacher_id IS NULL OR NEW.prn IS NOT NULL))
     OR (NEW.role = 'ADMIN' AND NEW.prn IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'USER_ROLE_LINK_INVALID';
  END IF;
END$$

-- students: audit profile changes / deletions (no PII when erasing)
CREATE TRIGGER trg_students_au AFTER UPDATE ON students
FOR EACH ROW
BEGIN
  IF NOT (OLD.full_name <=> NEW.full_name AND OLD.email <=> NEW.email AND OLD.phone <=> NEW.phone
          AND OLD.division_id <=> NEW.division_id AND OLD.roll_no <=> NEW.roll_no) THEN
    INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
    VALUES ('students', NEW.prn, 'UPDATE',
            JSON_OBJECT('full_name', OLD.full_name, 'email', OLD.email, 'phone', OLD.phone,
                        'division_id', OLD.division_id, 'roll_no', OLD.roll_no),
            JSON_OBJECT('full_name', NEW.full_name, 'email', NEW.email, 'phone', NEW.phone,
                        'division_id', NEW.division_id, 'roll_no', NEW.roll_no),
            @app_user_id, @audit_reason, USER());
  END IF;
END$$

CREATE TRIGGER trg_students_ad AFTER DELETE ON students
FOR EACH ROW
BEGIN
  IF @audit_action = 'ERASE' THEN
    INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
    VALUES ('students', SHA2(OLD.prn, 256), 'ERASE', NULL, NULL,
            @app_user_id, 'Right to be forgotten', USER());
  ELSE
    INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
    VALUES ('students', OLD.prn, 'DELETE',
            JSON_OBJECT('full_name', OLD.full_name, 'division_id', OLD.division_id, 'roll_no', OLD.roll_no),
            NULL, @app_user_id, @audit_reason, USER());
  END IF;
END$$

-- override workflow state changes
CREATE TRIGGER trg_override_au AFTER UPDATE ON override_requests
FOR EACH ROW
BEGIN
  IF OLD.status <> NEW.status THEN
    INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by, reason, db_user)
    VALUES ('override_requests', CAST(NEW.override_id AS CHAR), 'UPDATE',
            JSON_OBJECT('status', OLD.status),
            JSON_OBJECT('status', NEW.status, 'requested_status', NEW.requested_status,
                        'session_id', NEW.session_id, 'prn', NEW.prn, 'review_note', NEW.review_note),
            NEW.reviewed_by, NEW.reason, USER());
  END IF;
END$$


-- =====================================================================
--  STORED PROCEDURES
--  Errors are raised with SIGNAL SQLSTATE '45000' and a machine-readable
--  MESSAGE_TEXT that the API maps to HTTP status codes.
--  Procedures do NOT open their own transactions: the caller controls
--  the transaction boundary (e.g. whole class marked atomically).
-- =====================================================================

-- mark one student PRESENT. p_result: INSERTED | DUPLICATE
CREATE PROCEDURE mark_attendance(
  IN  p_session_id  INT UNSIGNED,
  IN  p_prn         VARCHAR(20),
  IN  p_method      VARCHAR(20),
  IN  p_confidence  DECIMAL(5,4),
  IN  p_marked_by   INT UNSIGNED,
  OUT p_result      VARCHAR(20)
)
BEGIN
  DECLARE v_status VARCHAR(12) DEFAULT NULL;
  DECLARE v_course INT UNSIGNED DEFAULT NULL;
  DECLARE v_dup BOOLEAN DEFAULT FALSE;
  DECLARE CONTINUE HANDLER FOR 1062 SET v_dup = TRUE;   -- duplicate key on uq_attendance_session_prn

  -- shared lock: concurrent markers proceed together, close_session() waits
  SELECT status, course_id INTO v_status, v_course
    FROM sessions WHERE session_id = p_session_id FOR SHARE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_FOUND';
  END IF;
  IF v_status <> 'OPEN' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_OPEN';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM enrollments WHERE prn = p_prn AND course_id = v_course) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'STUDENT_NOT_ENROLLED';
  END IF;

  INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at, marked_by)
  VALUES (p_session_id, p_prn, 'PRESENT', p_method, p_confidence, NOW(), p_marked_by);

  SET p_result = IF(v_dup, 'DUPLICATE', 'INSERTED');
END$$

-- solo late entry. Within the grace period the student is PRESENT.
-- p_result: LATE | PRESENT | UPGRADED_FROM_ABSENT ; error ALREADY_MARKED:<status>
CREATE PROCEDURE mark_late(
  IN  p_session_id    INT UNSIGNED,
  IN  p_prn           VARCHAR(20),
  IN  p_method        VARCHAR(20),
  IN  p_confidence    DECIMAL(5,4),
  IN  p_marked_by     INT UNSIGNED,
  OUT p_late_minutes  INT,
  OUT p_result        VARCHAR(30)
)
BEGIN
  DECLARE v_status   VARCHAR(12) DEFAULT NULL;
  DECLARE v_course   INT UNSIGNED DEFAULT NULL;
  DECLARE v_start    DATETIME DEFAULT NULL;
  DECLARE v_grace    INT DEFAULT 0;
  DECLARE v_existing VARCHAR(10) DEFAULT NULL;
  DECLARE v_minutes  INT DEFAULT 0;
  DECLARE v_new      VARCHAR(10);
  DECLARE v_msg      VARCHAR(128);

  SELECT status, course_id, TIMESTAMP(session_date, start_time), late_after_min
    INTO v_status, v_course, v_start, v_grace
    FROM sessions WHERE session_id = p_session_id FOR SHARE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_FOUND';
  END IF;
  IF v_status <> 'OPEN' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_OPEN';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM enrollments WHERE prn = p_prn AND course_id = v_course) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'STUDENT_NOT_ENROLLED';
  END IF;

  -- row lock (or gap lock) on the (session, prn) slot
  SELECT status INTO v_existing FROM attendance
   WHERE session_id = p_session_id AND prn = p_prn FOR UPDATE;

  IF v_existing IN ('PRESENT', 'LATE') THEN
    SET v_msg = CONCAT('ALREADY_MARKED:', v_existing);
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;

  SET v_minutes = GREATEST(0, TIMESTAMPDIFF(MINUTE, v_start, NOW()));
  SET v_new = IF(v_minutes > v_grace, 'LATE', 'PRESENT');

  IF v_existing = 'ABSENT' THEN
    SET @audit_reason = 'Late entry after auto-absent';
    UPDATE attendance
       SET status = v_new, method = p_method, confidence = p_confidence,
           marked_at = NOW(), marked_by = p_marked_by
     WHERE session_id = p_session_id AND prn = p_prn;
    SET @audit_reason = NULL;
    SET p_result = 'UPGRADED_FROM_ABSENT';
  ELSE
    INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at, marked_by)
    VALUES (p_session_id, p_prn, v_new, p_method, p_confidence, NOW(), p_marked_by);
    SET p_result = v_new;
  END IF;

  SELECT COALESCE(late_minutes, 0) INTO p_late_minutes
    FROM attendance WHERE session_id = p_session_id AND prn = p_prn;
END$$

-- open a session (time-window rule unless p_force)
CREATE PROCEDURE open_session(IN p_session_id INT UNSIGNED, IN p_force BOOLEAN, IN p_early_min INT)
BEGIN
  DECLARE v_status VARCHAR(12) DEFAULT NULL;
  DECLARE v_start DATETIME;
  DECLARE v_end DATETIME;

  SELECT status, TIMESTAMP(session_date, start_time), TIMESTAMP(session_date, end_time)
    INTO v_status, v_start, v_end
    FROM sessions WHERE session_id = p_session_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_FOUND';
  END IF;
  IF v_status <> 'SCHEDULED' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_SESSION_STATE';
  END IF;
  IF NOT p_force AND (NOW() < v_start - INTERVAL p_early_min MINUTE OR NOW() > v_end) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OUTSIDE_SESSION_WINDOW';
  END IF;

  UPDATE sessions SET status = 'OPEN', opened_at = NOW() WHERE session_id = p_session_id;
END$$

-- close a session: everybody enrolled but unmarked becomes ABSENT
CREATE PROCEDURE close_session(IN p_session_id INT UNSIGNED, IN p_closed_by INT UNSIGNED, OUT p_absent_marked INT)
BEGIN
  DECLARE v_status VARCHAR(12) DEFAULT NULL;
  DECLARE v_course INT UNSIGNED;

  -- exclusive lock: waits for in-flight markers holding FOR SHARE locks
  SELECT status, course_id INTO v_status, v_course
    FROM sessions WHERE session_id = p_session_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_FOUND';
  END IF;
  IF v_status <> 'OPEN' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SESSION_NOT_OPEN';
  END IF;

  INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at, marked_by)
  SELECT p_session_id, e.prn, 'ABSENT', 'AUTO', NULL, NOW(), p_closed_by
    FROM enrollments e
   WHERE e.course_id = v_course
     AND NOT EXISTS (SELECT 1 FROM attendance a
                      WHERE a.session_id = p_session_id AND a.prn = e.prn);
  SET p_absent_marked = ROW_COUNT();

  UPDATE sessions SET status = 'CLOSED', closed_at = NOW() WHERE session_id = p_session_id;
END$$

-- scheduler job: close sessions whose window ended (demonstrates a CURSOR)
CREATE PROCEDURE auto_close_expired_sessions(IN p_grace_min INT, OUT p_closed INT)
BEGIN
  DECLARE v_done BOOLEAN DEFAULT FALSE;
  DECLARE v_sid INT UNSIGNED;
  DECLARE v_absent INT;
  DECLARE cur CURSOR FOR
    SELECT session_id FROM sessions
     WHERE status = 'OPEN'
       AND TIMESTAMP(session_date, end_time) + INTERVAL p_grace_min MINUTE < NOW();
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = TRUE;

  SET p_closed = 0;
  OPEN cur;
  read_loop: LOOP
    FETCH cur INTO v_sid;
    IF v_done THEN
      LEAVE read_loop;
    END IF;
    CALL close_session(v_sid, NULL, v_absent);
    SET p_closed = p_closed + 1;
  END LOOP;
  CLOSE cur;
END$$

-- apply an approved override (fires audit triggers with the reason)
CREATE PROCEDURE apply_override(
  IN p_override_id INT UNSIGNED,
  IN p_reviewer    INT UNSIGNED,
  IN p_note        VARCHAR(255)
)
BEGIN
  DECLARE v_session   INT UNSIGNED DEFAULT NULL;
  DECLARE v_prn       VARCHAR(20);
  DECLARE v_requested VARCHAR(10);
  DECLARE v_state     VARCHAR(10);
  DECLARE v_reason    VARCHAR(500);
  DECLARE v_late      INT;
  DECLARE v_start     DATETIME;
  DECLARE v_grace     INT;

  SELECT session_id, prn, requested_status, status, reason, late_minutes
    INTO v_session, v_prn, v_requested, v_state, v_reason, v_late
    FROM override_requests WHERE override_id = p_override_id FOR UPDATE;

  IF v_session IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OVERRIDE_NOT_FOUND';
  END IF;
  IF v_state <> 'PENDING' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OVERRIDE_ALREADY_RESOLVED';
  END IF;

  SELECT TIMESTAMP(session_date, start_time), late_after_min INTO v_start, v_grace
    FROM sessions WHERE session_id = v_session;

  SET @app_user_id = p_reviewer, @audit_reason = v_reason, @audit_action = 'OVERRIDE';

  INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at, marked_by, remarks)
  VALUES (v_session, v_prn, v_requested, 'MANUAL', NULL,
          IF(v_requested = 'LATE', v_start + INTERVAL COALESCE(v_late, v_grace + 1) MINUTE, v_start),
          p_reviewer, CONCAT('Override #', p_override_id)) AS new_row
  ON DUPLICATE KEY UPDATE
    status     = new_row.status,
    method     = 'MANUAL',
    confidence = NULL,
    marked_at  = new_row.marked_at,
    marked_by  = new_row.marked_by,
    remarks    = new_row.remarks;

  UPDATE override_requests
     SET status = 'APPROVED', reviewed_by = p_reviewer, reviewed_at = NOW(), review_note = p_note
   WHERE override_id = p_override_id;

  SET @audit_action = NULL, @audit_reason = NULL;
END$$

-- student report: 3 result sets (profile, per course, history)
CREATE PROCEDURE get_student_report(IN p_prn VARCHAR(20))
BEGIN
  IF NOT EXISTS (SELECT 1 FROM students WHERE prn = p_prn) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'STUDENT_NOT_FOUND';
  END IF;

  SELECT * FROM v_student_attendance_pct WHERE prn = p_prn;

  SELECT course_id, course_code, course_name, sessions_held, present_count, late_count,
         absent_count, attendance_pct
    FROM v_student_course_attendance WHERE prn = p_prn ORDER BY course_code;

  SELECT ses.session_id, ses.session_date, ses.start_time, c.code AS course_code,
         c.name AS course_name, ses.status AS session_status,
         a.status, a.method, a.confidence, a.marked_at, a.late_minutes
    FROM enrollments e
    JOIN sessions ses ON ses.course_id = e.course_id AND ses.status IN ('OPEN','CLOSED')
    JOIN courses c ON c.course_id = ses.course_id
    LEFT JOIN attendance a ON a.session_id = ses.session_id AND a.prn = e.prn
   WHERE e.prn = p_prn
   ORDER BY ses.session_date DESC, ses.start_time DESC;
END$$

-- right to be forgotten (MySQL half of the FORGET saga).
-- SQL SECURITY DEFINER lets the app user pseudonymise audit rows without
-- having UPDATE privilege on audit_log itself.
CREATE PROCEDURE forget_student(IN p_prn VARCHAR(20), IN p_actor INT UNSIGNED, OUT p_deleted INT)
SQL SECURITY DEFINER
BEGIN
  DECLARE v_hash CHAR(64);
  SET v_hash = SHA2(p_prn, 256);

  -- pseudonymise historic audit entries that mention the student
  UPDATE audit_log
     SET old_values = IF(old_values IS NULL, NULL, JSON_SET(old_values, '$.prn', v_hash)),
         new_values = IF(new_values IS NULL, NULL, JSON_SET(new_values, '$.prn', v_hash))
   WHERE JSON_UNQUOTE(JSON_EXTRACT(old_values, '$.prn')) = p_prn
      OR JSON_UNQUOTE(JSON_EXTRACT(new_values, '$.prn')) = p_prn;

  UPDATE audit_log
     SET record_id = v_hash, old_values = NULL, new_values = NULL
   WHERE table_name = 'students' AND record_id = p_prn;

  -- FK cascades remove users, enrollments, attendance, override_requests
  SET @app_user_id = p_actor, @audit_action = 'ERASE';
  DELETE FROM students WHERE prn = p_prn;
  SET p_deleted = ROW_COUNT();
  SET @audit_action = NULL;
END$$

DELIMITER ;
