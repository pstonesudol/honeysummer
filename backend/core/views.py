from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json

from .emails import send_inquiry_emails, send_order_emails, send_signup_notification
from .models import Announcement, FlowerListing, FloristProfile, GalleryImage, Order, OrderItem
from .serializers import (
    AnnouncementSerializer,
    GalleryImageSerializer,
    InquirySerializer,
    FlowerListingSerializer,
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


class FlowerListingListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FlowerListingSerializer

    def get_queryset(self):
        profile = getattr(self.request.user, "florist_profile", None)
        if not profile or not profile.approved:
            return FlowerListing.objects.none()
        return FlowerListing.objects.filter(active=True, channel__in=[FlowerListing.Channel.WHOLESALE, FlowerListing.Channel.BOTH])


def _user_payload(request):
    profile = getattr(request.user, "florist_profile", None)
    return {"authenticated": request.user.is_authenticated, "approved": bool(profile and profile.approved), "business_name": profile.business_name if profile else ""}


@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    return Response(_user_payload(request))


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def signup(request):
    data = request.data
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    business = str(data.get("business_name", "")).strip()
    if not email or not password or not business:
        return Response({"detail": "Business name, email, and password are required."}, status=400)
    if User.objects.filter(username=email).exists():
        return Response({"detail": "An account with this email already exists."}, status=400)
    user = User.objects.create_user(username=email, email=email, password=password, is_active=True)
    profile = FloristProfile.objects.create(user=user, business_name=business, phone=str(data.get("phone", "")))
    send_signup_notification(profile)
    return Response({"detail": "Request received. Isabella will approve your account shortly."}, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def login(request):
    user = authenticate(username=str(request.data.get("email", "")).strip().lower(), password=request.data.get("password", ""))
    if not user:
        return Response({"detail": "Invalid email or password."}, status=400)
    auth_login(request, user)
    return Response(_user_payload(request))


@api_view(["POST"])
@csrf_exempt
def logout(request):
    auth_logout(request)
    return Response({"authenticated": False})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@csrf_exempt
def checkout(request):
    profile = getattr(request.user, "florist_profile", None)
    if not profile or not profile.approved:
        return Response({"detail": "Wholesale approval is required."}, status=403)
    items = request.data.get("items", [])
    if not items:
        return Response({"detail": "Your cart is empty."}, status=400)
    try:
        with transaction.atomic():
            order = Order.objects.create(customer=request.user, fulfillment=request.data.get("fulfillment", "pickup"), delivery_fee=request.data.get("delivery_fee", 0), pickup_window=request.data.get("pickup_window", ""), delivery_address=request.data.get("delivery_address", ""))
            for requested in items:
                listing = FlowerListing.objects.select_for_update().get(pk=requested["id"])
                quantity = int(requested["quantity"])
                if not listing.available or quantity < 1 or listing.quantity_available < quantity:
                    raise ValueError(f"Not enough {listing.name} available.")
                listing.quantity_available -= quantity
                listing.save(update_fields=["quantity_available"])
                OrderItem.objects.create(order=order, listing=listing, name_snapshot=listing.name, price_snapshot=listing.price, quantity=quantity)
        # Stripe integration is activated when STRIPE_SECRET_KEY is configured.
        if not settings.STRIPE_SECRET_KEY:
            order.status = Order.Status.PAID
            order.save(update_fields=["status"])
            send_order_emails(order)
            return Response({"order_id": order.id, "checkout_url": ""}, status=201)
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(mode="payment", success_url=settings.CHECKOUT_SUCCESS_URL, cancel_url=settings.CHECKOUT_CANCEL_URL, line_items=[{"price_data": {"currency": "usd", "product_data": {"name": item.name_snapshot}, "unit_amount": int(item.price_snapshot * 100)}, "quantity": item.quantity} for item in order.items.all()], metadata={"order_id": str(order.id)})
        order.stripe_session_id = session.id
        order.save(update_fields=["stripe_session_id"])
        return Response({"order_id": order.id, "checkout_url": session.url}, status=201)
    except (FlowerListing.DoesNotExist, ValueError) as error:
        return Response({"detail": str(error)}, status=409)


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_exempt
def stripe_webhook(request):
    if not settings.STRIPE_SECRET_KEY:
        return Response({"received": True})
    import stripe
    try:
        event = stripe.Webhook.construct_event(request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""), settings.STRIPE_WEBHOOK_SECRET)
        order = Order.objects.get(pk=event["data"]["object"].get("metadata", {}).get("order_id"))
        if event["type"] == "checkout.session.completed":
            order.status = Order.Status.PAID
            send_order_emails(order)
        elif event["type"] == "checkout.session.expired":
            _release_order(order)
            order.status = Order.Status.EXPIRED
        order.save(update_fields=["status"])
        return Response({"received": True})
    except Exception:
        return Response({"detail": "Invalid webhook."}, status=400)


def _release_order(order):
    for item in order.items.select_related("listing"):
        FlowerListing.objects.filter(pk=item.listing_id).update(quantity_available=F("quantity_available") + item.quantity)
