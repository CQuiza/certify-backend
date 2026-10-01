-- ============================================================
-- Migración 014: overrides por certificado (hours, validity_years)
-- Nullables: NULL = seguir el tipo; valor = override persistido
-- usado por generate/regenerate/renew/reproduce.
-- ============================================================

BEGIN;

ALTER TABLE certificates ADD COLUMN IF NOT EXISTS hours INTEGER;
ALTER TABLE certificates ADD COLUMN IF NOT EXISTS validity_years INTEGER;

COMMIT;