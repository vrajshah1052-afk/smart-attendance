# Hosting on Render

One Docker web service on Render runs the whole app: FastAPI, the built React
app and the ArcFace ONNX models in a single container (`Dockerfile`, served by
`app.serve`). Render has no MySQL, so the two databases live on free tiers
elsewhere:

| Piece | Where | Free plan |
|---|---|---|
| API + web app + face engine | Render web service | 512 MB, spins down when idle |
| MySQL (students, attendance, audit, sagas) | Aiven for MySQL | 1 node, TLS only |
| MongoDB (face templates, logs, notifications) | MongoDB Atlas | M0 shared |

`render.yaml` is a Blueprint: it describes the service and every environment
variable, so Render only asks for the handful marked `sync: false`.

---

## 1. MySQL on Aiven

1. Create a free **MySQL** service. Any region works; Singapore keeps latency
   low for `region: singapore` in `render.yaml`.
2. Copy the **Service URI** from the service Overview page.
3. Create `.env.cloud` in the project root (it is git-ignored):

   ```
   MYSQL_URI=mysql://avnadmin:<password>@<host>:<port>/defaultdb?ssl-mode=REQUIRED
   MYSQL_APP_USER=attendance_app
   MYSQL_APP_PASSWORD=<pick one, no single quotes>
   MYSQL_ADMIN_USER=attendance_admin
   MYSQL_ADMIN_PASSWORD=<pick one>
   MYSQL_REPORT_USER=attendance_report
   MYSQL_REPORT_PASSWORD=<pick one>
   ```

4. Load the schema, the seed data, the least-privilege users and every
   migration:

   ```
   backend\.venv\Scripts\python.exe -I local\setup_db.py --env-file .env.cloud
   ```

   Re-run this after pulling changes that add a file to `db/mysql/migrations`.
   It is safe to run again: the schema step is skipped once `attendance_db`
   exists, and a migration already applied is reported as such.

## 2. MongoDB on Atlas

1. Create a free **M0** cluster and a database user.
2. Network Access: allow `0.0.0.0/0`. A free Render service has no static
   outbound IP, so an address allow-list cannot be narrowed.
3. Copy the connection string:
   `mongodb+srv://<user>:<password>@<cluster>/?retryWrites=true&w=majority`

Nothing else is needed: the backend creates the collections, indexes and TTL
rules on start-up.

## 3. The Render service

1. Push this repository to GitHub.
2. Render dashboard → **New** → **Blueprint** → pick the repository. Render
   reads `render.yaml`.
3. Fill in the five values it asks for:

   | Variable | Value |
   |---|---|
   | `MYSQL_HOST` | Aiven host |
   | `MYSQL_PORT` | Aiven port |
   | `MYSQL_APP_PASSWORD` | the `attendance_app` password from `.env.cloud` |
   | `MONGO_URI` | the Atlas connection string |
   | `TEACHER_PASSWORD` | password for the teacher login |

4. Apply. The first build takes roughly ten minutes: it installs the Python
   dependencies, downloads the `buffalo_s` ONNX models and builds the React app.

`smart-attendance.onrender.com` is already taken by an unrelated app, so Render
will hand the service a suffixed hostname such as
`smart-attendance-ab12.onrender.com`. Take the URL from the service page rather
than guessing it, and rename `services[0].name` in `render.yaml` first if you
want a different one. Renaming after the Blueprint exists creates a second
service, so decide before the first apply.

### What the first boot does

- creates the admin account from `ADMIN_EMAIL` and the generated
  `ADMIN_PASSWORD` — read it under **Environment** in the Render dashboard, and
  change it from the app afterwards;
- creates the teacher from `TEACHER_EMPLOYEE_CODE` (username) and
  `TEACHER_PASSWORD`, and re-syncs that password on every later deploy;
- creates the MongoDB collections, indexes and TTL rules;
- loads the face engine (the first request after a cold start is slow).

### Logging in

| Who | Username | Password |
|---|---|---|
| Admin | `ADMIN_EMAIL` | `ADMIN_PASSWORD` (generated, in the dashboard) |
| Teacher | `TEACHER_EMPLOYEE_CODE`, e.g. `100101` | `TEACHER_PASSWORD` |
| Student | their PRN | chosen at sign-up |

Students sign up themselves at `/signup`. The account is held until an admin
approves it under **Admin → Pending approvals**; after that the student joins
courses with a class code.

---

## Things worth knowing

**Never change `EMBEDDING_ENC_KEY`.** Stored face templates are encrypted with
it; a new key makes every enrolled face unreadable. To rotate it, put the new
key first and keep the old one after it, comma-separated.

**QR codes point at the right host by themselves.** `FRONTEND_URL` is left
unset in the Blueprint, so the app falls back to `RENDER_EXTERNAL_URL`. Set
`FRONTEND_URL` only once you put a custom domain in front of the service.

**The free instance spins down after inactivity.** The first request then waits
for the container and the face engine. `healthCheckPath` is
`/api/health/live`, which answers without touching the databases;
`/api/health` reports what MySQL and MongoDB are actually doing.

**Memory is tight at 512 MB.** The image pins `buffalo_s` (not `buffalo_l`),
one compute thread and `FACE_LOW_MEMORY=true`. Group photos of a large class
are the heaviest operation; if the instance restarts under load, that is where
to look first.

**`autoDeploy` is on.** Every push to the default branch redeploys. Migrations
are not applied by the deploy — run `local/setup_db.py --env-file .env.cloud`
yourself when a release adds one. The application MySQL user has no `ALTER`
grant on purpose; start-up notices a missing migration and logs which file to
run instead of failing.

**E-mail is off** (`EMAIL_ENABLED=false`). Daily summaries and shortage alerts
are written to the in-app notification inbox only. Point `SMTP_*` at a real
provider to turn them into mail.
