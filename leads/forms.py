from django import forms

from .models import Campaign, EmailTemplate, IntegrationSettings, Lead, LeadNote, OutreachMessage
from .providers.overpass import CATEGORY_TAGS, normalize_category
from .services.outreach import render_email_template


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ("campaign", "business_name", "category", "address", "city", "country", "phone", "website_url", "email", "instagram_url", "status", "website_verification_status", "next_follow_up_at", "do_not_contact", "is_archived")
        widgets = {"next_follow_up_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class LeadNoteForm(forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ("text",)
        widgets = {"text": forms.Textarea(attrs={"rows": 3})}


class StatusForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ("status", "next_follow_up_at", "do_not_contact", "is_archived")
        widgets = {"next_follow_up_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ManualOutreachForm(forms.ModelForm):
    class Meta:
        model = OutreachMessage
        fields = ("channel", "recipient", "body", "status")

    def clean_channel(self):
        channel = self.cleaned_data["channel"]
        if channel == OutreachMessage.Channel.EMAIL:
            raise forms.ValidationError("Use the email composer for email messages.")
        return channel


class EmailComposerForm(forms.ModelForm):
    template = forms.ModelChoiceField(queryset=EmailTemplate.objects.none(), required=False)

    class Meta:
        model = OutreachMessage
        fields = ("template", "recipient", "subject", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 12})}

    def __init__(self, *args, lead=None, **kwargs):
        self.lead = lead
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = EmailTemplate.objects.filter(is_active=True)
        if lead and not self.is_bound:
            self.initial.setdefault("recipient", lead.email)
            template_id = self.initial.get("template")
            if template_id:
                template = EmailTemplate.objects.filter(pk=template_id, is_active=True).first()
                if template:
                    self.initial["subject"], self.initial["body"] = render_email_template(template, lead)

    def save(self, commit=True):
        message = super().save(commit=False)
        message.lead = self.lead
        message.channel = OutreachMessage.Channel.EMAIL
        message.status = OutreachMessage.Status.DRAFT
        if commit: message.save()
        return message


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ("name", "provider", "search_term", "text_search_query", "location", "country", "is_active", "target_with_website", "target_without_website")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["search_term"].help_text = "Structured category used by Overpass and as the Google fallback."
        self.fields["text_search_query"].help_text = "Google Places only. Example: Bar near Athens. Leave blank for structured category search."

    def clean(self):
        cleaned = super().clean()
        search_term = cleaned.get("search_term", "")
        if cleaned.get("provider") == Campaign.Provider.OVERPASS:
            canonical = normalize_category(search_term)
            if canonical not in CATEGORY_TAGS:
                self.add_error("search_term", f"Use a supported category: {', '.join(sorted(CATEGORY_TAGS))}. Common names such as barber and coffee are accepted.")
            else:
                cleaned["search_term"] = canonical
            cleaned["text_search_query"] = ""
        return cleaned


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ("name", "subject_template", "body_template", "is_active")
        widgets = {"body_template": forms.Textarea(attrs={"rows": 10})}


class IntegrationSettingsForm(forms.ModelForm):
    clear_google_places_key = forms.BooleanField(required=False)
    clear_pagespeed_key = forms.BooleanField(required=False)
    clear_email_password = forms.BooleanField(required=False)

    class Meta:
        model = IntegrationSettings
        fields = (
            "google_places_enabled", "google_places_api_key",
            "clear_google_places_key", "google_pagespeed_api_key",
            "clear_pagespeed_key", "overpass_api_url", "outbound_user_agent",
            "email_backend", "email_host", "email_port", "email_host_user",
            "email_host_password", "clear_email_password", "email_use_tls",
            "email_use_ssl", "default_from_email",
        )
        widgets = {
            "google_places_api_key": forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password", "placeholder": "Leave blank to keep the saved key"},
            ),
            "google_pagespeed_api_key": forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password", "placeholder": "Leave blank to keep the saved key"},
            ),
            "email_host_password": forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password", "placeholder": "Leave blank to keep the saved password"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._places_key = self.instance.google_places_api_key
        self._pagespeed_key = self.instance.google_pagespeed_api_key
        self._email_password = self.instance.email_host_password
        self.fields["google_places_api_key"].required = False
        self.fields["google_pagespeed_api_key"].required = False
        self.fields["google_places_api_key"].help_text = "Stored key is configured." if self._places_key else "No key configured."
        self.fields["google_pagespeed_api_key"].help_text = "Stored key is configured." if self._pagespeed_key else "No key configured."
        self.fields["email_host_password"].required = False
        self.fields["email_host_password"].help_text = "Stored password is configured." if self._email_password else "No password configured."

    def clean(self):
        cleaned = super().clean()
        places_value = cleaned.get("google_places_api_key", "").strip()
        pagespeed_value = cleaned.get("google_pagespeed_api_key", "").strip()
        cleaned["google_places_api_key"] = "" if cleaned.get("clear_google_places_key") else places_value or self._places_key
        cleaned["google_pagespeed_api_key"] = "" if cleaned.get("clear_pagespeed_key") else pagespeed_value or self._pagespeed_key
        email_password = cleaned.get("email_host_password", "").strip()
        cleaned["email_host_password"] = "" if cleaned.get("clear_email_password") else email_password or self._email_password
        if cleaned.get("email_use_tls") and cleaned.get("email_use_ssl"):
            self.add_error("email_use_ssl", "TLS and SSL cannot both be enabled.")
        if cleaned.get("email_backend") == IntegrationSettings.EmailBackend.SMTP and not cleaned.get("email_host"):
            self.add_error("email_host", "SMTP host is required when the SMTP backend is selected.")
        return cleaned
