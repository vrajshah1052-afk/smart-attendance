-- Students who signed up themselves wait in PENDING_APPROVAL until an admin approves them.
-- Safe to re-run: MODIFY COLUMN just restates the full enum.
ALTER TABLE students
  MODIFY COLUMN face_status ENUM('PENDING','PENDING_APPROVAL','ENROLLED','REENROLL_REQUIRED')
  NOT NULL DEFAULT 'PENDING';
