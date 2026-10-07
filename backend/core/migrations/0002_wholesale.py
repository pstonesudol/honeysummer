from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="FlowerListing", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=160)), ("variety", models.CharField(blank=True, max_length=160)),
            ("color", models.CharField(blank=True, max_length=100)), ("photo", models.FileField(blank=True, upload_to="flowers/")),
            ("stem_notes", models.CharField(blank=True, max_length=250)), ("price", models.DecimalField(decimal_places=2, max_digits=8)),
            ("unit", models.CharField(choices=[("stem", "Per stem"), ("bunch", "Per bunch")], default="stem", max_length=10)),
            ("quantity_available", models.PositiveIntegerField(default=0)), ("sold_out", models.BooleanField(default=False)),
            ("channel", models.CharField(choices=[("retail", "Retail"), ("wholesale", "Wholesale"), ("both", "Retail and wholesale")], default="wholesale", max_length=10)),
            ("active", models.BooleanField(default=True)), ("sort_order", models.PositiveIntegerField(default=0)),
        ], options={"ordering": ["sort_order", "name", "id"]}),
        migrations.CreateModel(name="FloristProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("business_name", models.CharField(max_length=200)), ("phone", models.CharField(blank=True, max_length=40)),
            ("approved", models.BooleanField(default=False)), ("notes", models.TextField(blank=True)),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="florist_profile", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="Order", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("delivery_fee", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
            ("fulfillment", models.CharField(choices=[("pickup", "Pickup"), ("delivery", "Delivery")], default="pickup", max_length=10)),
            ("pickup_window", models.CharField(blank=True, max_length=200)), ("delivery_address", models.TextField(blank=True)),
            ("stripe_session_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
            ("status", models.CharField(choices=[("pending", "Pending payment"), ("paid", "Paid"), ("expired", "Expired"), ("cancelled", "Cancelled")], default="pending", max_length=12)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="flower_orders", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at"]}),
        migrations.CreateModel(name="OrderItem", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name_snapshot", models.CharField(max_length=160)), ("price_snapshot", models.DecimalField(decimal_places=2, max_digits=8)),
            ("quantity", models.PositiveIntegerField()), ("listing", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.flowerlisting")),
            ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="core.order")),
        ]),
    ]
