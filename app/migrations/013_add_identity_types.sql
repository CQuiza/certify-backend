-- ============================================================
-- Migración 013: Expandir tipos de identidad (CC, TI, CE, PPT, PASSPORT)
-- Aplicar: psql -d certify -f migrations/013_add_identity_types.sql
-- ============================================================

BEGIN;

ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_identity_type;
ALTER TABLE users ADD CONSTRAINT ck_users_identity_type
  CHECK (identity_type IN ('CC', 'TI', 'CE', 'PPT', 'PASSPORT', 'OTHER'));

COMMIT;
