import { PRIMARY_STRATEGIES } from "../lib/strategies";
import type { StrategyKey } from "../types/rankings";

interface StrategyPickerProps {
  selected: StrategyKey;
  onSelect: (strategy: StrategyKey) => void;
  variant?: "hero" | "tabs";
}

export function StrategyPicker({
  selected,
  onSelect,
  variant = "hero",
}: StrategyPickerProps) {
  return (
    <div
      className={`strategy-picker strategy-picker--${variant}`}
      role="radiogroup"
      aria-label={variant === "hero" ? "Choose your player type" : "Change player type"}
    >
      {PRIMARY_STRATEGIES.map((strategy, index) => (
        <button
          className="strategy-option"
          data-active={strategy.key === selected}
          key={strategy.key}
          onClick={() => onSelect(strategy.key)}
          onKeyDown={(event) => {
            const targetIndex = keyboardTargetIndex(event.key, index);
            if (targetIndex === null) return;
            event.preventDefault();
            const targetStrategy = PRIMARY_STRATEGIES[targetIndex];
            const radioButtons = event.currentTarget.parentElement?.querySelectorAll<HTMLElement>(
              '[role="radio"]',
            );
            targetStrategy && onSelect(targetStrategy.key);
            radioButtons?.[targetIndex]?.focus();
          }}
          role="radio"
          aria-checked={strategy.key === selected}
          tabIndex={strategy.key === selected ? 0 : -1}
          type="button"
        >
          <span className="strategy-option__number">0{index + 1}</span>
          <span>
            <strong>{strategy.shortLabel}</strong>
            {variant === "hero" ? <small>{strategy.label}</small> : null}
          </span>
        </button>
      ))}
    </div>
  );
}

function keyboardTargetIndex(key: string, currentIndex: number): number | null {
  const finalIndex = PRIMARY_STRATEGIES.length - 1;
  if (key === "Home") return 0;
  if (key === "End") return finalIndex;
  if (key === "ArrowRight" || key === "ArrowDown") {
    return currentIndex === finalIndex ? 0 : currentIndex + 1;
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return currentIndex === 0 ? finalIndex : currentIndex - 1;
  }
  return null;
}
