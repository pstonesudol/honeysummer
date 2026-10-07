from django.urls import path

from .views import GalleryListView, InquiryCreateView, announcement, health

urlpatterns = [
    path("health/", health, name="health"),
    path("announcement/", announcement, name="announcement"),
    path("gallery/", GalleryListView.as_view(), name="gallery"),
    path("inquiries/", InquiryCreateView.as_view(), name="inquiry-create"),
]
