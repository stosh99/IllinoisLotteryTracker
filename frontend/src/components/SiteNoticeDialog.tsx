import { useEffect, useRef } from "react";

export const SITE_NOTICE_STORAGE_KEY = "scratchoffdata.siteNotice";
export const SITE_NOTICE_VERSION = "2026-08-25-v1";

export type SiteNoticeMode = "required" | "voluntary";

export function hasCurrentSiteNoticeAcknowledgment(storage: Storage = window.localStorage): boolean {
  try {
    const value: unknown = JSON.parse(storage.getItem(SITE_NOTICE_STORAGE_KEY) ?? "null");
    return (
      typeof value === "object" &&
      value !== null &&
      "version" in value &&
      value.version === SITE_NOTICE_VERSION &&
      "acknowledgedAt" in value &&
      typeof value.acknowledgedAt === "string" &&
      !Number.isNaN(Date.parse(value.acknowledgedAt))
    );
  } catch {
    return false;
  }
}

export function persistSiteNoticeAcknowledgment(
  storage: Storage = window.localStorage,
  now: Date = new Date(),
): void {
  try {
    storage.setItem(
      SITE_NOTICE_STORAGE_KEY,
      JSON.stringify({ version: SITE_NOTICE_VERSION, acknowledgedAt: now.toISOString() }),
    );
  } catch {
    // The current page session may continue; a later reload asks again.
  }
}

interface SiteNoticeDialogProps {
  mode: SiteNoticeMode;
  onAcknowledge: () => void;
  onClose: () => void;
}

export function SiteNoticeDialog({
  mode,
  onAcknowledge,
  onClose,
}: SiteNoticeDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    headingRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (mode === "voluntary") {
          event.preventDefault();
          onClose();
        }
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [])];
      if (focusable.length === 0) {
        event.preventDefault();
        headingRef.current?.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mode, onClose]);

  return (
    <div
      className="site-notice-backdrop"
      data-mode={mode}
      onMouseDown={(event) => {
        if (mode === "voluntary" && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        aria-labelledby="site-notice-title"
        aria-modal="true"
        className="site-notice"
        ref={dialogRef}
        role="dialog"
      >
        <div className="site-notice__rule" />
        <div className="site-notice__scroll">
          <div className="site-notice__content">
            <p className="eyebrow">IMPORTANT INFORMATION</p>
            <h1 id="site-notice-title" ref={headingRef} tabIndex={-1}>
              Before you use the estimates
            </h1>
            <p>
              Scratch-Off Data is an independent information and analysis service. It is not
              affiliated with, endorsed by, sponsored by, or operated by the Illinois Lottery,
              the Illinois Department of the Lottery, or the State of Illinois.
            </p>

            <section>
              <h2>Estimates are not official figures.</h2>
              <p>
                Estimated current odds, estimated ticket supply, prize return, and rankings are
                calculated from public data and stated assumptions. Source information—and our
                collection, calculations, or display of it—may be delayed, incomplete, corrected,
                or inaccurate. Ticket and prize availability may change after the displayed update
                time.
              </p>
            </section>

            <section>
              <h2>The analysis does not predict the next ticket.</h2>
              <p>
                It describes game-wide prize pools and cannot guarantee a win or profit. Rankings
                compare games under the selected criteria; they are not recommendations to
                purchase a ticket.
              </p>
            </section>

            <section>
              <h2>Official records control.</h2>
              <p>
                Scratch-Off Data does not sell or validate lottery tickets. Do not use this site
                to determine whether a ticket is a winner. Official Illinois Lottery rules,
                records, published corrections, claim decisions, and ticket validation control in
                all cases.
              </p>
            </section>

            <p className="site-notice__responsible">
              Illinois Lottery tickets may be purchased only by people 18 or older. Play
              responsibly. Problem-gambling help is available at 1-800-GAMBLER.
            </p>
            <p className="site-notice__version">Notice updated August 25, 2026</p>
          </div>
          <div className="site-notice__actions">
            <button
              className="button site-notice__primary"
              onClick={mode === "required" ? onAcknowledge : onClose}
              type="button"
            >
              {mode === "required" ? "I understand and continue" : "Close"}
            </button>
            {mode === "required" ? (
              <a className="site-notice__leave" href="https://www.illinoislottery.com/">
                Leave site
              </a>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
