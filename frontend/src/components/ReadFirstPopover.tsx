import { useEffect, useRef, useState } from "react";

export function ReadFirstPopover() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="read-first" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className="read-first__trigger"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        Read this first
      </button>
      {open ? (
        <div aria-label="Important information" className="read-first__popover" role="dialog">
          <strong>Before using the estimates</strong>
          <p>Estimates describe the game-wide prize pool—not what the next ticket will do.</p>
          <p>Published unclaimed prizes can include sold winners whose claims are still processing.</p>
          <p>This is an independent analysis and is not affiliated with the Illinois Lottery.</p>
          <a href="/#methodology" onClick={() => setOpen(false)}>How the estimates work →</a>
        </div>
      ) : null}
    </div>
  );
}
