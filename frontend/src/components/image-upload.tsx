"use client";

import { useEffect, useRef, useState } from "react";

export function ImageUpload({ id, name, describedBy }: { id: string; name: string; describedBy?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const objectUrl = useRef<string | null>(null);
  const [selection, setSelection] = useState<{ url: string; name: string; size: string } | null>(null);
  const [error, setError] = useState("");

  function releasePreview() {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }

  function clearSelection() {
    releasePreview();
    if (input.current) input.current.value = "";
    setSelection(null);
    setError("");
  }

  useEffect(() => {
    const form = input.current?.form;
    const reset = () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
      setSelection(null);
      setError("");
    };
    form?.addEventListener("reset", reset);
    return () => {
      form?.removeEventListener("reset", reset);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);

  return (
    <div className="image-upload">
      <input
        ref={input}
        id={id}
        name={name}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        aria-describedby={[describedBy, `${id}-status`].filter(Boolean).join(" ")}
        onChange={(event) => {
          releasePreview();
          setSelection(null);
          setError("");
          const file = event.currentTarget.files?.[0];
          if (!file) return;
          if (!file.type.startsWith("image/")) {
            setError("This file cannot be previewed. Please choose an image.");
            return;
          }
          const url = URL.createObjectURL(file);
          objectUrl.current = url;
          setSelection({ url, name: file.name, size: `${(file.size / 1024 / 1024).toFixed(2)} MB` });
        }}
      />
      {selection && !error ? (
        <figure className="image-upload__preview">
          {/* Local file previews use a browser blob URL, not the image optimizer. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={selection.url} alt="Selected inspiration photo preview" onError={() => {
            releasePreview();
            setError("This image cannot be previewed in your browser. Choose another image if needed.");
          }} />
          <figcaption>Full image preview · no cropping</figcaption>
        </figure>
      ) : null}
      <div className="image-upload__details">
        <p id={`${id}-status`} className="form-field__help" role="status">
          {error || (selection ? `${selection.name} · ${selection.size} · Ready to send` : "Choose an image to preview it before sending.")}
        </p>
        {selection || error ? <button type="button" className="button button--quiet button--sm" onClick={() => {
          clearSelection();
          input.current?.focus();
        }}>Remove photo</button> : null}
      </div>
    </div>
  );
}
