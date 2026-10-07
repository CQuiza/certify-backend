"""Plantillas HTML por defecto para los correos.

Los placeholders ``{{key}}`` se interpolan en el servicio de plantillas. Cada
body incluye ``{{logo}}`` (rendered as an inline ``cid:logo`` image cuando hay
logo configurado; vacío en caso contrario).
"""

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "credentials": {
        "subject": "Tus credenciales de acceso — {{app_name}}",
        "body_html": """<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    {{logo}}
    <h2>Bienvenido a {{app_name}}</h2>
    <p>Tu cuenta ha sido creada exitosamente. Estas son tus credenciales de acceso:</p>
    <p><strong>Correo:</strong> {{email}}</p>
    <p><strong>Contraseña:</strong> {{password}}</p>
    <p style="color: #dc2626; font-weight: bold;">IMPORTANTE: Debes cambiar tu contraseña inmediatamente después de iniciar sesión por primera vez.</p>
    <p>Puedes acceder en el siguiente enlace:</p>
    <p><a href="{{login_url}}">{{login_url}}</a></p>
    <p style="color:#6b7280; font-size:12px;">{{organization_name}}</p>
</body>
</html>""",
    },
    "certificate_issued": {
        "subject": "Tu certificado ha sido emitido — {{app_name}}",
        "body_html": """<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    {{logo}}
    <h2>Certificado Emitido</h2>
    <p>Hola <strong>{{student_name}}</strong>,</p>
    <p>Te informamos que tu certificado ha sido emitido exitosamente.</p>
    {{certificate_type}}
    <p>Puedes verificar y descargar tu certificado en el siguiente enlace:</p>
    <p><a href="{{verify_link}}">{{verify_link}}</a></p>
    <p>Si tienes alguna duda, por favor contacta al administrador.</p>
    <p style="color:#6b7280; font-size:12px;">{{organization_name}}</p>
</body>
</html>""",
    },
    "certificate_expired": {
        "subject": "Tu certificado ha expirado — {{app_name}}",
        "body_html": """<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    {{logo}}
    <h2>Certificado Expirado</h2>
    <p>Hola <strong>{{student_name}}</strong>,</p>
    <p>Te informamos que tu certificado ha expirado.</p>
    <p>Si deseas obtener un nuevo certificado, por favor contacta al administrador.</p>
    <p style="color:#6b7280; font-size:12px;">{{organization_name}}</p>
</body>
</html>""",
    },
}

#: Descripción de placeholders disponibles para mostrar en la UI.
PLACEHOLDERS: dict[str, str] = {
    "app_name": "Nombre de la plataforma (ej. Certify)",
    "organization_name": "Nombre de la organización",
    "student_name": "Nombre del estudiante",
    "email": "Correo del destinatario",
    "password": "Contraseña generada (solo correo de credenciales)",
    "login_url": "URL de inicio de sesión",
    "verify_link": "Enlace de verificación del certificado",
    "certificate_type": "Línea con el tipo de certificado (solo emitido)",
    "logo": "Logo de la organización (imagen inline)",
}