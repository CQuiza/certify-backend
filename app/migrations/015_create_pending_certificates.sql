-- ============================================================
-- Migración 015: solicitudes de certificado EN PROCESO.
-- El certificado se emite automáticamente cuando el estudiante
-- completa el curso al 100% (pending_certificates).
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS pending_certificates (
    id                    INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id             INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    certificate_type_id   INTEGER REFERENCES certificate_types(id),
    status                VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    created_by            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    issued_at_override    TIMESTAMPTZ,
    validity_extension    INTEGER,
    hours                 INTEGER,
    issued_certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    issued_at             TIMESTAMPTZ,
    CONSTRAINT uq_pending_user_course UNIQUE (user_id, course_id),
    CONSTRAINT ck_pending_certificates_status CHECK (status IN ('in_progress', 'issued'))
);

CREATE INDEX IF NOT EXISTS idx_pending_certificates_user
    ON pending_certificates (user_id);

CREATE INDEX IF NOT EXISTS idx_pending_certificates_course
    ON pending_certificates (course_id);

CREATE INDEX IF NOT EXISTS idx_pending_certificates_status
    ON pending_certificates (status);

COMMIT;