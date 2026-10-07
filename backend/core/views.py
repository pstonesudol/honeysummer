from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .emails import send_inquiry_emails
from .models import Announcement, GalleryImage
from .serializers import (
    AnnouncementSerializer,
    GalleryImageSerializer,
    InquirySerializer,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok", "service": "honey-summer-api"})


@api_view(["GET"])
@permission_classes([AllowAny])
def announcement(request):
    current = Announcement.objects.filter(active=True).first()
    return Response(
        {"announcement": AnnouncementSerializer(current).data if current else None}
    )


class GalleryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = GalleryImageSerializer

    def get_queryset(self):
        return GalleryImage.objects.filter(active=True)


class InquiryCreateView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = InquirySerializer

    def perform_create(self, serializer):
        inquiry = serializer.save()
        send_inquiry_emails(inquiry)
