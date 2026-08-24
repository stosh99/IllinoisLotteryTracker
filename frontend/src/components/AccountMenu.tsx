import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useAuthSession } from "../hooks/useAuthSession";

export function AccountMenu() {
  const { state, logout } = useAuthSession();
  const [error, setError] = useState(false);
  const menuRef = useRef<HTMLDetailsElement>(null);

  // Close the menu when the user clicks anywhere outside it or presses Escape.
  useEffect(() => {
    const closeOnOutsidePress = (event: PointerEvent) => {
      const menu = menuRef.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) {
        menu.open = false;
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && menuRef.current) menuRef.current.open = false;
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  if (state.status !== "authenticated") return null;

  const close = () => {
    if (menuRef.current) menuRef.current.open = false;
  };

  const signOut = async () => {
    setError(false);
    close();
    try {
      await logout();
    } catch {
      setError(true);
    }
  };

  return (
    <div className="account-control">
      <details className="account-menu" ref={menuRef}>
        <summary>Account</summary>
        <div className="account-menu__panel">
          <span className="account-menu__email">{state.session.user.email}</span>
          <Link onClick={close} to="/account#ticket-history">My ticket history</Link>
          <Link onClick={close} to="/account#account-security">Account settings</Link>
          <button onClick={() => void signOut()} type="button">
            Sign out
          </button>
        </div>
      </details>
      {error ? <span className="visually-hidden" role="alert">Sign out failed.</span> : null}
    </div>
  );
}
