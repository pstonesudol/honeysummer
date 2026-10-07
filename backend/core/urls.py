from django.urls import path

from .views import (FlowerListingListView, GalleryListView, InquiryCreateView,
                    checkout, login, logout, me, signup, stripe_webhook,
                    announcement, health)

urlpatterns = [
    path("health/", health, name="health"),
    path("announcement/", announcement, name="announcement"),
    path("gallery/", GalleryListView.as_view(), name="gallery"),
    path("inquiries/", InquiryCreateView.as_view(), name="inquiry-create"),
    path("flowers/", FlowerListingListView.as_view(), name="flower-list"),
    path("flowers", FlowerListingListView.as_view()),
    path("auth/signup/", signup, name="signup"),
    path("auth/signup", signup),
    path("auth/login/", login, name="login"),
    path("auth/login", login),
    path("auth/logout/", logout, name="logout"),
    path("auth/logout", logout),
    path("auth/me/", me, name="me"),
    path("auth/me", me),
    path("checkout/", checkout, name="checkout"),
    path("checkout", checkout),
    path("stripe/webhook/", stripe_webhook, name="stripe-webhook"),
]
