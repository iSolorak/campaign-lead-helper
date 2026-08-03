from datetime import timedelta
from io import StringIO
from uuid import uuid4
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db.models import Avg, Count, OuterRef, Q, Subquery
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import CampaignForm, EmailComposerForm, EmailTemplateForm, IntegrationSettingsForm, LeadForm, LeadNoteForm, ManualOutreachForm, StatusForm
from .models import Campaign, EmailTemplate, IntegrationSettings, Lead, LighthouseResult, OutreachMessage
from .services.outreach import send_email_message
from .services.pagespeed import analyze_lead
from .services.website_inspection import inspect_lead_website
from .services.places import GooglePlacesClient, PlacesError
from .services.runtime_settings import get_runtime_settings


def staff_required(view):
    """Allow dashboard access only to authenticated Django staff users."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            raise PermissionDenied("Dashboard access requires a staff account.")
        return view(request, *args, **kwargs)
    return wrapped


def _scored_leads():
    latest = LighthouseResult.objects.filter(lead=OuterRef("pk"))
    return Lead.objects.select_related("campaign").annotate(
        mobile_performance=Subquery(latest.filter(strategy="mobile").order_by("-checked_at").values("performance")[:1]),
        desktop_performance=Subquery(latest.filter(strategy="desktop").order_by("-checked_at").values("performance")[:1]),
    )


@staff_required
def dashboard(request):
    leads = _scored_leads().filter(is_archived=False)
    now = timezone.now()
    context = {
        "new_count": leads.filter(status=Lead.Status.NEW).count(),
        "with_website": leads.exclude(normalized_domain="").count(),
        "without_website": leads.filter(normalized_domain="").count(),
        "ready": leads.filter(status=Lead.Status.READY).count(),
        "contacted": leads.filter(status=Lead.Status.CONTACTED).count(),
        "replies": leads.filter(status=Lead.Status.REPLIED).count(),
        "followups": leads.filter(next_follow_up_at__lte=now).count(),
        "declined": leads.filter(status=Lead.Status.DECLINED).count(),
        "averages": leads.aggregate(mobile=Avg("mobile_performance"), desktop=Avg("desktop_performance")),
        "campaign_count": Campaign.objects.count(),
    }
    return render(request, "leads/dashboard.html", context)


@staff_required
def analyze_pending_websites(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(("POST",))
    stdout, stderr = StringIO(), StringIO()
    call_command("analyze_pending_leads", stdout=stdout, stderr=stderr)
    summary = next(
        (
            line
            for line in reversed(stdout.getvalue().splitlines())
            if line.startswith("PageSpeed summary:")
        ),
        "PageSpeed analysis finished.",
    )
    if stderr.getvalue().strip():
        messages.warning(request, f"{summary}\n{stderr.getvalue().strip()}")
    else:
        messages.success(request, summary)
    return redirect("dashboard")


@staff_required
def lead_list(request):
    leads = _scored_leads()
    q = request.GET.get("q", "").strip()
    if q: leads = leads.filter(Q(business_name__icontains=q) | Q(normalized_domain__icontains=q) | Q(address__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    simple = {"campaign": "campaign_id", "source": "source", "category": "category", "city": "city", "country": "country", "status": "status", "website_status": "website_verification_status"}
    for param, field in simple.items():
        if request.GET.get(param): leads = leads.filter(**{field: request.GET[param]})
    if request.GET.get("has_website") == "yes": leads = leads.exclude(normalized_domain="")
    if request.GET.get("has_website") == "no": leads = leads.filter(normalized_domain="")
    if request.GET.get("has_email") == "yes": leads = leads.exclude(email="")
    if request.GET.get("has_email") == "no": leads = leads.filter(email="")
    if request.GET.get("contacted") == "yes": leads = leads.filter(status=Lead.Status.CONTACTED)
    if request.GET.get("follow_up_due") == "yes": leads = leads.filter(next_follow_up_at__lte=timezone.now())
    if request.GET.get("do_not_contact") == "yes": leads = leads.filter(do_not_contact=True)
    if request.GET.get("archived") != "yes": leads = leads.filter(is_archived=False)
    for param, lookup in (("mobile_min", "mobile_performance__gte"), ("mobile_max", "mobile_performance__lte"), ("desktop_min", "desktop_performance__gte"), ("desktop_max", "desktop_performance__lte"), ("discovered_from", "discovered_at__date__gte"), ("discovered_to", "discovered_at__date__lte")):
        if request.GET.get(param): leads = leads.filter(**{lookup: request.GET[param]})
    from django.core.paginator import Paginator
    page = Paginator(leads, 25).get_page(request.GET.get("page"))
    query = request.GET.copy(); query.pop("page", None)
    return render(request, "leads/lead_list.html", {"page_obj": page, "campaigns": Campaign.objects.all(), "status_choices": Lead.Status.choices, "querystring": query.urlencode()})


@staff_required
def bulk_delete_leads(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(("POST",))
    lead_ids = request.POST.getlist("lead_ids")
    leads = Lead.objects.filter(pk__in=lead_ids).order_by("business_name")
    if not lead_ids or not leads.exists():
        messages.warning(request, "Select at least one lead to delete.")
        return redirect("lead-list")
    if request.POST.get("confirm") != "yes":
        return render(
            request,
            "leads/confirm_bulk_delete.html",
            {"leads": leads, "lead_ids": list(leads.values_list("pk", flat=True))},
        )
    count = leads.count()
    leads.delete()
    messages.success(request, f"Deleted {count} lead{'s' if count != 1 else ''}.")
    return redirect("lead-list")


@staff_required
def bulk_analyze_leads(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(("POST",))
    lead_ids = request.POST.getlist("lead_ids")
    leads = Lead.objects.filter(pk__in=lead_ids).order_by("business_name")
    if not lead_ids or not leads.exists():
        messages.warning(request, "Select at least one lead to analyze.")
        return redirect("lead-list")
    if request.POST.get("confirm") != "yes":
        return render(
            request,
            "leads/confirm_bulk_analyze.html",
            {
                "leads": leads,
                "lead_ids": list(leads.values_list("pk", flat=True)),
                "website_count": leads.exclude(normalized_domain="").count(),
            },
        )

    analyzed = failed = skipped = 0
    for lead in leads.iterator():
        if not lead.has_website:
            skipped += 1
            continue
        try:
            results = analyze_lead(lead, force=True)
        except Exception:
            failed += 1
            continue
        if any(result.error_message for result in results):
            failed += 1
        else:
            analyzed += 1
    message = (
        f"Selected Lighthouse analysis: successful={analyzed}, "
        f"failed={failed}, no_website_skipped={skipped}."
    )
    if failed:
        messages.warning(request, message)
    else:
        messages.success(request, message)
    return redirect("lead-list")


@staff_required
def lead_detail(request, pk):
    lead = get_object_or_404(Lead.objects.select_related("campaign").prefetch_related("notes", "outreach_messages", "lighthouse_results"), pk=pk)
    return render(request, "leads/lead_detail.html", {"lead": lead, "priority_reasons": lead.calculate_priority_score()[1], "note_form": LeadNoteForm(), "status_form": StatusForm(instance=lead), "manual_form": ManualOutreachForm()})


@staff_required
def lead_edit(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    form = LeadForm(request.POST or None, instance=lead)
    if request.method == "POST" and form.is_valid():
        lead = form.save(); lead.recalculate_priority(); messages.success(request, "Lead updated."); return redirect("lead-detail", pk=pk)
    return render(request, "leads/form.html", {"form": form, "title": "Edit lead"})


@staff_required
def add_note(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    lead = get_object_or_404(Lead, pk=pk); form = LeadNoteForm(request.POST)
    if form.is_valid(): note = form.save(commit=False); note.lead = lead; note.save(); messages.success(request, "Note added.")
    else: messages.error(request, "Note could not be added.")
    return redirect("lead-detail", pk=pk)


@staff_required
def update_status(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    lead = get_object_or_404(Lead, pk=pk); form = StatusForm(request.POST, instance=lead)
    if form.is_valid(): form.save(); messages.success(request, "Lead status updated.")
    else: messages.error(request, "Status could not be updated.")
    return redirect("lead-detail", pk=pk)


@staff_required
def manual_outreach(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    lead = get_object_or_404(Lead, pk=pk); form = ManualOutreachForm(request.POST)
    if form.is_valid(): item = form.save(commit=False); item.lead = lead; item.save(); messages.success(request, "Manual outreach recorded.")
    else: messages.error(request, "Manual outreach could not be recorded.")
    return redirect("lead-detail", pk=pk)


@staff_required
def compose_email(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    form = EmailComposerForm(request.POST or None, lead=lead, initial={"template": request.GET.get("template")})
    if request.method == "POST" and form.is_valid(): message = form.save(); messages.success(request, "Email draft saved. Review it before sending."); return redirect("send-email", pk=message.pk)
    return render(request, "leads/form.html", {"form": form, "title": "Compose email"})


@staff_required
def send_email_view(request, pk):
    message = get_object_or_404(OutreachMessage.objects.select_related("lead"), pk=pk, channel=OutreachMessage.Channel.EMAIL)
    if request.method == "POST":
        try: success = send_email_message(message)
        except Exception as exc: messages.error(request, str(exc))
        else: messages.success(request, "Sent." if success else "Email sending failed; the draft and error were saved.")
        return redirect("lead-detail", pk=message.lead_id)
    return render(request, "leads/send_email.html", {"message": message})


@staff_required
def refresh_lighthouse(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    lead = get_object_or_404(Lead, pk=pk)
    try:
        analyze_lead(lead, force=True)
    except Exception as exc:
        messages.error(request, f"PageSpeed analysis failed: {exc}")
    else:
        messages.success(request, "PageSpeed analysis finished.")
    return redirect("lead-detail", pk=pk)


@staff_required
def inspect_website(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    lead = get_object_or_404(Lead, pk=pk)
    try:
        inspect_lead_website(lead)
    except Exception as exc:
        messages.error(request, f"Website inspection failed: {exc}")
    else:
        messages.success(request, "Website inspection finished.")
    return redirect("lead-detail", pk=pk)


@staff_required
def lead_create(request):
    lead = Lead(source="manual", source_id=f"manual:{uuid4()}")
    form = LeadForm(request.POST or None, instance=lead)
    if request.method == "POST" and form.is_valid():
        lead = form.save(); messages.success(request, "Lead created."); return redirect("lead-detail", pk=lead.pk)
    return render(request, "leads/form.html", {"form": form, "title": "Create lead", "subtitle": "Add a manually researched business."})


@staff_required
def campaign_list(request):
    campaigns = Campaign.objects.annotate(lead_count=Count("leads"))
    return render(request, "leads/campaign_list.html", {"campaigns": campaigns})


@staff_required
def campaign_create(request):
    form = CampaignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save(); messages.success(request, "Campaign created."); return redirect("campaign-list")
    return render(request, "leads/form.html", {"form": form, "title": "Create campaign", "subtitle": "Overpass accepts categories such as barber, coffee, dentist, and restaurant."})


@staff_required
def campaign_edit(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    form = CampaignForm(request.POST or None, instance=campaign)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Campaign updated."); return redirect("campaign-list")
    return render(request, "leads/form.html", {"form": form, "title": "Edit campaign"})


@staff_required
def campaign_collect(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    campaign = get_object_or_404(Campaign, pk=pk)
    stdout, stderr = StringIO(), StringIO()
    call_command("collect_leads", campaign_ids=[campaign.pk], stdout=stdout, stderr=stderr)
    summary = next((line for line in reversed(stdout.getvalue().splitlines()) if line.startswith("Collection summary:")), "Collection finished.")
    if stderr.getvalue().strip(): messages.warning(request, stderr.getvalue().strip())
    else: messages.success(request, summary)
    return redirect("campaign-list")


@staff_required
def campaign_toggle(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    campaign = get_object_or_404(Campaign, pk=pk)
    campaign.is_active = not campaign.is_active; campaign.save(update_fields=("is_active", "updated_at"))
    messages.success(request, f"Campaign {'activated' if campaign.is_active else 'paused'}.")
    return redirect("campaign-list")


@staff_required
def email_template_list(request):
    return render(request, "leads/email_template_list.html", {"templates": EmailTemplate.objects.all()})


@staff_required
def email_template_create(request):
    form = EmailTemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Email template created."); return redirect("email-template-list")
    return render(request, "leads/form.html", {"form": form, "title": "Create email template", "subtitle": "Supported placeholders are shown below the form."})


@staff_required
def email_template_edit(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk)
    form = EmailTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Email template updated."); return redirect("email-template-list")
    return render(request, "leads/form.html", {"form": form, "title": "Edit email template"})


@staff_required
def email_template_toggle(request, pk):
    if request.method != "POST": return HttpResponseNotAllowed(("POST",))
    template = get_object_or_404(EmailTemplate, pk=pk)
    template.is_active = not template.is_active; template.save(update_fields=("is_active", "updated_at"))
    messages.success(request, f"Template {'activated' if template.is_active else 'disabled'}.")
    return redirect("email-template-list")


@staff_required
def toggle_theme(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(("POST",))
    current = request.session.get("theme", "dark")
    request.session["theme"] = "light" if current == "dark" else "dark"
    destination = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        destination = reverse("dashboard")
    return redirect(destination)


@staff_required
def integration_settings(request):
    configured = IntegrationSettings.load()
    form = IntegrationSettingsForm(request.POST or None, instance=configured)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Integration settings saved.")
        return redirect("integration-settings")
    return render(
        request,
        "leads/integration_settings.html",
        {"form": form},
    )


@staff_required
def test_google_places(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(("POST",))
    runtime = get_runtime_settings()
    if not runtime.google_places_api_key:
        messages.error(request, "No Google Places API key is configured.")
        return redirect("integration-settings")
    try:
        result = GooglePlacesClient(api_key=runtime.google_places_api_key).text_search(
            "cafe in Athens, Greece",
            page_size=1,
            field_mask=("places.id", "places.displayName"),
        )
    except PlacesError as exc:
        messages.error(request, f"Google Places test failed: {exc}")
    else:
        messages.success(
            request,
            f"Google Places connection succeeded ({len(result.places)} test result).",
        )
    return redirect("integration-settings")
