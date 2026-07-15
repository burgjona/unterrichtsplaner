-- Meilenstein 12 / U10 – Branding: Logo (Browser-Favicon & PWA-App-Icon).
-- Pfad zur Logo-Datei relativ zum storage_root (im .branding-Unterbaum); NULL = kein Logo.

ALTER TABLE user_settings ADD COLUMN logo_path TEXT;
