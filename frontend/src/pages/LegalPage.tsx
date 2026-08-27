import { useEffect, type ReactNode } from "react";

export const SUPPORT_EMAIL = "privacy@scratchoffdata.com";

export function LegalPage({
  eyebrow,
  title,
  lede,
  updated,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  updated: string;
  children: ReactNode;
}) {
  useEffect(() => {
    document.title = `${title.replace(/\.$/, "")} · Scratch-Off Data`;
    return () => {
      document.title = "Scratch-Off Data";
    };
  }, [title]);

  return (
    <main className="legal-page" id="main-content">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="legal-page__lede">{lede}</p>
      <p className="legal-page__updated">Last updated {updated}</p>
      <div className="legal-page__body">{children}</div>
    </main>
  );
}
