from django.contrib import admin
from django.utils.html import format_html

from .models import Announcement, GalleryImage, Inquiry


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
