"""Pruebas del render de plantillas y placeholders."""

from app.services.email_template_service import RawHTML, render


def test_escapes_values():
    out = render("Hola {{name}}", {"name": "<b>Ana</b> & Co"})
    assert "<b>Ana</b>" not in out
    assert "&lt;b&gt;Ana&lt;/b&gt; &amp; Co" in out


def test_raw_html_passthrough():
    raw = RawHTML("<p><strong>Cert</strong></p>")
    out = render("{{line}}", {"line": raw})
    assert out == "<p><strong>Cert</strong></p>"


def test_missing_placeholder_preserved():
    out = render("A {{missing}} B", {})
    assert out == "A {{missing}} B"


def test_multiple_and_null_values():
    out = render(
        "{{a}}|{{b}}|{{c}}",
        {"a": "1", "b": None, "c": "3"},
    )
    assert out == "1|{{b}}|3"


def test_render_dashboard_message_default():
    from app.models.platform_settings import DEFAULT_DASHBOARD_MESSAGE

    out = render(
        DEFAULT_DASHBOARD_MESSAGE,
        {"app_name": "Certify", "organization": "ACME"},
    )
    assert out == "Panel principal de la plataforma Certify para la organización ACME"