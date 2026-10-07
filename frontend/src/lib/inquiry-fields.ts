export type InquiryKind = "bouquet" | "wedding" | "contact" | "wholesale";

export type InquiryFieldType =
  | "text"
  | "email"
  | "tel"
  | "url"
  | "date"
  | "number"
  | "textarea"
  | "select"
  | "checkbox"
  | "file";

export type InquiryField = {
  name: string;
  label: string;
  type: InquiryFieldType;
  required?: boolean;
  placeholder?: string;
  help?: string;
  autoComplete?: string;
  options?: { value: string; label: string }[];
  half?: boolean;
  rows?: number;
};

export type InquiryState = {
  status: "idle" | "success" | "error";
  message?: string;
};

const identity: InquiryField[] = [
  {
    name: "name",
    label: "Your name",
    type: "text",
    required: true,
    autoComplete: "name",
    half: true,
  },
  {
    name: "email",
    label: "Email",
    type: "email",
    required: true,
    autoComplete: "email",
    half: true,
  },
  {
    name: "phone",
    label: "Phone (optional)",
    type: "tel",
    autoComplete: "tel",
    half: true,
  },
];

export const inquiryFields: Record<InquiryKind, InquiryField[]> = {
  bouquet: [
    ...identity,
    {
      name: "fulfillment",
      label: "Pickup or delivery?",
      type: "select",
      required: true,
      half: true,
      options: [
        { value: "pickup", label: "Pickup at the farm" },
        { value: "delivery", label: "Delivery" },
      ],
    },
    {
      name: "desired_date",
      label: "Desired date",
      type: "date",
      half: true,
    },
    {
      name: "occasion",
      label: "Occasion",
      type: "text",
      placeholder: "Birthday, anniversary, just because…",
      half: true,
    },
    {
      name: "budget",
      label: "Budget",
      type: "text",
      placeholder: "$45–$75",
      half: true,
    },
    {
      name: "color_preferences",
      label: "Color preferences",
      type: "text",
      placeholder: "Soft pinks, whites, something cheerful…",
    },
    {
      name: "message",
      label: "Anything else we should know?",
      type: "textarea",
      rows: 4,
    },
  ],
  wedding: [
    ...identity,
    { name: "event_date", label: "Event date", type: "date", half: true },
    {
      name: "event_type",
      label: "Event type",
      type: "select",
      half: true,
      options: [
        { value: "wedding", label: "Wedding" },
        { value: "elopement", label: "Elopement" },
        { value: "rehearsal", label: "Rehearsal dinner" },
        { value: "shower", label: "Shower" },
        { value: "corporate", label: "Corporate or other event" },
      ],
    },
    { name: "venue", label: "Venue or location", type: "text" },
    { name: "guest_count", label: "Guest count", type: "number", half: true },
    {
      name: "party_size",
      label: "Wedding party size",
      type: "text",
      placeholder: "6 bridesmaids, 6 groomsmen",
      half: true,
    },
    {
      name: "floral_budget",
      label: "Floral budget",
      type: "text",
      placeholder: "$2,000–$4,000",
      half: true,
    },
    {
      name: "color_palette",
      label: "Color palette",
      type: "text",
      placeholder: "Dusty rose, cream, sage…",
      half: true,
    },
    {
      name: "style",
      label: "Style or vibe",
      type: "text",
      placeholder: "Garden-inspired, airy, romantic…",
    },
    {
      name: "florals_of_interest",
      label: "Florals you are drawn to",
      type: "textarea",
      rows: 3,
    },
    {
      name: "inspiration_photo",
      label: "Inspiration photo",
      type: "file",
      help: "JPG or PNG, up to 10 MB. Optional but lovely.",
    },
    {
      name: "pinterest_url",
      label: "Pinterest board or link",
      type: "url",
      placeholder: "https://pinterest.com/…",
    },
    {
      name: "seasonal_substitutions",
      label:
        "I understand Honey Summer grows with the seasons and I am open to substitutions within my color palette.",
      type: "checkbox",
      required: true,
    },
    {
      name: "message",
      label: "Additional notes",
      type: "textarea",
      rows: 4,
    },
  ],
  contact: [
    ...identity,
    {
      name: "reason",
      label: "How can we help?",
      type: "select",
      required: true,
      half: true,
      options: [
        { value: "bouquet", label: "Bouquet order" },
        { value: "wedding", label: "Wedding or event" },
        { value: "wholesale", label: "Wholesale" },
        { value: "collaboration", label: "Collaboration" },
        { value: "other", label: "Something else" },
      ],
    },
    {
      name: "message",
      label: "Your message",
      type: "textarea",
      required: true,
      rows: 5,
    },
  ],
  wholesale: [
    ...identity,
    {
      name: "business_name",
      label: "Business name",
      type: "text",
      required: true,
      half: true,
    },
    {
      name: "business_type",
      label: "Business type",
      type: "select",
      half: true,
      options: [
        { value: "florist", label: "Florist" },
        { value: "event", label: "Event designer or planner" },
        { value: "shop", label: "Retail shop or studio" },
        { value: "other", label: "Other" },
      ],
    },
    {
      name: "website",
      label: "Website or Instagram",
      type: "url",
      placeholder: "https://…",
    },
    {
      name: "message",
      label: "Tell us about your work",
      type: "textarea",
      rows: 4,
    },
  ],
};

export const inquiryIntros: Record<InquiryKind, string> = {
  bouquet:
    "Tell us about the flowers you have in mind. Isabella will reply to confirm what is blooming and arrange pickup or delivery.",
  wedding:
    "Share a few details about your day. We will follow up with availability, ideas, and a custom quote.",
  contact: "Send a note and we will get back to you within a few days.",
  wholesale:
    "Tell us about your business. We will set up your wholesale account and share a password with approved florists.",
};
