import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { rankingDatasetFixture } from "../test/rankingDatasetFixture";
import { SITE_NOTICE_STORAGE_KEY, SITE_NOTICE_VERSION } from "./SiteNoticeDialog";

function stored(version = SITE_NOTICE_VERSION, acknowledgedAt = "2026-08-25T10:11:12.000Z") {
  return JSON.stringify({ version, acknowledgedAt });
}

describe("site notice flow", () => {
  beforeEach(() => window.localStorage.removeItem(SITE_NOTICE_STORAGE_KEY));

  it.each([
    ["missing", null],
    ["malformed", "not-json"],
    ["old version", stored("2026-01-01-v1")],
  ])("requires acknowledgment for %s storage", (_label, value) => {
    if (value !== null) window.localStorage.setItem(SITE_NOTICE_STORAGE_KEY, value);
    render(<App datasetOverride={rankingDatasetFixture} />);

    const dialog = screen.getByRole("dialog", { name: "Before you use the estimates" });
    expect(within(dialog).getByRole("button", { name: "I understand and continue" })).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "Leave site" })).toHaveAttribute(
      "href",
      "https://www.illinoislottery.com/",
    );
    expect(document.getElementById("site-background")).toHaveAttribute("inert");
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });

  it("does not open automatically for a matching valid version", () => {
    window.localStorage.setItem(SITE_NOTICE_STORAGE_KEY, stored());
    render(<App datasetOverride={rankingDatasetFixture} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Important information" })).toBeVisible();
    expect(document.getElementById("site-background")).not.toHaveAttribute("inert");
  });

  it("stores a timestamp, continues, and preserves it through a voluntary reopen", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);
    await user.click(screen.getByRole("button", { name: "I understand and continue" }));

    const firstValue = window.localStorage.getItem(SITE_NOTICE_STORAGE_KEY);
    expect(JSON.parse(firstValue ?? "")).toMatchObject({ version: SITE_NOTICE_VERSION });
    expect(Date.parse(JSON.parse(firstValue ?? "").acknowledgedAt)).not.toBeNaN();

    const trigger = screen.getByRole("button", { name: "Important information" });
    await user.click(trigger);
    expect(screen.getByRole("button", { name: "Close" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(window.localStorage.getItem(SITE_NOTICE_STORAGE_KEY)).toBe(firstValue);
    expect(trigger).toHaveFocus();
  });

  it("keeps required mode open for backdrop clicks and Escape", async () => {
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);
    const backdrop = document.querySelector<HTMLElement>(".site-notice-backdrop")!;

    await user.click(backdrop);
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Before you use the estimates" })).toBeVisible();
  });

  it("contains keyboard focus and restores it after voluntary Escape", async () => {
    window.localStorage.setItem(SITE_NOTICE_STORAGE_KEY, stored());
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);
    const trigger = screen.getByRole("button", { name: "Important information" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog");
    const close = within(dialog).getByRole("button", { name: "Close" });
    close.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("allows the current session to continue when localStorage writes fail", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    const user = userEvent.setup();
    render(<App datasetOverride={rankingDatasetFixture} />);
    await user.click(screen.getByRole("button", { name: "I understand and continue" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(setItem).toHaveBeenCalled();
  });

  it("opens on direct navigation to a non-home route", () => {
    window.history.replaceState({}, "", "/tickets");
    render(<App datasetOverride={rankingDatasetFixture} />);
    expect(screen.getByRole("dialog", { name: "Before you use the estimates" })).toBeVisible();
  });

  it("has one notice mechanism and no cookie banner", () => {
    render(<App datasetOverride={rankingDatasetFixture} />);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.queryByText("Read this first")).not.toBeInTheDocument();
    expect(screen.queryByText(/cookie consent/i)).not.toBeInTheDocument();
  });
});
