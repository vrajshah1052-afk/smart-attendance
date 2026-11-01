// =====================================================================
//  MongoDB 7 initialisation (runs once on first container start).
//  - creates the least-privilege application user
//  - creates collections with $jsonSchema validators
//  - creates compound + TTL indexes
//  The backend re-applies the same schema idempotently at start-up
//  (app/db/mongo_schema.py), so a fresh test database is self-healing.
// =====================================================================

const dbName = process.env.MONGO_INITDB_DATABASE || 'attendance_logs';
const testDbName = dbName + '_test';
const appUser = process.env.MONGO_APP_USER;
const appPass = process.env.MONGO_APP_PASSWORD;
const logTtlDays = parseInt(process.env.RECOGNITION_LOG_TTL_DAYS || '90', 10);
const snapshotTtlDays = parseInt(process.env.SNAPSHOT_TTL_DAYS || '30', 10);
const DAY = 24 * 60 * 60;

const NUM = ['double', 'int', 'long', 'decimal'];

const validators = {
  face_embeddings: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['prn', 'model', 'dim', 'embedding_enc', 'source', 'active', 'created_at'],
      properties: {
        prn: { bsonType: 'string', pattern: '^[A-Z0-9]{6,20}$' },
        model: { bsonType: 'string' },
        dim: { bsonType: ['int', 'long'], minimum: 64, maximum: 4096 },
        embedding_enc: { bsonType: 'binData', description: 'Fernet (AES-128-CBC + HMAC-SHA256) encrypted float32 vector' },
        pose: { bsonType: ['string', 'null'] },
        yaw: { bsonType: NUM.concat(['null']) },
        quality: { bsonType: 'object' },
        source: { enum: ['REGISTRATION', 'ADD_PHOTOS', 'AUTO_REENROLL', 'REVIEW', 'SYNTHETIC'] },
        active: { bsonType: 'bool' },
        saga_id: { bsonType: ['string', 'null'] },
        created_at: { bsonType: 'date' },
      },
    },
  },
  recognition_logs: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['kind', 'status', 'created_at'],
      properties: {
        kind: { enum: ['GROUP', 'SOLO', 'LIVE', 'QR'] },
        status: { enum: ['MATCHED', 'LOW_CONFIDENCE', 'POSSIBLE', 'UNKNOWN', 'SPOOF_SUSPECTED', 'TOO_SMALL'] },
        prn: { bsonType: ['string', 'null'] },
        confidence: { bsonType: NUM.concat(['null']) },
        session_id: { bsonType: ['int', 'long', 'null'] },
        created_at: { bsonType: 'date' },
      },
    },
  },
  snapshots: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['kind', 'image', 'created_at'],
      properties: {
        kind: { enum: ['GROUP_ANNOTATED', 'UNKNOWN_FACE', 'SPOOF', 'LATE', 'REVIEW_FACE'] },
        image: { bsonType: 'binData' },
        content_type: { bsonType: 'string' },
        created_at: { bsonType: 'date' },
      },
    },
  },
  notifications: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['type', 'title', 'message', 'created_at'],
      properties: {
        type: { enum: ['LATE', 'SHORTAGE', 'UNKNOWN_FACE', 'SPOOF', 'REENROLL', 'OVERRIDE', 'SESSION', 'SYSTEM', 'DAILY_SUMMARY', 'REVIEW', 'ATTENDANCE'] },
        title: { bsonType: 'string' },
        message: { bsonType: 'string' },
        recipient_prn: { bsonType: ['string', 'null'] },
        recipient_user_id: { bsonType: ['int', 'long', 'null'] },
        audience_role: { enum: ['ADMIN', 'TEACHER', 'STUDENT', null] },
        read_by: { bsonType: 'array' },
        created_at: { bsonType: 'date' },
      },
    },
  },
  spoof_attempts: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['endpoint', 'reasons', 'created_at'],
      properties: {
        endpoint: { bsonType: 'string' },
        reasons: { bsonType: 'array', items: { bsonType: 'string' } },
        prn: { bsonType: ['string', 'null'] },
        session_id: { bsonType: ['int', 'long', 'null'] },
        created_at: { bsonType: 'date' },
      },
    },
  },
  review_queue: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['session_id', 'status', 'confidence', 'created_at'],
      properties: {
        session_id: { bsonType: ['int', 'long'] },
        prn: { bsonType: ['string', 'null'] },
        confidence: { bsonType: NUM },
        status: { enum: ['PENDING', 'APPROVED', 'REJECTED'] },
        created_at: { bsonType: 'date' },
      },
    },
  },
  attendance_drafts: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['session_id', 'kind', 'status', 'created_at', 'expires_at'],
      properties: {
        session_id: { bsonType: ['int', 'long'] },
        kind: { enum: ['GROUP', 'LIVE'] },
        status: { enum: ['OPEN', 'COMMITTING', 'COMMITTED'] },
        created_at: { bsonType: 'date' },
        expires_at: { bsonType: 'date' },
      },
    },
  },
};

function ensureCollection(database, name) {
  const exists = database.getCollectionNames().includes(name);
  if (!exists) {
    database.createCollection(name, {
      validator: validators[name],
      validationLevel: 'strict',
      validationAction: 'error',
    });
  } else if (validators[name]) {
    database.runCommand({ collMod: name, validator: validators[name], validationLevel: 'strict' });
  }
}

function setup(database) {
  Object.keys(validators).forEach((name) => ensureCollection(database, name));
  ['liveness_nonces', 'meta'].forEach((name) => {
    if (!database.getCollectionNames().includes(name)) database.createCollection(name);
  });

  // ---- face_embeddings: many vectors per student
  database.face_embeddings.createIndex({ prn: 1, created_at: -1 }, { name: 'prn_created' });
  database.face_embeddings.createIndex({ model: 1, active: 1 }, { name: 'model_active' });
  database.face_embeddings.createIndex({ saga_id: 1 }, { name: 'saga', sparse: true });

  // ---- recognition_logs: high-volume, auto-expiring (TTL)
  database.recognition_logs.createIndex({ prn: 1, created_at: -1 }, { name: 'prn_created' });
  database.recognition_logs.createIndex({ session_id: 1 }, { name: 'session' });
  database.recognition_logs.createIndex({ status: 1, created_at: -1 }, { name: 'status_created' });
  database.recognition_logs.createIndex({ created_at: 1 }, { name: 'ttl_created_at', expireAfterSeconds: logTtlDays * DAY });

  // ---- snapshots: annotated photos / unknown faces, short retention
  database.snapshots.createIndex({ created_at: 1 }, { name: 'ttl_created_at', expireAfterSeconds: snapshotTtlDays * DAY });
  database.snapshots.createIndex({ session_id: 1 }, { name: 'session' });
  database.snapshots.createIndex({ prn: 1 }, { name: 'prn', sparse: true });

  // ---- notifications
  database.notifications.createIndex({ recipient_prn: 1, created_at: -1 }, { name: 'prn_created' });
  database.notifications.createIndex({ recipient_user_id: 1, created_at: -1 }, { name: 'user_created' });
  database.notifications.createIndex({ audience_role: 1, created_at: -1 }, { name: 'role_created' });
  database.notifications.createIndex({ created_at: 1 }, { name: 'ttl_created_at', expireAfterSeconds: 180 * DAY });

  // ---- spoof attempts
  database.spoof_attempts.createIndex({ created_at: -1 }, { name: 'created' });
  database.spoof_attempts.createIndex({ prn: 1, created_at: -1 }, { name: 'prn_created' });

  // ---- review queue
  database.review_queue.createIndex({ status: 1, created_at: -1 }, { name: 'status_created' });
  database.review_queue.createIndex({ prn: 1 }, { name: 'prn' });

  // ---- drafts for "confirm before save" (expire automatically)
  database.attendance_drafts.createIndex({ expires_at: 1 }, { name: 'ttl_expires_at', expireAfterSeconds: 0 });
  database.attendance_drafts.createIndex({ session_id: 1, status: 1 }, { name: 'session_status' });

  // ---- one-time liveness challenge nonces (replay protection)
  database.liveness_nonces.createIndex({ nonce: 1 }, { name: 'nonce_unique', unique: true });
  database.liveness_nonces.createIndex({ created_at: 1 }, { name: 'ttl_created_at', expireAfterSeconds: 600 });

  // index-version counter used to keep in-memory vector indexes in sync
  database.meta.updateOne({ _id: 'embedding_index' }, { $setOnInsert: { version: 0 } }, { upsert: true });
}

const target = db.getSiblingDB(dbName);
if (appUser && appPass) {
  target.createUser({
    user: appUser,
    pwd: appPass,
    roles: [
      { role: 'readWrite', db: dbName },
      { role: 'readWrite', db: testDbName },
    ],
  });
  print(`[init-mongo] created user ${appUser}`);
}

setup(target);
setup(db.getSiblingDB(testDbName));

target.notifications.insertOne({
  type: 'SYSTEM',
  title: 'Welcome',
  message: 'Smart Attendance is ready. Register students to begin face enrolment.',
  audience_role: 'ADMIN',
  recipient_prn: null,
  recipient_user_id: null,
  read_by: [],
  data: {},
  created_at: new Date(),
});

print('[init-mongo] collections, validators and indexes ready');
