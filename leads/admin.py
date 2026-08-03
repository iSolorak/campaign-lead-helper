from io import StringIO

from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError

from .models import (
    Campaign, EmailTemplate, IntegrationSettings, Lead, LeadNote, LighthouseResult,
    OutreachMessage, WebsiteInspection,
)
from .forms import CampaignForm, IntegrationSettingsForm


class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0
    fields = ("text", "created_at")
    readonly_fields = ("created_at",)


class OutreachInline(admin.TabularInline):
    model = OutreachMessage
    extra = 0
    fields = ("channel", "recipient", "status", "sent_at")
    readonly_fields = ("sent_at",)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    form = CampaignForm
    list_display = ("name", "search_term", "text_search_query", "location", "country", "provider", "is_active")
    list_filter = ("provider", "is_active", "created_at")
    search_fields = ("name", "search_term", "text_search_query", "location", "country")
    readonly_fields = ("created_at", "updated_at")
    actions = ("collect_selected_leads",)

    @admin.action(description="Collect leads for selected active campaigns")
    def collect_selected_leads(self, request, queryset):
        active_ids = list(queryset.filter(is_active=True).values_list("pk", flat=True))
        skipped = queryset.count() - len(active_ids)
        if not active_ids:
            self.message_user(request, "No active campaigns were selected.", level="warning")
            return
        stdout, stderr = StringIO(), StringIO()
        try:
            call_command("collect_leads", campaign_ids=active_ids, stdout=stdout, stderr=stderr)
        except CommandError as exc:
            self.message_user(request, f"Lead collection failed: {exc}", level="error")
            return
        summary = next((line for line in reversed(stdout.getvalue().splitlines()) if line.startswith("Collection summary:")), "Lead collection finished.")
        if skipped:
            summary += f" Skipped {skipped} inactive campaign(s)."
        self.message_user(request, summary, level="success")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("business_name", "category", "city", "source", "status", "priority_score", "has_website", "next_follow_up_at")
    list_filter = ("status", "source", "campaign", "category", "website_verification_status", "do_not_contact", "is_archived")
    search_fields = ("business_name", "normalized_domain", "address", "phone", "email")
    autocomplete_fields = ("campaign",)
    readonly_fields = ("normalized_domain", "priority_score", "discovered_at", "created_at", "updated_at")
    inlines = (LeadNoteInline, OutreachInline)


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    list_display = ("lead", "created_at", "updated_at")
    search_fields = ("text", "lead__business_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("lead",)


@admin.register(LighthouseResult)
class LighthouseResultAdmin(admin.ModelAdmin):
    list_display = ("lead", "strategy", "performance", "accessibility", "seo", "checked_at", "succeeded")
    list_filter = ("strategy", "checked_at")
    search_fields = ("lead__business_name", "final_url", "error_message")
    readonly_fields = ("checked_at",)
    autocomplete_fields = ("lead",)


@admin.register(WebsiteInspection)
class WebsiteInspectionAdmin(admin.ModelAdmin):
    list_display = ("lead", "http_status", "has_https", "robots_allowed", "inspected_at")
    search_fields = ("lead__business_name", "final_url", "page_title")
    readonly_fields = ("inspected_at",)
    autocomplete_fields = ("lead",)


@admin.register(OutreachMessage)
class OutreachMessageAdmin(admin.ModelAdmin):
    list_display = ("lead", "channel", "recipient", "status", "sent_at", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("lead__business_name", "recipient", "subject")
    readonly_fields = ("sent_at", "created_at", "updated_at")
    autocomplete_fields = ("lead",)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "subject_template", "body_template")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IntegrationSettings)
class IntegrationSettingsAdmin(admin.ModelAdmin):
    form = IntegrationSettingsForm
    list_display = ("overpass_api_url", "google_places_enabled", "updated_at")
    readonly_fields = ("updated_at",)
