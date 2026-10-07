from django.db import models
from django.contrib.auth.models import User


class Announcement(models.Model):
    """A short, season-aware message shown in the site announcement banner."""

    text = models.CharField(max_length=200)
    link_url = models.URLField(blank=True)
    link_label = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(
        default=True,
        help_text="Only the most recent active announcement is shown on the site.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.text


class GalleryImage(models.Model):
    """A photograph in the Weddings & Events portfolio."""

    image = models.FileField(upload_to="gallery/")
    alt_text = models.CharField(
        max_length=250,
        blank=True,
        help_text="Describe the photo for screen readers and search engines.",
    )
    caption = models.CharField(max_length=250, blank=True)
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first.",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.caption or self.alt_text or f"Gallery image {self.pk}"


class Inquiry(models.Model):
    """A message from the public: a bouquet request, wedding inquiry, or note.

    Common identity fields are columns for easy searching in the admin, while
    form-specific answers are stored in ``details`` so new fields can be added
    without a migration.
    """

    class Kind(models.TextChoices):
        BOUQUET = "bouquet", "Bouquet order"
        WEDDING = "wedding", "Wedding & event"
        CONTACT = "contact", "General contact"
        WHOLESALE = "wholesale", "Wholesale access request"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    message = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    photo = models.FileField(upload_to="inquiries/%Y/%m/", blank=True)
    handled = models.BooleanField(
        default=False,
        help_text="Tick once you have replied to this inquiry.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "inquiries"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.name}"


class FlowerListing(models.Model):
    class Unit(models.TextChoices):
        STEM = "stem", "Per stem"
        BUNCH = "bunch", "Per bunch"

    class Channel(models.TextChoices):
        RETAIL = "retail", "Retail"
        WHOLESALE = "wholesale", "Wholesale"
        BOTH = "both", "Retail and wholesale"

    name = models.CharField(max_length=160)
    variety = models.CharField(max_length=160, blank=True)
    color = models.CharField(max_length=100, blank=True)
    photo = models.FileField(upload_to="flowers/", blank=True)
    stem_notes = models.CharField(max_length=250, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.STEM)
    quantity_available = models.PositiveIntegerField(default=0)
    sold_out = models.BooleanField(default=False)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.WHOLESALE)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name", "id"]

    def __str__(self):
        return self.name

    @property
    def available(self):
        return self.active and not self.sold_out and self.quantity_available > 0


class FloristProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="florist_profile")
    business_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=40, blank=True)
    approved = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.business_name


class Order(models.Model):
    class Fulfillment(models.TextChoices):
        PICKUP = "pickup", "Pickup"
        DELIVERY = "delivery", "Delivery"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="flower_orders")
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fulfillment = models.CharField(max_length=10, choices=Fulfillment.choices, default=Fulfillment.PICKUP)
    pickup_window = models.CharField(max_length=200, blank=True)
    delivery_address = models.TextField(blank=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, unique=True, null=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    listing = models.ForeignKey(FlowerListing, on_delete=models.PROTECT)
    name_snapshot = models.CharField(max_length=160)
    price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField()

    @property
    def total(self):
        return self.price_snapshot * self.quantity
