import type { TicketPriceFilter } from "../types/rankings";

interface RankingFiltersProps {
  ariaLabel?: string;
  prices: number[];
  ticketPrice: TicketPriceFilter;
  onTicketPriceChange: (price: TicketPriceFilter) => void;
}

export function RankingFilters({
  ariaLabel = "Ranking filters",
  prices,
  ticketPrice,
  onTicketPriceChange,
}: RankingFiltersProps) {
  return (
    <div className="ranking-filters" aria-label={ariaLabel}>
      <div className="price-filter">
        <span className="filter-label">Ticket price</span>
        <div className="price-filter__options">
          <FilterButton
            active={ticketPrice === "all"}
            label="All"
            onClick={() => onTicketPriceChange("all")}
          />
          {prices.map((price) => (
            <FilterButton
              active={ticketPrice === price}
              key={price}
              label={`$${price}`}
              onClick={() => onTicketPriceChange(price)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface FilterButtonProps {
  active: boolean;
  label: string;
  onClick: () => void;
}

function FilterButton({ active, label, onClick }: FilterButtonProps) {
  return (
    <button
      className="filter-chip"
      data-active={active}
      type="button"
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
