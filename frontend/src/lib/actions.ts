"use server";

import { redirect } from "next/navigation";

import { getApiBaseUrl } from "@/lib/api";
import { inquiryFields, type InquiryKind, type InquiryState } from "@/lib/inquiry-fields";
import { site } from "@/lib/site";

const KINDS: InquiryKind[] = ["bouquet", "wedding", "contact"];

function apiErrorMessage(data: unknown): string {
  if (data && typeof data === "object") {
    const parts = Object.entries(data as Record<string, unknown>).map(
      ([field, value]) => {
        const text = Array.isArray(value) ? value.join(" ") : String(value);
        return field === "non_field_errors" ? text : `${field}: ${text}`;
      },
    );
    if (parts.length > 0) {
      return parts.join(" ");
    }
  }
  return "Something went wrong sending your message. Please email us directly.";
}

export async function submitInquiry(
  kind: InquiryKind,
  _prevState: InquiryState,
  formData: FormData,
): Promise<InquiryState> {
  if (!KINDS.includes(kind)) {
    return { status: "error", message: "Unknown inquiry type." };
  }

  // Honeypot: real people never fill a hidden "company" field.
  const honeypot = formData.get("company");
  if (typeof honeypot === "string" && honeypot.trim() !== "") {
    redirect(`/thank-you?type=${kind}`);
  }

  const config = inquiryFields[kind];
  const details: Record<string, string | boolean> = {};
  let photo: File | null = null;

  for (const field of config) {
    if (["name", "email", "phone", "message"].includes(field.name)) {
      continue;
    }
    if (field.type === "file") {
      const value = formData.get(field.name);
      if (value instanceof File && value.size > 0) {
        photo = value;
      }
      continue;
    }
    if (field.type === "checkbox") {
      details[field.name] = formData.get(field.name) === "on";
      continue;
    }
    const value = formData.get(field.name);
    if (typeof value === "string" && value.trim() !== "") {
      details[field.name] = value.trim();
    }
  }

  const payload = new FormData();
  payload.set("kind", kind);
  payload.set("name", String(formData.get("name") ?? "").trim());
  payload.set("email", String(formData.get("email") ?? "").trim());
  payload.set("phone", String(formData.get("phone") ?? "").trim());
  payload.set("message", String(formData.get("message") ?? "").trim());
  payload.set("details", JSON.stringify(details));
  if (photo) {
    payload.set("photo", photo);
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}/api/inquiries/`, {
      method: "POST",
      body: payload,
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return {
      status: "error",
      message: `We could not reach the farm just now. Please try again, or email ${site.email}.`,
    };
  }

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    return { status: "error", message: apiErrorMessage(data) };
  }

  redirect(`/thank-you?type=${kind}`);
}
