"""Cálculo de caducidad de certificados y conversión a texto en español."""

from datetime import UTC, datetime, timedelta


def number_to_spanish_years_text(years: int) -> str:
    _UNITS = ["", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
    _TENS = ["", "diez", "veinte", "treinta", "cuarenta", "cincuenta",
             "sesenta", "setenta", "ochenta", "noventa"]
    _TEENS = ["diez", "once", "doce", "trece", "catorce", "quince",
              "dieciséis", "diecisiete", "dieciocho", "diecinueve"]

    if years == 0:
        word = "cero"
    elif years < 10:
        word = _UNITS[years]
    elif years < 20:
        word = _TEENS[years - 10]
    elif years < 100:
        t = years // 10
        u = years % 10
        if u == 0:
            word = _TENS[t]
        else:
            word = f"{_TENS[t]} y {_UNITS[u]}"
    else:
        word = str(years)

    plural = "año" if years == 1 else "años"
    return f"{word} ({years}) {plural}"


def normalize_issue_date(issued_at: datetime | None) -> datetime:
    """Normaliza la fecha de expedición de un certificado.

    Si no se recibe fecha, se usa el instante actual. Si la fecha no tiene zona
    horaria se asume UTC. Cuando la fecha llega a medianoche (valor que produce un
    ``<input type="date">``) se fija a mediodía para que el día calendario no se
    desplace al mostrarlo en zonas horarias negativas (p. ej. UTC-5).
    """
    if issued_at is None:
        return datetime.now(UTC)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    if (
        issued_at.hour == 0
        and issued_at.minute == 0
        and issued_at.second == 0
        and issued_at.microsecond == 0
    ):
        issued_at = issued_at.replace(hour=12)
    return issued_at


def compute_certificate_expires_at(
    issued_at: datetime,
    validity_type: str,
    validity_value: int,
) -> datetime:
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    vt = validity_type.lower().strip()
    if vt == "days":
        return issued_at + timedelta(days=validity_value)
    if vt == "months":
        return issued_at + timedelta(days=30 * validity_value)
    if vt == "years":
        return issued_at + timedelta(days=365 * validity_value)
    raise ValueError(f"Tipo de validez no soportado: {validity_type}")
