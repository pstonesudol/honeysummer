import json
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Announcement, GalleryImage, Inquiry


class HealthViewTests(TestCase):
    def test_health_endpoint_reports_service_status(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "honey-summer-api"},
        )


class AnnouncementViewTests(TestCase):
    def test_returns_null_when_no_active_announcement(self):
        Announcement.objects.create(text="Hidden", active=False)

        response = self.client.get(reverse("announcement"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["announcement"])

    def test_returns_most_recent_active_announcement(self):
        Announcement.objects.create(text="Older", active=True)
        newest = Announcement.objects.create(
            text="Spring flowers are here",
            link_url="https://example.com/shop",
            link_label="Shop now",
            active=True,
        )

        response = self.client.get(reverse("announcement"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["announcement"]["id"], newest.id)
        self.assertEqual(
            response.json()["announcement"]["text"], "Spring flowers are here"
        )


class GalleryViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_override = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        super().tearDownClass()

    def test_lists_only_active_images_in_sort_order(self):
        GalleryImage.objects.create(
            image=SimpleUploadedFile("b.jpg", b"image-bytes", "image/jpeg"),
            caption="Second",
            sort_order=2,
            active=True,
        )
        GalleryImage.objects.create(
            image=SimpleUploadedFile("a.jpg", b"image-bytes", "image/jpeg"),
            caption="First",
            sort_order=1,
            active=True,
        )
        GalleryImage.objects.create(
            image=SimpleUploadedFile("c.jpg", b"image-bytes", "image/jpeg"),
            caption="Hidden",
            sort_order=0,
            active=False,
        )

        response = self.client.get(reverse("gallery"))

        self.assertEqual(response.status_code, 200)
        captions = [item["caption"] for item in response.json()]
        self.assertEqual(captions, ["First", "Second"])
        self.assertTrue(response.json()[0]["image"].endswith("/media/gallery/a.jpg"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Honey Summer <hello@hellohoneysummer.com>",
    INQUIRY_NOTIFICATION_EMAIL="isabella@hellohoneysummer.com",
)
class InquiryCreateViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_override = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        super().tearDownClass()

    def _payload(self, **overrides):
        payload = {
            "kind": "bouquet",
            "name": "Jamie Rivera",
            "email": "jamie@example.com",
            "phone": "570-555-0100",
            "message": "A cheerful bouquet, please.",
            "details": json.dumps(
                {
                    "fulfillment": "pickup",
                    "occasion": "Birthday",
                    "seasonal_substitutions": True,
                }
            ),
        }
        payload.update(overrides)
        return payload

    def test_creates_inquiry_and_sends_two_emails(self):
        response = self.client.post(reverse("inquiry-create"), self._payload())

        self.assertEqual(response.status_code, 201)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.kind, "bouquet")
        self.assertEqual(inquiry.details["occasion"], "Birthday")
        self.assertTrue(inquiry.details["seasonal_substitutions"])
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("isabella@hellohoneysummer.com", mail.outbox[0].to)
        self.assertEqual(mail.outbox[0].reply_to, ["jamie@example.com"])
        self.assertEqual(mail.outbox[1].to, ["jamie@example.com"])

    def test_accepts_an_inspiration_photo(self):
        photo = SimpleUploadedFile("inspo.jpg", b"image-bytes", "image/jpeg")
        response = self.client.post(
            reverse("inquiry-create"),
            self._payload(kind="wedding", photo=photo),
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Inquiry.objects.get().photo.name.startswith("inquiries/"))

    def test_rejects_missing_email(self):
        response = self.client.post(reverse("inquiry-create"), self._payload(email=""))

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())
        self.assertEqual(Inquiry.objects.count(), 0)
