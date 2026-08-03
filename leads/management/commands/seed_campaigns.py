from django.core.management.base import BaseCommand

from leads.models import Campaign


SAMPLES = (
    ("Athens Hair Salons", "hair_salon", "Athens"),
    ("Athens Clothing Shops", "clothing_shop", "Athens"),
    ("Thessaloniki Restaurants", "restaurant", "Thessaloniki"),
    ("Piraeus Dentists", "dentist", "Piraeus"),
)


class Command(BaseCommand):
    help = "Create optional sample Overpass campaigns without running discovery."

    def handle(self, *args, **options):
        created = 0
        for name, search_term, location in SAMPLES:
            _, was_created = Campaign.objects.get_or_create(name=name, defaults={"search_term": search_term, "location": location})
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Sample campaigns created: {created}"))
