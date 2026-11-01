// mongosh "mongodb://attendance_app:<password>@localhost:27018/attendance_logs?authSource=attendance_logs" docs/mongo/aggregations.js
const since = new Date(Date.now() - 30 * 24 * 3600 * 1000);
const tz = 'Asia/Kolkata';
const T = 0.45; // match threshold
const M = 0.08; // low-confidence margin

print('--- low-confidence matches per student ---');
printjson(db.recognition_logs.aggregate([
  { $match: { created_at: { $gte: since }, prn: { $ne: null }, confidence: { $gte: T - M, $lt: T + M } } },
  { $group: { _id: '$prn', occurrences: { $sum: 1 }, avg_confidence: { $avg: '$confidence' },
              min_confidence: { $min: '$confidence' }, last_seen: { $max: '$created_at' } } },
  { $sort: { occurrences: -1, avg_confidence: 1 } },
  { $limit: 20 },
]).toArray());

print('--- daily recognition stats ---');
printjson(db.recognition_logs.aggregate([
  { $match: { created_at: { $gte: since } } },
  { $group: {
      _id: { $dateToString: { format: '%Y-%m-%d', date: '$created_at', timezone: tz } },
      faces: { $sum: 1 },
      matched: { $sum: { $cond: [{ $eq: ['$status', 'MATCHED'] }, 1, 0] } },
      unsure: { $sum: { $cond: [{ $in: ['$status', ['LOW_CONFIDENCE', 'POSSIBLE']] }, 1, 0] } },
      unknown: { $sum: { $cond: [{ $in: ['$status', ['UNKNOWN', 'TOO_SMALL']] }, 1, 0] } },
      avg_confidence: { $avg: '$confidence' },
      avg_latency_ms: { $avg: '$latency_ms' },
  } },
  { $sort: { _id: 1 } },
]).toArray());

print('--- spoof attempts per day ---');
printjson(db.spoof_attempts.aggregate([
  { $match: { created_at: { $gte: since } } },
  { $project: { day: { $dateToString: { format: '%Y-%m-%d', date: '$created_at', timezone: tz } }, reasons: 1 } },
  { $facet: {
      totals: [{ $group: { _id: '$day', attempts: { $sum: 1 } } }, { $sort: { _id: 1 } }],
      reasons: [{ $unwind: '$reasons' }, { $group: { _id: { day: '$day', reason: '$reasons' }, n: { $sum: 1 } } }],
  } },
]).toArray());

print('--- templates per student and model (embeddings are encrypted, only metadata is read) ---');
printjson(db.face_embeddings.aggregate([
  { $match: { active: true } },
  { $group: { _id: { prn: '$prn', model: '$model' }, templates: { $sum: 1 }, poses: { $addToSet: '$pose' } } },
  { $sort: { templates: -1 } },
  { $limit: 10 },
]).toArray());

print('--- TTL indexes ---');
['recognition_logs', 'snapshots', 'notifications', 'attendance_drafts', 'liveness_nonces'].forEach((c) => {
  db[c].getIndexes().filter((i) => i.expireAfterSeconds !== undefined)
    .forEach((i) => print(`${c}.${i.name}: expires after ${i.expireAfterSeconds}s`));
});

print('--- query plan: a student\'s recent logs use the compound (prn, created_at) index ---');
printjson(db.recognition_logs.find({ prn: '12310005' }).sort({ created_at: -1 }).limit(5)
  .explain('queryPlanner').queryPlanner.winningPlan);
