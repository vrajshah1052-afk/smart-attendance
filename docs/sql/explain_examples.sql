-- =====================================================================
--  EXPLAIN examples for the viva. Run as attendance_admin on attendance_db.
--  Plans below were captured on the seeded database (MySQL 8/9, InnoDB).
-- =====================================================================
USE attendance_db;

-- 1. Point lookup through the UNIQUE key that also prevents duplicate marking
EXPLAIN SELECT status FROM attendance WHERE session_id = 3 AND prn = '12310005';
-- type=const  key=uq_attendance_session_prn  ref=const,const  rows=1
-- => at most one row can match, the optimiser reads it during planning.

-- 2. Per-student status counts: covering index (no table rows read)
EXPLAIN SELECT status, COUNT(*) FROM attendance WHERE prn = '12310005' GROUP BY status;
-- type=ref  key=idx_attendance_prn_status  rows=10  Extra=Using index

-- 3. The same query without the index (invisible indexes are a safe way to test a drop)
ALTER TABLE attendance ALTER INDEX idx_attendance_prn_status INVISIBLE;
EXPLAIN SELECT status, COUNT(*) FROM attendance WHERE prn = '12310005' GROUP BY status;
-- type=ALL  key=NULL  rows=205  Extra=Using where; Using temporary   (full scan + temp table)
ALTER TABLE attendance ALTER INDEX idx_attendance_prn_status VISIBLE;

-- 4. Today's open sessions (dashboard, auto-close job)
EXPLAIN SELECT * FROM sessions WHERE session_date = CURDATE() AND status = 'OPEN';
-- type=ref  key=idx_sessions_date_status  ref=const,const  rows=1  Extra=Using index condition

-- 5. Course roster: the composite PK of enrollments is used as eq_ref
EXPLAIN SELECT s.prn, s.full_name FROM enrollments e JOIN students s ON s.prn = e.prn WHERE e.course_id = 1;
-- s: index (covering)   e: eq_ref PRIMARY (prn, course_id)  -> one probe per student

-- 6. Teacher's sessions for a day (daily summary e-mail)
EXPLAIN SELECT session_id FROM sessions WHERE teacher_id = 1 AND session_date = CURDATE();
-- key=idx_sessions_teacher_date

-- 7. Audit viewer filter
EXPLAIN SELECT * FROM audit_log WHERE table_name = 'attendance' AND record_id = '42';
-- key=idx_audit_record

-- 8. Where does a view spend its time? (MySQL 8.0.18+)
EXPLAIN ANALYZE SELECT * FROM v_shortage_list WHERE course_id = 1;
-- Nested loop inner join ... Materialize (the GROUP BY view is materialised into a temporary table)
-- -> Covering index scan on s / Single-row covering index lookup on e using PRIMARY ...

-- 9. Index statistics
SELECT index_name, seq_in_index, column_name, cardinality
  FROM information_schema.statistics
 WHERE table_schema = 'attendance_db' AND table_name = 'attendance'
 ORDER BY index_name, seq_in_index;
