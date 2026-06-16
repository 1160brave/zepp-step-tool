CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL COLLATE NOCASE UNIQUE,
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profiles (
  user_id INTEGER PRIMARY KEY,
  zepp_account TEXT,
  zepp_password_enc TEXT,
  schedule_enabled INTEGER NOT NULL DEFAULT 0,
  schedule_hour INTEGER NOT NULL DEFAULT 18,
  schedule_minute INTEGER NOT NULL DEFAULT 18,
  min_steps INTEGER NOT NULL DEFAULT 18000,
  max_steps INTEGER NOT NULL DEFAULT 26000,
  last_run_date TEXT,
  last_status TEXT,
  last_message TEXT,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  trigger_type TEXT NOT NULL,
  steps INTEGER NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
  ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_profiles_schedule
  ON profiles(schedule_enabled, schedule_hour, schedule_minute);
CREATE INDEX IF NOT EXISTS idx_submissions_user_created
  ON submissions(user_id, created_at DESC);
