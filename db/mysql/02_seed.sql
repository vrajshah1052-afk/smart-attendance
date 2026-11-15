-- =====================================================================
--  Seed data: 5 branches, 60 divisions, 5 teachers, 5 SY semester-3 subjects,
--  20 students, 10 sessions (8 closed with attendance + 2 today).
--  Teachers sign in with their employee code (VIT@001), never an e-mail, and
--  only an admin ever creates one - see local/seed_subjects.py for the
--  passwords, which SQL cannot hash.
--  Dates are relative to CURDATE() so the demo always looks "recent".
--  User accounts are created WITHOUT passwords: the backend activates
--  them on boot with DEMO_USER_PASSWORD (no secrets in SQL files).
-- =====================================================================
USE attendance_db;

INSERT INTO branches (code, name) VALUES
  ('CS',   'Computer Engineering'),
  ('IT',   'Information Technology'),
  ('ENTC', 'Electronics and Telecommunication'),
  ('AIDS', 'Artificial Intelligence and Data Science'),
  ('MECH', 'Mechanical Engineering');

-- every branch x year (1-4) x division (A, B, C)
INSERT INTO divisions (branch_id, year_of_study, name)
SELECT b.branch_id, y.y, d.d
  FROM branches b
 CROSS JOIN (SELECT 1 AS y UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4) y
 CROSS JOIN (SELECT 'A' AS d UNION ALL SELECT 'B' UNION ALL SELECT 'C') d;

SET @cs := (SELECT branch_id FROM branches WHERE code = 'CS');
SET @it := (SELECT branch_id FROM branches WHERE code = 'IT');
SET @cs2a := (SELECT division_id FROM divisions WHERE branch_id = @cs AND year_of_study = 2 AND name = 'A');

INSERT INTO teachers (employee_code, full_name, email, phone, branch_id, designation) VALUES
  ('VIT@001', 'Renuka Vaidya', 'renuka.vaidya@vit.edu', '9822000101', @cs, 'Assistant Professor'),
  ('VIT@002', 'Jyoti Yadav',   'jyoti.yadav@vit.edu',   '9822000102', @cs, 'Associate Professor'),
  ('VIT@003', 'Manisha More',  'manisha.more@vit.edu',  '9822000103', @cs, 'Assistant Professor'),
  ('VIT@004', 'Tejal Panmand', 'tejal.panmand@vit.edu', '9822000104', @cs, 'Assistant Professor'),
  ('VIT@005', 'Rahul Rathod',  'rahul.rathod@vit.edu',  '9822000105', @cs, 'Assistant Professor');

SET @t_ds   := (SELECT teacher_id FROM teachers WHERE employee_code = 'VIT@001');
SET @t_dbms := (SELECT teacher_id FROM teachers WHERE employee_code = 'VIT@002');
SET @t_oop  := (SELECT teacher_id FROM teachers WHERE employee_code = 'VIT@003');
SET @t_dm   := (SELECT teacher_id FROM teachers WHERE employee_code = 'VIT@004');
SET @t_ldm  := (SELECT teacher_id FROM teachers WHERE employee_code = 'VIT@005');

-- SY Computer Engineering, semester 3
INSERT INTO courses (code, name, credits, branch_id, year_of_study, semester, teacher_id) VALUES
  ('DS',   'Data Structures',                  4, @cs, 2, 3, @t_ds),
  ('DBMS', 'Database Management Systems',      4, @cs, 2, 3, @t_dbms),
  ('OOP',  'Object Oriented Programming',      4, @cs, 2, 3, @t_oop),
  ('LDM',  'Logic Design and Microprocessors', 3, @cs, 2, 3, @t_ldm),
  ('DM',   'Discrete Mathematics',             3, @cs, 2, 3, @t_dm);

SET @ds   := (SELECT course_id FROM courses WHERE code = 'DS');
SET @dbms := (SELECT course_id FROM courses WHERE code = 'DBMS');
SET @oop  := (SELECT course_id FROM courses WHERE code = 'OOP');

-- 20 students of SY CS division A
INSERT INTO students (prn, full_name, email, phone, division_id, roll_no, consent_given, face_status) VALUES
  ('12310001', 'Aarav Patil',       'aarav.patil@student.example.org',       '9876500001', @cs2a,  1, TRUE, 'PENDING'),
  ('12310002', 'Aditi Kulkarni',    'aditi.kulkarni@student.example.org',    '9876500002', @cs2a,  2, TRUE, 'PENDING'),
  ('12310003', 'Rohan Joshi',       'rohan.joshi@student.example.org',       '9876500003', @cs2a,  3, TRUE, 'PENDING'),
  ('12310004', 'Sneha Deshpande',   'sneha.deshpande@student.example.org',   '9876500004', @cs2a,  4, TRUE, 'PENDING'),
  ('12310005', 'Vedant Shinde',     'vedant.shinde@student.example.org',     '9876500005', @cs2a,  5, TRUE, 'PENDING'),
  ('12310006', 'Priya Pawar',       'priya.pawar@student.example.org',       '9876500006', @cs2a,  6, TRUE, 'PENDING'),
  ('12310007', 'Omkar Jadhav',      'omkar.jadhav@student.example.org',      '9876500007', @cs2a,  7, TRUE, 'PENDING'),
  ('12310008', 'Isha Gokhale',      'isha.gokhale@student.example.org',      '9876500008', @cs2a,  8, TRUE, 'PENDING'),
  ('12310009', 'Siddharth More',    'siddharth.more@student.example.org',    '9876500009', @cs2a,  9, TRUE, 'PENDING'),
  ('12310010', 'Tanvi Bhosale',     'tanvi.bhosale@student.example.org',     '9876500010', @cs2a, 10, TRUE, 'PENDING'),
  ('12310011', 'Yash Chavan',       'yash.chavan@student.example.org',       '9876500011', @cs2a, 11, TRUE, 'PENDING'),
  ('12310012', 'Neha Gaikwad',      'neha.gaikwad@student.example.org',      '9876500012', @cs2a, 12, TRUE, 'PENDING'),
  ('12310013', 'Pranav Kale',       'pranav.kale@student.example.org',       '9876500013', @cs2a, 13, TRUE, 'PENDING'),
  ('12310014', 'Shruti Apte',       'shruti.apte@student.example.org',       '9876500014', @cs2a, 14, TRUE, 'PENDING'),
  ('12310015', 'Atharva Naik',      'atharva.naik@student.example.org',      '9876500015', @cs2a, 15, TRUE, 'PENDING'),
  ('12310016', 'Rutuja Salunkhe',   'rutuja.salunkhe@student.example.org',   '9876500016', @cs2a, 16, TRUE, 'PENDING'),
  ('12310017', 'Kunal Mane',        'kunal.mane@student.example.org',        '9876500017', @cs2a, 17, TRUE, 'PENDING'),
  ('12310018', 'Pooja Thorat',      'pooja.thorat@student.example.org',      '9876500018', @cs2a, 18, TRUE, 'PENDING'),
  ('12310019', 'Harsh Wagh',        'harsh.wagh@student.example.org',        '9876500019', @cs2a, 19, TRUE, 'PENDING'),
  ('12310020', 'Gauri Bapat',       'gauri.bapat@student.example.org',       '9876500020', @cs2a, 20, TRUE, 'PENDING');

-- everybody takes all five subjects
INSERT INTO enrollments (prn, course_id)
SELECT s.prn, c.course_id FROM students s CROSS JOIN courses c;

-- 10 sessions: 8 closed in the past 9 days, 2 scheduled today
INSERT INTO sessions (course_id, teacher_id, session_date, start_time, end_time, late_after_min, status, opened_at, closed_at, room, topic) VALUES
  (@dbms, @t_dbms, CURDATE() - INTERVAL 9 DAY, '09:00:00', '10:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 9 DAY, '08:55:00'), TIMESTAMP(CURDATE() - INTERVAL 9 DAY, '10:05:00'), 'A-301', 'ER modelling'),
  (@ds,   @t_ds, CURDATE() - INTERVAL 8 DAY, '11:00:00', '12:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 8 DAY, '10:58:00'), TIMESTAMP(CURDATE() - INTERVAL 8 DAY, '12:02:00'), 'A-302', 'Process scheduling'),
  (@oop,  @t_oop, CURDATE() - INTERVAL 7 DAY, '14:00:00', '15:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 7 DAY, '13:57:00'), TIMESTAMP(CURDATE() - INTERVAL 7 DAY, '15:03:00'), 'B-105', 'OSI and TCP/IP'),
  (@dbms, @t_dbms, CURDATE() - INTERVAL 6 DAY, '09:00:00', '10:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 6 DAY, '08:56:00'), TIMESTAMP(CURDATE() - INTERVAL 6 DAY, '10:04:00'), 'A-301', 'Relational algebra'),
  (@ds,   @t_ds, CURDATE() - INTERVAL 5 DAY, '11:00:00', '12:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 5 DAY, '10:59:00'), TIMESTAMP(CURDATE() - INTERVAL 5 DAY, '12:01:00'), 'A-302', 'Deadlocks'),
  (@oop,  @t_oop, CURDATE() - INTERVAL 4 DAY, '14:00:00', '15:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 4 DAY, '13:58:00'), TIMESTAMP(CURDATE() - INTERVAL 4 DAY, '15:02:00'), 'B-105', 'Subnetting'),
  (@dbms, @t_dbms, CURDATE() - INTERVAL 2 DAY, '09:00:00', '10:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 2 DAY, '08:57:00'), TIMESTAMP(CURDATE() - INTERVAL 2 DAY, '10:03:00'), 'A-301', 'Normalisation'),
  (@ds,   @t_ds, CURDATE() - INTERVAL 1 DAY, '11:00:00', '12:00:00', 10, 'CLOSED', TIMESTAMP(CURDATE() - INTERVAL 1 DAY, '10:58:00'), TIMESTAMP(CURDATE() - INTERVAL 1 DAY, '12:02:00'), 'A-302', 'Paging'),
  (@dbms, @t_dbms, CURDATE(),                  '09:00:00', '10:00:00', 10, 'SCHEDULED', NULL, NULL, 'A-301', 'Transactions and ACID'),
  (@ds,   @t_ds, CURDATE(),                  '11:00:00', '12:00:00', 10, 'SCHEDULED', NULL, NULL, 'A-302', 'Virtual memory');

-- Deterministic pseudo-random attendance for the closed sessions.
-- Roll 17-20 are "low attenders" so the shortage list is not empty.
INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at, marked_by)
SELECT y.session_id, y.prn, y.status,
       IF(y.status = 'ABSENT', 'AUTO', 'FACE_GROUP'),
       IF(y.status = 'ABSENT', NULL, ROUND(0.52 + (y.r % 35) / 100, 4)),
       IF(y.status = 'LATE',
          TIMESTAMP(y.session_date, y.start_time) + INTERVAL (12 + y.r % 18) MINUTE,
          TIMESTAMP(y.session_date, y.start_time) + INTERVAL (y.r % 6) MINUTE),
       NULL
  FROM (
        SELECT x.*,
               CASE
                 WHEN x.roll_no >= 17 THEN
                   CASE WHEN x.r < 45 THEN 'PRESENT' WHEN x.r < 58 THEN 'LATE' ELSE 'ABSENT' END
                 ELSE
                   CASE WHEN x.r < 82 THEN 'PRESENT' WHEN x.r < 94 THEN 'LATE' ELSE 'ABSENT' END
               END AS status
          FROM (
                SELECT ses.session_id, ses.session_date, ses.start_time, s.prn, s.roll_no,
                       CRC32(CONCAT(s.prn, '#', ses.session_id)) % 100 AS r
                  FROM sessions ses
                  JOIN enrollments e ON e.course_id = ses.course_id
                  JOIN students s ON s.prn = e.prn
                 WHERE ses.status = 'CLOSED'
               ) x
       ) y;

-- login principals (activated by the backend on first boot).
-- A teacher's username is the employee code, not their e-mail.
INSERT INTO users (username, password_hash, role, teacher_id)
SELECT employee_code, NULL, 'TEACHER', teacher_id FROM teachers;

INSERT INTO users (username, password_hash, role, prn)
SELECT prn, NULL, 'STUDENT', prn FROM students;

-- one pending correction request for the override workflow demo
INSERT INTO override_requests (session_id, prn, current_status, requested_status, reason, status, requested_by)
SELECT a.session_id, a.prn, a.status, 'PRESENT',
       'I was present but my face was hidden behind another student in the group photo.',
       'PENDING', u.user_id
  FROM attendance a
  JOIN users u ON u.prn = a.prn
 WHERE a.status = 'ABSENT'
 ORDER BY a.session_id, a.prn
 LIMIT 1;
