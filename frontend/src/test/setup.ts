import "@testing-library/jest-dom/vitest";

import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

import { SITE_NOTICE_STORAGE_KEY, SITE_NOTICE_VERSION } from "../components/SiteNoticeDialog";

beforeEach(() => {
  window.localStorage.setItem(
    SITE_NOTICE_STORAGE_KEY,
    JSON.stringify({ version: SITE_NOTICE_VERSION, acknowledgedAt: "2026-08-25T12:00:00.000Z" }),
  );
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});
