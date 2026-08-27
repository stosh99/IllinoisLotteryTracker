import { Link } from "react-router-dom";

import { LegalPage, SUPPORT_EMAIL } from "./LegalPage";

export function ContactPage() {
  return (
    <LegalPage
      eyebrow="CONTACT"
      title="Get in touch."
      lede="One address reaches the person who runs this site."
      updated="August 27, 2026"
    >
      <p className="legal-page__address">
        <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
      </p>

      <h2>What to write about</h2>
      <ul>
        <li>a number that looks wrong, or a game shown incorrectly;</li>
        <li>questions about what is stored about you, or requests about your data;</li>
        <li>trouble signing in or deleting an account;</li>
        <li>anything on the site that is unclear or misleading.</li>
      </ul>
      <p>
        This is a project run by one person, so replies are not immediate. Messages about
        privacy and account deletion are answered first.
      </p>

      <h2>What this address cannot do</h2>
      <p>
        Scratch-Off Data is independent and has no connection to the Illinois Lottery. It cannot
        validate a ticket, confirm a win, process a claim, or pay a prize. For anything involving
        an actual ticket or prize, contact the Illinois Lottery directly.
      </p>
      <p>
        For help with gambling, the confidential helpline 1-800-GAMBLER is available free at any
        time.
      </p>
      <p>
        See also the <Link to="/privacy">privacy notice</Link> and{" "}
        <Link to="/terms">terms of use</Link>.
      </p>
    </LegalPage>
  );
}
