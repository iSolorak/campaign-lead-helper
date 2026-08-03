import logging
from string import Formatter

from django.core.exceptions import ValidationError
from django.core.mail import get_connection, send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from leads.models import Lead, OutreachMessage
from .runtime_settings import get_runtime_settings

logger = logging.getLogger(__name__)
SUPPORTED_PLACEHOLDERS = {
    "business_name", "category", "city", "website_url",
    "mobile_performance", "desktop_performance",
}


def render_email_template(template, lead):
    """Render only explicitly supported, flat placeholders."""
    fields = {field for text in (template.subject_template, template.body_template) for _, field, _, _ in Formatter().parse(text) if field}
    unsupported = fields - SUPPORTED_PLACEHOLDERS
    if unsupported:
        raise ValidationError(f"Unsupported placeholders: {', '.join(sorted(unsupported))}")
    mobile, desktop = lead.latest_mobile_result, lead.latest_desktop_result
    context = {
        "business_name": lead.business_name, "category": lead.category, "city": lead.city,
        "website_url": lead.website_url,
        "mobile_performance": mobile.performance if mobile and mobile.performance is not None else "N/A",
        "desktop_performance": desktop.performance if desktop and desktop.performance is not None else "N/A",
    }
    return template.subject_template.format_map(context), template.body_template.format_map(context)


def send_email_message(message):
    """Send an explicit email draft and mark the lead contacted only on success."""
    if message.channel != OutreachMessage.Channel.EMAIL:
        raise ValidationError("Only email messages can be sent automatically")
    if message.lead.do_not_contact:
        raise ValidationError("This lead is marked do not contact")
    validate_email(message.recipient)
    try:
        runtime = get_runtime_settings()
        connection = get_connection(
            runtime.email_backend,
            host=runtime.email_host,
            port=runtime.email_port,
            username=runtime.email_host_user,
            password=runtime.email_host_password,
            use_tls=runtime.email_use_tls,
            use_ssl=runtime.email_use_ssl,
            fail_silently=False,
        )
        sent = send_mail(
            message.subject,
            message.body,
            runtime.default_from_email,
            [message.recipient],
            fail_silently=False,
            connection=connection,
        )
        if sent != 1:
            raise RuntimeError("Email backend did not accept the message")
    except Exception as exc:
        message.status = OutreachMessage.Status.FAILED
        message.error_message = str(exc)[:1000]
        message.save(update_fields=("status", "error_message", "updated_at"))
        logger.error("Email send failed message=%s error=%s", message.pk, exc)
        return False
    with transaction.atomic():
        message.status = OutreachMessage.Status.SENT
        message.sent_at = timezone.now()
        message.error_message = ""
        message.save(update_fields=("status", "sent_at", "error_message", "updated_at"))
        Lead.objects.filter(pk=message.lead_id).update(status=Lead.Status.CONTACTED, updated_at=timezone.now())
    return True
