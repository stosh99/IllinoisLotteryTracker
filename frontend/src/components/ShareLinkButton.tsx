import { useState } from "react";

import { absolutePublicUrl } from "../lib/urlState";

interface ShareLinkButtonProps {
  href: string;
  label: string;
  successMessage: string;
}

export function ShareLinkButton({
  href,
  label,
  successMessage,
}: ShareLinkButtonProps) {
  const [status, setStatus] = useState<string | null>(null);

  const copyLink = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(absolutePublicUrl(href, window.location.origin));
      setStatus(successMessage);
    } catch {
      setStatus("Copy unavailable. Use your browser address bar to copy this page.");
    }
  };

  return (
    <div className="share-link-control">
      <button className="button button--outline" onClick={copyLink} type="button">
        <CopyIcon />
        {label}
      </button>
      <span aria-live="polite" className="share-link-control__status">
        {status}
      </span>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <rect height="10" rx="1" width="10" x="7" y="7" />
      <path d="M13 7V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h3" />
    </svg>
  );
}
