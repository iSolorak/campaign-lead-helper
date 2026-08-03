from urllib.parse import urlsplit

from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def normalize_domain(value):
    """Normalize a website URL to a comparable IDNA hostname."""
    value = (value or "").strip()
    if not value or any(character.isspace() for character in value):
        return ""
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname.encode("idna").decode("ascii") if hostname else ""
    except (UnicodeError, ValueError):
        return ""


class Campaign(models.Model):
    class Provider(models.TextChoices):
        OVERPASS = "overpass", "OpenStreetMap Overpass"
        GOOGLE_PLACES = "google_places", "Google Places"

    name = models.CharField(max_length=200)
    search_term = models.CharField(max_length=100)
    text_search_query = models.CharField(
        max_length=300,
        blank=True,
        help_text="Optional Google Places free-text query, for example: Bar near Athens",
    )
    location = models.CharField(max_length=200)
    country = models.CharField(max_length=100, default="Greece")
    provider = models.CharField(
        max_length=30, choices=Provider.choices, default=Provider.OVERPASS
    )
    is_active = models.BooleanField(default=True)
    target_with_website = models.PositiveSmallIntegerField(default=10)
    target_without_website = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def save(self, *args, **kwargs):
        if self.provider == self.Provider.OVERPASS:
            from leads.providers.overpass import CATEGORY_TAGS, normalize_category
            category = normalize_category(self.search_term)
            if category in CATEGORY_TAGS:
                self.search_term = category
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWING = "reviewing", "Reviewing"
        READY = "ready", "Ready"
        CONTACTED = "contacted", "Contacted"
        REPLIED = "replied", "Replied"
        INTERESTED = "interested", "Interested"
        DECLINED = "declined", "Declined"
        FOLLOW_UP = "follow_up", "Follow up"
        DO_NOT_CONTACT = "do_not_contact", "Do not contact"
        INVALID = "invalid", "Invalid"

    class WebsiteVerification(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        CONFIRMED_NONE = "confirmed_none", "No website found in discovery source"
        FOUND_MANUALLY = "found_manually", "Found manually"
        SOCIAL_ONLY = "social_only", "Social only"
        VERIFIED = "verified", "Verified"

    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads"
    )
    source = models.CharField(max_length=50)
    source_id = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    phone = models.CharField(max_length=100, blank=True)
    website_url = models.URLField(max_length=500, blank=True)
    normalized_domain = models.CharField(max_length=255, blank=True, editable=False)
    email = models.EmailField(blank=True)
    instagram_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)
    website_verification_status = models.CharField(
        max_length=30,
        choices=WebsiteVerification.choices,
        default=WebsiteVerification.NOT_CHECKED,
    )
    priority_score = models.PositiveSmallIntegerField(
        default=0, validators=(MaxValueValidator(100),)
    )
    do_not_contact = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    discovered_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_follow_up_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-discovered_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_id"), name="unique_lead_source_source_id"
            )
        ]
        indexes = [
            models.Index(fields=("status",), name="lead_status_idx"),
            models.Index(fields=("campaign",), name="lead_campaign_idx"),
            models.Index(fields=("normalized_domain",), name="lead_norm_domain_idx"),
            models.Index(fields=("discovered_at",), name="lead_discovered_idx"),
            models.Index(fields=("next_follow_up_at",), name="lead_followup_idx"),
        ]

    @property
    def has_website(self):
        return bool(self.normalized_domain)

    @property
    def website_discovery_label(self):
        return "Website listed" if self.has_website else "No website listed in discovery source"

    def latest_lighthouse(self, strategy):
        return self.lighthouse_results.filter(strategy=strategy).order_by("-checked_at").first()

    @property
    def latest_mobile_result(self):
        return self.latest_lighthouse(LighthouseResult.Strategy.MOBILE)

    @property
    def latest_desktop_result(self):
        return self.latest_lighthouse(LighthouseResult.Strategy.DESKTOP)

    def calculate_priority_score(self):
        score = 0
        reasons = []
        if not self.has_website:
            score += 40
            reasons.append("No website listed: +40")
        mobile = self.latest_mobile_result
        if mobile:
            if mobile.performance is not None:
                if mobile.performance < 40:
                    score += 30
                    reasons.append("Mobile performance below 40: +30")
                elif mobile.performance < 60:
                    score += 20
                    reasons.append("Mobile performance below 60: +20")
            if mobile.accessibility is not None and mobile.accessibility < 80:
                score += 10
                reasons.append("Accessibility below 80: +10")
            if mobile.seo is not None and mobile.seo < 80:
                score += 10
                reasons.append("SEO below 80: +10")
        if self.email:
            score += 10
            reasons.append("Confirmed email available: +10")
        return min(score, 100), reasons

    def recalculate_priority(self, save=True):
        self.priority_score = self.calculate_priority_score()[0]
        if save:
            self.save(update_fields=("priority_score", "updated_at"))
        return self.priority_score

    def save(self, *args, **kwargs):
        self.normalized_domain = normalize_domain(self.website_url)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "website_url" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"normalized_domain"}
        super().save(*args, **kwargs)
        calculated = self.calculate_priority_score()[0]
        if calculated != self.priority_score:
            type(self).objects.filter(pk=self.pk).update(priority_score=calculated)
            self.priority_score = calculated

    def __str__(self):
        return self.business_name


class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Note for {self.lead}"


class LighthouseResult(models.Model):
    class Strategy(models.TextChoices):
        MOBILE = "mobile", "Mobile"
        DESKTOP = "desktop", "Desktop"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="lighthouse_results")
    strategy = models.CharField(max_length=10, choices=Strategy.choices)
    performance = models.PositiveSmallIntegerField(null=True, blank=True)
    accessibility = models.PositiveSmallIntegerField(null=True, blank=True)
    best_practices = models.PositiveSmallIntegerField(null=True, blank=True)
    seo = models.PositiveSmallIntegerField(null=True, blank=True)
    first_contentful_paint_ms = models.FloatField(null=True, blank=True)
    largest_contentful_paint_ms = models.FloatField(null=True, blank=True)
    cumulative_layout_shift = models.FloatField(null=True, blank=True)
    total_blocking_time_ms = models.FloatField(null=True, blank=True)
    final_url = models.URLField(max_length=1000, blank=True)
    error_message = models.TextField(blank=True)
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-checked_at",)
        indexes = [models.Index(fields=("lead", "strategy", "-checked_at"), name="lh_latest_idx")]

    @property
    def succeeded(self):
        return not self.error_message

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        Lead.objects.get(pk=self.lead_id).recalculate_priority()

    def __str__(self):
        return f"{self.lead} - {self.get_strategy_display()} - {self.checked_at:%Y-%m-%d}"


class WebsiteInspection(models.Model):
    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="website_inspection")
    final_url = models.URLField(max_length=1000, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    page_title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    has_contact_page = models.BooleanField(default=False)
    has_privacy_page = models.BooleanField(default=False)
    has_https = models.BooleanField(default=False)
    has_viewport_meta = models.BooleanField(default=False)
    robots_allowed = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    inspected_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Website inspection for {self.lead}"


class OutreachMessage(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        INSTAGRAM = "instagram", "Instagram"
        PHONE = "phone", "Phone"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        REPLIED = "replied", "Replied"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="outreach_messages")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    recipient = models.CharField(max_length=320, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_channel_display()} to {self.recipient or self.lead}"


class EmailTemplate(models.Model):
    name = models.CharField(max_length=200, unique=True)
    subject_template = models.CharField(max_length=500)
    body_template = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def clean(self):
        from string import Formatter
        from leads.services.outreach import SUPPORTED_PLACEHOLDERS
        fields = {field for value in (self.subject_template, self.body_template) for _, field, _, _ in Formatter().parse(value) if field}
        unsupported = fields - SUPPORTED_PLACEHOLDERS
        if unsupported:
            raise ValidationError(f"Unsupported placeholders: {', '.join(sorted(unsupported))}")

    def __str__(self):
        return self.name


class IntegrationSettings(models.Model):
    """Single-user runtime integration configuration managed in the dashboard."""

    class EmailBackend(models.TextChoices):
        CONSOLE = "django.core.mail.backends.console.EmailBackend", "Console (development)"
        SMTP = "django.core.mail.backends.smtp.EmailBackend", "SMTP"

    google_places_enabled = models.BooleanField(default=False)
    google_places_api_key = models.CharField(max_length=500, blank=True)
    google_pagespeed_api_key = models.CharField(max_length=500, blank=True)
    overpass_api_url = models.URLField(
        max_length=500, default="https://overpass-api.de/api/interpreter"
    )
    outbound_user_agent = models.CharField(
        max_length=500,
        default="LeadResearchDashboard/1.0 (personal research)",
    )
    email_backend = models.CharField(
        max_length=100,
        choices=EmailBackend.choices,
        default=EmailBackend.CONSOLE,
    )
    email_host = models.CharField(max_length=255, blank=True)
    email_port = models.PositiveIntegerField(default=587)
    email_host_user = models.CharField(max_length=255, blank=True)
    email_host_password = models.CharField(max_length=500, blank=True)
    email_use_tls = models.BooleanField(default=True)
    email_use_ssl = models.BooleanField(default=False)
    default_from_email = models.EmailField(default="webmaster@localhost")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "integration settings"

    @classmethod
    def load(cls):
        settings_object = cls.objects.order_by("pk").first()
        return settings_object or cls()

    def save(self, *args, **kwargs):
        if not self.pk:
            existing = type(self).objects.order_by("pk").first()
            if existing:
                self.pk = existing.pk
        super().save(*args, **kwargs)

    def __str__(self):
        return "Integration settings"
