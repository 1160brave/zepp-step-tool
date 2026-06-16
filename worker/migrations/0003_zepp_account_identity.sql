CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_zepp_account_unique
  ON profiles(zepp_account COLLATE NOCASE)
  WHERE zepp_account IS NOT NULL;
