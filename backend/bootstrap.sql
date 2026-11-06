-- Run with a database administrator, then assign a dedicated application user.
-- Does not modify any existing business tables.
CREATE DATABASE IF NOT EXISTS hydro_oa
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- Configure DATABASE_URL with a user authorized only for hydro_oa.
-- Then run: python -m backend.sync init
