"""API contract tests for the wholesale/auth/checkout surface.

These lock the observable behaviour of the Django backend so the Sanic
re-platform can be verified against it. They intentionally test the HTTP
contract (status codes, JSON shapes, side effects) rather than internals.
"""

import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import FlowerListing, FloristProfile, Order, OrderItem


EMAIL_SETTINGS = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Honey Summer <hello@hellohoneysummer.com>",
    INQUIRY_NOTIFICATION_EMAIL="isabella@hellohoneysummer.com",
    STRIPE_SECRET_KEY="",
    STRIPE_WEBHOOK_SECRET="",
    CHECKOUT_SUCCESS_URL="http://localhost:3000/wholesale?checkout=success",
    CHECKOUT_CANCEL_URL="http://localhost:3000/wholesale?checkout=cancelled",
)

STRIPE_SETTINGS = {**EMAIL_SETTINGS, "STRIPE_SECRET_KEY": "sk_test_123", "STRIPE_WEBHOOK_SECRET": "whsec_test"}


def make_florist(email="florist@example.com", password="flowers-are-nice", approved=True):
    user = User.objects.create_user(username=email, email=email, password=password)
    FloristProfile.objects.create(user=user, business_name="Fern & Fig", approved=approved)
    return user


@override_settings(**EMAIL_SETTINGS)
class AuthContractTests(TestCase):
    def test_signup_creates_unapproved_profile_and_notifies_the_farm(self):
        response = self.client.post(
            reverse("signup"),
            json.dumps(
                {
                    "business_name": "Fern & Fig",
                    "email": "New@Example.com",
                    "password": "flowers-are-nice",
                    "phone": "570-555-0100",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.username, "new@example.com")
        self.assertFalse(user.florist_profile.approved)
        self.assertEqual(user.florist_profile.business_name, "Fern & Fig")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("isabella@hellohoneysummer.com", mail.outbox[0].to)

    def test_signup_rejects_an_duplicate_email(self):
        make_florist()

        response = self.client.post(
            reverse("signup"),
            json.dumps({"business_name": "X", "email": "florist@example.com", "password": "flowers-are-nice"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_signup_requires_business_email_and_password(self):
        response = self.client.post(
            reverse("signup"),
            json.dumps({"email": "someone@example.com"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_login_me_and_logout_round_trip(self):
        make_florist()

        login = self.client.post(
            reverse("login"),
            json.dumps({"email": "florist@example.com", "password": "flowers-are-nice"}),
            content_type="application/json",
        )

        self.assertEqual(login.status_code, 200)
        self.assertEqual(
            login.json(),
            {"authenticated": True, "approved": True, "business_name": "Fern & Fig"},
        )
        self.assertEqual(self.client.get(reverse("me")).json()["authenticated"], True)

        self.client.post(reverse("logout"))

        self.assertEqual(self.client.get(reverse("me")).json()["authenticated"], False)

    def test_login_rejects_a_bad_password(self):
        make_florist()

        response = self.client.post(
            reverse("login"),
            json.dumps({"email": "florist@example.com", "password": "wrong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)


@override_settings(**EMAIL_SETTINGS)
class FlowerListingContractTests(TestCase):
    def setUp(self):
        self.user = make_florist()

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("flower-list")).status_code, 403)

    def test_lists_active_wholesale_and_both_offerings_for_approved_florists(self):
        FlowerListing.objects.create(
            name="Dahlia", price=Decimal("2.50"), channel=FlowerListing.Channel.BOTH, quantity_available=10
        )
        FlowerListing.objects.create(
            name="Retail only", price=Decimal("1.00"), channel=FlowerListing.Channel.RETAIL, quantity_available=5
        )
        FlowerListing.objects.create(
            name="Hidden", price=Decimal("1.00"), channel=FlowerListing.Channel.WHOLESALE, active=False, quantity_available=5
        )
        self.client.force_login(self.user)

        data = self.client.get(reverse("flower-list")).json()

        self.assertEqual([item["name"] for item in data], ["Dahlia"])
        self.assertEqual(data[0]["price"], "2.50")
        self.assertEqual(data[0]["available"], True)

    def test_unapproved_accounts_see_no_catalog(self):
        pending = make_florist(email="pending@example.com", approved=False)
        FlowerListing.objects.create(
            name="Dahlia", price=Decimal("2.50"), channel=FlowerListing.Channel.WHOLESALE, quantity_available=10
        )
        self.client.force_login(pending)

        self.assertEqual(self.client.get(reverse("flower-list")).json(), [])


@override_settings(**EMAIL_SETTINGS)
class CheckoutContractTests(TestCase):
    def setUp(self):
        self.user = make_florist()
        self.listing = FlowerListing.objects.create(
            name="Dahlia", price=Decimal("2.50"), channel=FlowerListing.Channel.WHOLESALE, quantity_available=10
        )

    def _checkout(self, items, **extra):
        return self.client.post(
            reverse("checkout"),
            json.dumps({"items": items, **extra}),
            content_type="application/json",
        )

    def _approve(self):
        self.client.force_login(self.user)

    def test_requires_approval(self):
        self._approve()
        self.user.florist_profile.approved = False
        self.user.florist_profile.save()

        response = self._checkout([{"id": self.listing.id, "quantity": 1}])

        self.assertEqual(response.status_code, 403)

    def test_requires_authentication(self):
        response = self._checkout([{"id": self.listing.id, "quantity": 1}])

        self.assertEqual(response.status_code, 403)

    def test_empty_cart_is_rejected(self):
        self._approve()

        self.assertEqual(self._checkout([]).status_code, 400)

    def test_successful_order_holds_stock_and_snapshots_price(self):
        self._approve()

        response = self._checkout([{"id": self.listing.id, "quantity": 3}])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["checkout_url"], "")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity_available, 7)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.PAID)
        item = order.items.get()
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.price_snapshot, Decimal("2.50"))
        self.assertEqual(item.name_snapshot, "Dahlia")
        self.assertEqual(len(mail.outbox), 2)

    def test_insufficient_stock_is_rejected_and_nothing_is_held(self):
        self._approve()

        response = self._checkout([{"id": self.listing.id, "quantity": 11}])

        self.assertEqual(response.status_code, 409)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity_available, 10)
        self.assertEqual(Order.objects.count(), 0)

    def test_sold_out_or_unknown_listings_are_rejected(self):
        self.listing.sold_out = True
        self.listing.save()
        self._approve()

        self.assertEqual(self._checkout([{"id": self.listing.id, "quantity": 1}]).status_code, 409)
        self.assertEqual(self._checkout([{"id": 999999, "quantity": 1}]).status_code, 409)


@override_settings(**STRIPE_SETTINGS)
class StripeWebhookContractTests(TestCase):
    def setUp(self):
        self.user = make_florist()
        self.listing = FlowerListing.objects.create(
            name="Dahlia", price=Decimal("2.50"), channel=FlowerListing.Channel.WHOLESALE, quantity_available=3
        )
        self.order = Order.objects.create(customer=self.user, status=Order.Status.PENDING)
        OrderItem.objects.create(
            order=self.order, listing=self.listing, name_snapshot="Dahlia", price_snapshot=Decimal("2.50"), quantity=2
        )

    def _post(self, event):
        with mock.patch("stripe.Webhook.construct_event", return_value=event):
            return self.client.post(
                reverse("stripe-webhook"),
                data=json.dumps(event),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )

    def test_completed_marks_the_order_paid_and_emails_both_parties(self):
        response = self._post(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"metadata": {"order_id": str(self.order.id)}}},
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(len(mail.outbox), 2)

    def test_expired_releases_held_stock(self):
        response = self._post(
            {
                "type": "checkout.session.expired",
                "data": {"object": {"metadata": {"order_id": str(self.order.id)}}},
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.EXPIRED)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity_available, 5)

    def test_invalid_signature_returns_400(self):
        with mock.patch("stripe.Webhook.construct_event", side_effect=ValueError("bad signature")):
            response = self.client.post(
                reverse("stripe-webhook"),
                data="{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )

        self.assertEqual(response.status_code, 400)

    def test_configured_checkout_returns_a_stripe_session_url(self):
        self.client.force_login(self.user)
        session = mock.Mock(id="cs_test_1", url="https://checkout.stripe.com/cs_test_1")

        with mock.patch("stripe.checkout.Session.create", return_value=session) as create:
            response = self.client.post(
                reverse("checkout"),
                json.dumps({"items": [{"id": self.listing.id, "quantity": 1}]}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["checkout_url"], "https://checkout.stripe.com/cs_test_1")
        order = Order.objects.get(pk=response.json()["order_id"])
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.stripe_session_id, "cs_test_1")
        self.assertTrue(create.called)
