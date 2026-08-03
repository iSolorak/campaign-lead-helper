from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("lighthouse/analyze-pending/", views.analyze_pending_websites, name="analyze-pending-websites"),
    path("theme/toggle/", views.toggle_theme, name="toggle-theme"),
    path("settings/integrations/", views.integration_settings, name="integration-settings"),
    path("settings/integrations/test-google/", views.test_google_places, name="test-google-places"),
    path("leads/", views.lead_list, name="lead-list"),
    path("leads/new/", views.lead_create, name="lead-create"),
    path("leads/bulk-delete/", views.bulk_delete_leads, name="lead-bulk-delete"),
    path("leads/bulk-analyze/", views.bulk_analyze_leads, name="lead-bulk-analyze"),
    path("leads/<int:pk>/", views.lead_detail, name="lead-detail"),
    path("leads/<int:pk>/edit/", views.lead_edit, name="lead-edit"),
    path("leads/<int:pk>/notes/", views.add_note, name="add-note"),
    path("leads/<int:pk>/status/", views.update_status, name="update-status"),
    path("leads/<int:pk>/manual-outreach/", views.manual_outreach, name="manual-outreach"),
    path("leads/<int:pk>/email/", views.compose_email, name="compose-email"),
    path("messages/<int:pk>/send/", views.send_email_view, name="send-email"),
    path("leads/<int:pk>/lighthouse/", views.refresh_lighthouse, name="refresh-lighthouse"),
    path("leads/<int:pk>/inspect/", views.inspect_website, name="inspect-website"),
    path("campaigns/", views.campaign_list, name="campaign-list"),
    path("campaigns/new/", views.campaign_create, name="campaign-create"),
    path("campaigns/<int:pk>/edit/", views.campaign_edit, name="campaign-edit"),
    path("campaigns/<int:pk>/collect/", views.campaign_collect, name="campaign-collect"),
    path("campaigns/<int:pk>/toggle/", views.campaign_toggle, name="campaign-toggle"),
    path("email-templates/", views.email_template_list, name="email-template-list"),
    path("email-templates/new/", views.email_template_create, name="email-template-create"),
    path("email-templates/<int:pk>/edit/", views.email_template_edit, name="email-template-edit"),
    path("email-templates/<int:pk>/toggle/", views.email_template_toggle, name="email-template-toggle"),
]
