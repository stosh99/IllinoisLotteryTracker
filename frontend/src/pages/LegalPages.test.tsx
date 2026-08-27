import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ContactPage } from "./ContactPage";
import { SUPPORT_EMAIL } from "./LegalPage";
import { PrivacyPage } from "./PrivacyPage";
import { TermsPage } from "./TermsPage";

function renderPage(page: React.ReactNode) {
  return render(<MemoryRouter>{page}</MemoryRouter>);
}

describe("privacy notice", () => {
  it("states every disclosure the release gate requires", () => {
    renderPage(<PrivacyPage />);

    const body = screen.getByRole("main").textContent ?? "";
    // Verified email and the Google identifier.
    expect(body).toMatch(/email address and whether Google reports it as verified/i);
    expect(body).toMatch(/stable account identifier Google issues/i);
    // Sessions, in-memory pseudonyms, and the 90-day event retention.
    expect(body).toMatch(/session record is created/i);
    expect(body).toMatch(/pseudonymous values held only in memory/i);
    expect(body).toMatch(/automatically deleted after 90 days/i);
    // The backup lifecycle.
    expect(body).toMatch(/7-daily, 4-weekly, 12-monthly/i);
    // Deletion route and the contact address.
    expect(body).toMatch(/delete your account/i);
    expect(screen.getByRole("link", { name: SUPPORT_EMAIL })).toHaveAttribute(
      "href",
      `mailto:${SUPPORT_EMAIL}`,
    );
  });

  it("claims no tracking and no IP or device recording", () => {
    renderPage(<PrivacyPage />);

    const body = screen.getByRole("main").textContent ?? "";
    expect(body).toMatch(/no analytics, advertising, tracking/i);
    expect(body).toMatch(/no IP addresses, no device or browser names/i);
  });
});

describe("terms of use", () => {
  it("disclaims affiliation, prediction, and sets the play age", () => {
    renderPage(<TermsPage />);

    const body = screen.getByRole("main").textContent ?? "";
    expect(body).toMatch(/not affiliated with, endorsed by, sponsored by/i);
    expect(body).toMatch(/cannot tell you whether any particular\s+ticket wins/i);
    expect(body).toMatch(/18 or older/i);
    expect(body).toMatch(/1-800-GAMBLER/i);
    expect(screen.getByRole("link", { name: /privacy notice/i })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });
});

describe("contact page", () => {
  it("publishes the address and the limits of what it can do", () => {
    renderPage(<ContactPage />);

    expect(screen.getAllByRole("link", { name: SUPPORT_EMAIL })[0]).toHaveAttribute(
      "href",
      `mailto:${SUPPORT_EMAIL}`,
    );
    const body = screen.getByRole("main").textContent ?? "";
    expect(body).toMatch(/cannot\s+validate a ticket, confirm a win, process a claim/i);
  });
});
