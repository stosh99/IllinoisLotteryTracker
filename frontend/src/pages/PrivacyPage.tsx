import { LegalPage, SUPPORT_EMAIL } from "./LegalPage";

export function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="PRIVACY"
      title="What this site collects."
      lede="Scratch-Off Data is built to need very little about you. This notice describes exactly what is stored, for how long, and how to remove it."
      updated="August 27, 2026"
    >
      <h2>Browsing without an account</h2>
      <p>
        Reading rankings, game pages, and the ticket directory requires no account and collects
        no personal information about you. The site loads no analytics, advertising, tracking
        scripts, or third-party fonts — every asset is served from this domain.
      </p>
      <p>
        The only thing stored in your browser while signed out is a single record noting that you
        acknowledged the site notice, so it is not shown on every visit. Clearing your browser
        storage removes it.
      </p>

      <h2>If you sign in</h2>
      <p>
        Sign-in uses Google and requests only the <code>openid email</code> scope. When you sign
        in, this site receives and stores:
      </p>
      <ul>
        <li>your email address and whether Google reports it as verified;</li>
        <li>the stable account identifier Google issues for you, used to recognize you on return;</li>
        <li>the times your account was created and last authenticated.</li>
      </ul>
      <p>
        A session record is created so you stay signed in. Sessions are stored on the server and
        referenced by a cookie that is host-only, HTTP-only, and unreadable by page scripts.
      </p>

      <h2>What is deliberately not recorded</h2>
      <p>
        Sessions and security events carry <strong>no IP addresses, no device or browser names,
        and no locations</strong>. That is a property of the database itself: no such column
        exists. Abuse protection uses short-lived pseudonymous values held only in memory, which
        are never written to storage.
      </p>

      <h2>Security events</h2>
      <p>
        Sign-in, sign-out, session revocation, and deletion attempts are recorded with the time,
        the type of event, and whether it succeeded, so that account misuse can be investigated.
        These records are <strong>automatically deleted after 90 days</strong>.
      </p>

      <h2>Tickets you record</h2>
      <p>
        Ticket results you enter — the game, the date, and the amount won — are private to your
        account. They are never shown to other people, published, sold, or shared, and they are
        not used to build any profile of you.
      </p>

      <h2>Backups</h2>
      <p>
        The database is backed up on a 7-daily, 4-weekly, 12-monthly lifecycle so the service can
        be restored after a failure. Because backups are point-in-time copies, data you delete may
        persist in them until the copies containing it age out on that schedule.
      </p>

      <h2>Deleting your account</h2>
      <p>
        You can delete your account from the account page at any time. Deletion removes your
        stored identity, your sessions, and every ticket result you recorded, and requires a
        recent sign-in to confirm it is really you. Deletion is immediate and cannot be undone;
        remaining copies in backups age out as described above.
      </p>

      <h2>Sharing</h2>
      <p>
        Your information is not sold, rented, or shared for advertising. The only third party
        involved is Google, and only because you chose to sign in with it — that exchange is
        governed by Google&apos;s own privacy policy. Information may be disclosed if required by
        law.
      </p>

      <h2>Changes and questions</h2>
      <p>
        Material changes to this notice will be reflected in the date above. Questions, or
        requests about your data, can be sent to <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>.
      </p>
    </LegalPage>
  );
}
