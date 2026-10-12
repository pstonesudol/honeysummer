"use server";

import { redirect } from "next/navigation";
import { getCloudflareContext } from "@opennextjs/cloudflare";

import { getApiBaseUrl } from "@/lib/api";
import { backendAuthHeaders } from "@/lib/backend-auth";
import { inquiryFields, type InquiryKind, type InquiryState } from "@/lib/inquiry-fields";
import { site } from "@/lib/site";

const KINDS: InquiryKind[] = ["bouquet", "wedding", "contact"];
const NETWORK_ERROR_CODES = new Set([
  "ECONNREFUSED",
  "ECONNRESET",
  "EAI_AGAIN",
  "ENOTFOUND",
  "ETIMEDOUT",
  "ERR_TLS_CERT_ALTNAME_INVALID",
  "UND_ERR_CONNECT_TIMEOUT",
]);
type WorkerSelfReference = { fetch(request: Request): Promise<Response> };

function getWorkerSelfReference(): WorkerSelfReference | undefined {
  try {
    const binding = getCloudflareContext().env.WORKER_SELF_REFERENCE as WorkerSelfReference | undefined;
    return binding && typeof binding.fetch === "function" ? binding : undefined;
  } catch {
    // Local Next.js development has no deployed Worker service binding.
    return undefined;
  }
}

function inquiryFailureDetails(error: unknown) {
  const cause = error instanceof Error ? error.cause : undefined;
  const candidateCode = cause && typeof cause === "object" && "code" in cause
    ? cause.code
    : undefined;
  const causeCode = typeof candidateCode === "string" && NETWORK_ERROR_CODES.has(candidateCode)
    ? candidateCode
    : undefined;

  return {
    errorType: error instanceof TypeError ? "TypeError" : error instanceof Error ? "Error" : "NonError",
    ...(causeCode ? { causeCode } : {}),
  };
}

function logStagingInquiryFailure(
  reference: string,
  stage: "request_setup" | "fetch" | "upstream_response",
  details: Record<string, string | number | boolean | undefined>,
) {
  if (process.env.DEPLOYMENT_ENVIRONMENT !== "staging") return;
  // Never log submitted fields, request bodies, credentials, raw exception
  // messages, or upstream response bodies.
  console.error("staging_inquiry_failure", { reference, stage, ...details });
}

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

  const reference = crypto.randomUUID();
  const staging = process.env.DEPLOYMENT_ENVIRONMENT === "staging";
  let apiUrl: string;
  let authHeaders: Record<string, string>;
  let selfReference: WorkerSelfReference | undefined;
  try {
    apiUrl = `${getApiBaseUrl()}/api/inquiries/`;
    authHeaders = backendAuthHeaders();
    selfReference = getWorkerSelfReference();
  } catch (error) {
    logStagingInquiryFailure(reference, "request_setup", {
      ...inquiryFailureDetails(error),
      apiUrlConfigured: Boolean(process.env.API_URL),
    });
    return {
      status: "error",
      message: `We could not reach the farm just now. Please try again, or email ${site.email}.${staging ? ` Reference: ${reference}` : ""}`,
    };
  }

  let response: Response;
  try {
    const requestOptions: RequestInit = {
      method: "POST",
      body: payload,
      headers: { Accept: "application/json", ...authHeaders },
      redirect: selfReference ? "manual" : "error",
      cache: "no-store",
    };
    response = selfReference
      ? await selfReference.fetch(new Request("https://worker-self-reference.invalid/api/inquiries/", requestOptions))
      : await fetch(apiUrl, requestOptions);
  } catch (error) {
    logStagingInquiryFailure(reference, "fetch", {
      ...inquiryFailureDetails(error),
      apiUrlConfigured: Boolean(process.env.API_URL),
      originCredentialIncluded: Boolean(authHeaders["X-HoneySummer-Origin-Secret"]),
      transport: selfReference ? "worker_service_binding" : "direct_fetch",
    });
    return {
      status: "error",
      message: `We could not reach the farm just now. Please try again, or email ${site.email}.${staging ? ` Reference: ${reference}` : ""}`,
    };
  }

  if (!response.ok) {
    logStagingInquiryFailure(reference, "upstream_response", { status: response.status });
    const data = await response.json().catch(() => null);
    return {
      status: "error",
      message: `${apiErrorMessage(data)}${staging ? ` Reference: ${reference}` : ""}`,
    };
  }

  redirect(`/thank-you?type=${kind}`);
}
