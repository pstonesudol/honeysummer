"use client";

import { useActionState } from "react";
import { AlertCircle, Loader2, Lock } from "lucide-react";

import { submitInquiry } from "@/lib/actions";
import {
  inquiryFields,
  type InquiryField,
  type InquiryKind,
  type InquiryState,
} from "@/lib/inquiry-fields";

const initialState: InquiryState = { status: "idle" };

function FieldControl({ field, kind }: { field: InquiryField; kind: InquiryKind }) {
  const id = `${kind}-${field.name}`;
  const helpId = field.help ? `${id}-help` : undefined;
  const describedBy = helpId;

  switch (field.type) {
    case "textarea":
      return (
        <textarea
          id={id}
          name={field.name}
          rows={field.rows ?? 4}
          required={field.required}
          placeholder={field.placeholder}
          aria-describedby={describedBy}
        />
      );
    case "select":
      return (
        <select
          id={id}
          name={field.name}
          required={field.required}
          defaultValue=""
          aria-describedby={describedBy}
        >
          <option value="" disabled>
            Please choose…
          </option>
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );
    case "checkbox":
      return (
        <label className="checkbox" htmlFor={id}>
          <input id={id} name={field.name} type="checkbox" required={field.required} />
          <span>{field.label}</span>
        </label>
      );
    case "file":
      return (
        <input
          id={id}
          name={field.name}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          aria-describedby={describedBy}
        />
      );
    case "number":
      return (
        <input
          id={id}
          name={field.name}
          type="number"
          min={0}
          required={field.required}
          placeholder={field.placeholder}
          aria-describedby={describedBy}
        />
      );
    default:
      return (
        <input
          id={id}
          name={field.name}
          type={field.type}
          required={field.required}
          placeholder={field.placeholder}
          autoComplete={field.autoComplete}
          aria-describedby={describedBy}
        />
      );
  }
}

function Field({ field, kind }: { field: InquiryField; kind: InquiryKind }) {
  const id = `${kind}-${field.name}`;
  const helpId = field.help ? `${id}-help` : undefined;
  const isCheckbox = field.type === "checkbox";

  return (
    <div
      className={`form-field${field.half ? " form-field--half" : ""}${
        isCheckbox ? " form-field--checkbox" : ""
      }`}
    >
      {!isCheckbox ? (
        <label htmlFor={id}>
          {field.label}
          {field.required ? <span aria-hidden="true"> *</span> : null}
        </label>
      ) : null}
      <FieldControl field={field} kind={kind} />
      {field.help ? (
        <p className="form-field__help" id={helpId}>
          {field.help}
        </p>
      ) : null}
    </div>
  );
}

export function InquiryForm({
  kind,
  submitLabel = "Send inquiry",
}: {
  kind: InquiryKind;
  submitLabel?: string;
}) {
  const [state, action, pending] = useActionState(
    submitInquiry.bind(null, kind),
    initialState,
  );

  return (
    <form className="inquiry-form" action={action}>
      <div className="form-honeypot" aria-hidden="true">
        <label htmlFor={`${kind}-company`}>Company</label>
        <input
          id={`${kind}-company`}
          name="company"
          type="text"
          tabIndex={-1}
          autoComplete="off"
        />
      </div>

      <div className="form-grid">
        {inquiryFields[kind].map((field) => (
          <Field field={field} kind={kind} key={field.name} />
        ))}
      </div>

      {state.status === "error" ? (
        <p className="form-status form-status--error" role="alert">
          <AlertCircle aria-hidden="true" size={18} strokeWidth={1.8} />
          <span>{state.message}</span>
        </p>
      ) : null}

      <div className="inquiry-form__actions">
        <button className="button button--primary" type="submit" disabled={pending}>
          {pending ? (
            <>
              <Loader2 className="spin" aria-hidden="true" size={16} strokeWidth={1.8} />
              Sending…
            </>
          ) : (
            submitLabel
          )}
        </button>
        <p className="inquiry-form__privacy">
          <Lock aria-hidden="true" size={14} strokeWidth={1.8} />
          We only use your details to reply to you.
        </p>
      </div>
    </form>
  );
}
