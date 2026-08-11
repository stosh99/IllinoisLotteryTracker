export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 42 42" role="img">
        <path d="M7 8.5h28v8.25a5.2 5.2 0 0 0 0 10.5v6.25H7v-6.25a5.2 5.2 0 0 0 0-10.5V8.5Z" />
        <path className="brand-mark__line" d="M15 9v24" />
        <path className="brand-mark__star" d="m25 15.5 1.65 3.35 3.7.54-2.68 2.61.63 3.69-3.3-1.74-3.3 1.74.63-3.69-2.68-2.61 3.7-.54L25 15.5Z" />
      </svg>
    </span>
  );
}
