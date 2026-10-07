from django.contrib import admin
from django.utils.html import format_html

from .models import Announcement, FlowerListing, FloristProfile, GalleryImage, Inquiry, Order, OrderItem


@admin.register(FlowerListing)
class FlowerListingAdmin(admin.ModelAdmin):
    list_display = ("name", "variety", "channel", "price", "unit", "quantity_available", "sold_out", "active")
    list_filter = ("channel", "unit", "active", "sold_out")
    list_editable = ("quantity_available", "sold_out", "active")
    search_fields = ("name", "variety", "color")


@admin.register(FloristProfile)
class FloristProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "user", "approved", "phone")
    list_filter = ("approved",)
    list_editable = ("approved",)
    search_fields = ("business_name", "user__email")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("listing", "name_snapshot", "price_snapshot", "quantity")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "fulfillment", "created_at")
    list_filter = ("status", "fulfillment")
    search_fields = ("customer__username", "customer__email", "stripe_session_id")
    readonly_fields = ("customer", "delivery_fee", "fulfillment", "pickup_window", "delivery_address", "stripe_session_id", "created_at", "updated_at")
    inlines = (OrderItemInline,)

    actions = ("cancel_orders",)

    @admin.action(description="Cancel orders and release held stock")
    def cancel_orders(self, request, queryset):
        from django.db import transaction
        from django.db.models import F
        for order in queryset.filter(status__in=[Order.Status.PENDING, Order.Status.PAID]):
            with transaction.atomic():
                for item in order.items.all():
                    type(item.listing).objects.filter(pk=item.listing_id).update(quantity_available=F("quantity_available") + item.quantity)
                order.status = Order.Status.CANCELLED
                order.save(update_fields=("status", "updated_at"))


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("text", "active", "link_label", "updated_at")
    list_editable = ("active",)
    ordering = ("-created_at",)


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "caption", "sort_order", "active")
    list_editable = ("sort_order", "active")
    search_fields = ("caption", "alt_text")
    readonly_fields = ("preview",)

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if not obj.image:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="height:44px;border-radius:6px;" />',
            obj.image.url,
        )

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.image:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="max-width:420px;border-radius:12px;" />',
            obj.image.url,
        )


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ("kind", "name", "email", "handled", "created_at")
    list_filter = ("kind", "handled", "created_at")
    list_editable = ("handled",)
    search_fields = ("name", "email", "phone", "message")
    readonly_fields = ("kind", "name", "email", "phone", "message", "details", "photo", "created_at")
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("kind", "handled", "created_at")}),
        ("Contact", {"fields": ("name", "email", "phone")}),
        ("Message", {"fields": ("message", "details", "photo")}),
    )
