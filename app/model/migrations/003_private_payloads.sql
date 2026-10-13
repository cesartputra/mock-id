ALTER TABLE principals ADD COLUMN display_login TEXT;
CREATE TABLE IF NOT EXISTS vault_metadata (id INTEGER PRIMARY KEY CHECK(id=1), key_check TEXT NOT NULL);
