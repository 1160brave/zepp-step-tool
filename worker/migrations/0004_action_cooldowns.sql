ALTER TABLE profiles ADD COLUMN manual_cooldown_until INTEGER NOT NULL DEFAULT 0;
ALTER TABLE profiles ADD COLUMN settings_cooldown_until INTEGER NOT NULL DEFAULT 0;
