from rest_framework import serializers

from .models import Announcement, GalleryImage, Inquiry

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
