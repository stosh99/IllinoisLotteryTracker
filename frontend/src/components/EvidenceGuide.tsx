export type EvidenceKind = "official" | "calculated" | "estimated" | "adjusted";

const evidenceDefinitions: ReadonlyArray<{
  kind: EvidenceKind;
  label: string;
  description: string;
}> = [
  {
    kind: "official",
    label: "Official report",
    description: "Copied from the Illinois Lottery source.",
  },
  {
    kind: "calculated",
    label: "Calculated",
    description: "Exact arithmetic using reported values.",
  },
  {
    kind: "estimated",
    label: "Estimate",
    description: "Depends on ticket supply the lottery does not publish directly.",
  },
  {
    kind: "adjusted",
    label: "Lag-adjusted estimate",
    description: "Uses the current 24-day claim-delay assumption when eligible.",
  },
] as const;

export function EvidenceTag({ kind }: { kind: EvidenceKind }) {
  const definition = evidenceDefinitions.find((item) => item.kind === kind)!;
  return (
    <span className={`evidence-tag evidence-tag--${kind}`}>
      {definition.label}
    </span>
  );
}

export function EvidenceGuide({ id }: { id?: string }) {
  return (
    <div className="evidence-guide" id={id}>
      <div className="evidence-guide__heading">
        <strong>What the data labels mean</strong>
        <span>Text and color identify where each number comes from.</span>
      </div>
      <ul>
        {evidenceDefinitions.map((item) => (
          <li key={item.kind}>
            <EvidenceTag kind={item.kind} />
            <span>{item.description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
