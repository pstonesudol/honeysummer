from rest_framework import serializers

from .models import Announcement, FlowerListing, GalleryImage, Inquiry

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


class AnnouncementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Announcement
        fields = ("id", "text", "link_url", "link_label")


class GalleryImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GalleryImage
        fields = ("id", "image", "alt_text", "caption", "sort_order")


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = (
            "id",
            "kind",
            "name",
            "email",
            "phone",
            "message",
            "details",
            "photo",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_details(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Details must be an object.")
        return value

    def validate_photo(self, value):
        if value.size > MAX_PHOTO_BYTES:
            raise serializers.ValidationError("Photos must be 10 MB or smaller.")
        content_type = getattr(value, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise serializers.ValidationError("Please upload an image file.")
        return value


class FlowerListingSerializer(serializers.ModelSerializer):
    available = serializers.ReadOnlyField()
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = FlowerListing
        fields = ("id", "name", "variety", "color", "photo_url", "stem_notes", "price", "unit", "quantity_available", "sold_out", "available")

    def get_photo_url(self, obj):
        return obj.photo.url if obj.photo else ""
