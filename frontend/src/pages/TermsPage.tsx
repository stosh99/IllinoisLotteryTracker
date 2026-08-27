import { Link } from "react-router-dom";

import { LegalPage, SUPPORT_EMAIL } from "./LegalPage";

export function TermsPage() {
  return (
    <LegalPage
      eyebrow="TERMS"
      title="Terms of use."
      lede="Scratch-Off Data is an independent information service. Using it means accepting the terms below."
      updated="August 27, 2026"
    >
      <h2>Not affiliated with the Illinois Lottery</h2>
      <p>
        This site is operated independently by a private individual in Illinois. It is not
        affiliated with, endorsed by, sponsored by, or operated by the Illinois Lottery, the
        Illinois Department of the Lottery, or the State of Illinois. It does not sell tickets and
        cannot validate, claim, or pay any prize.
      </p>

      <h2>The numbers are estimates</h2>
      <p>
        Estimated remaining prizes, current odds, prize return, and rankings are calculated from
        public data using stated assumptions. Source information — and our collection, calculation,
        or display of it — may be delayed, incomplete, corrected, or inaccurate. Ticket and prize
        availability can change after the update time shown on each page. Official Illinois Lottery
        rules, records, published corrections, claim decisions, and ticket validation control in
        all cases.
      </p>

      <h2>Nothing here predicts a ticket or recommends a purchase</h2>
      <p>
        The analysis describes game-wide prize pools. It cannot tell you whether any particular
        ticket wins, and it does not guarantee a win, a profit, or a return. Rankings compare games
        against a selected criterion; they are not advice to buy anything. Any decision to play,
        and any money you spend, is entirely your own.
      </p>

      <h2>Play responsibly</h2>
      <p>
        Illinois Lottery tickets may be purchased only by people aged 18 or older. Lottery play
        carries real financial risk and can become harmful. Confidential help is available free at
        any time through the problem-gambling helpline, 1-800-GAMBLER.
      </p>

      <h2>Accounts and the results you record</h2>
      <p>
        Accounts are optional. If you create one, you are responsible for the security of the
        Google account used to sign in. Ticket results you record are your own entries: they are
        not verified against official records and have no bearing on any claim. You may delete
        your account, and everything recorded under it, at any time from the account page.
      </p>
      <p>
        Do not use the site to attempt unauthorized access, to place automated load on it, or to
        misrepresent its output as official lottery information.
      </p>

      <h2>Availability and liability</h2>
      <p>
        The service is provided as is, without warranty of any kind. It may be unavailable,
        interrupted, or discontinued without notice, and data may be withheld when it cannot be
        verified as current. To the fullest extent permitted by law, the operator is not liable
        for any loss arising from use of this site or reliance on its estimates, including money
        spent on lottery tickets.
      </p>

      <h2>Changes and contact</h2>
      <p>
        These terms may change; the date above records the current version, and continuing to use
        the site means accepting the version then posted. Privacy practices are described in the{" "}
        <Link to="/privacy">privacy notice</Link>. Questions can be sent to{" "}
        <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>.
      </p>
    </LegalPage>
  );
}
