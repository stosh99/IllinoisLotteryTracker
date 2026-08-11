import { useContext } from "react";

import { AuthSessionContext } from "../context/AuthSessionProvider";

export function useAuthSession() {
  const value = useContext(AuthSessionContext);
  if (!value) throw new Error("useAuthSession requires AuthSessionProvider");
  return value;
}
