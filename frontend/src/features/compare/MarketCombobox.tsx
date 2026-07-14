import { useEffect, useId, useMemo, useState } from "react";

interface MarketOption {
  id: string;
  title: string;
}

export function MarketCombobox({ label, value, markets, onChange, placeholder, showLabel = true }: {
  label: string;
  value: string;
  markets: MarketOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  showLabel?: boolean;
}) {
  const inputId = useId();
  const listboxId = useId();
  const selected = markets.find((market) => market.id === value);
  const [inputValue, setInputValue] = useState(selected?.title ?? "");
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const query = inputValue.toLocaleLowerCase();
  const results = useMemo(
    () => markets.filter((market) =>
      market.title.toLocaleLowerCase().includes(query)
      || market.id.toLocaleLowerCase().includes(query),
    ).slice(0, 12),
    [markets, query],
  );

  useEffect(() => {
    setInputValue(selected?.title ?? "");
    setOpen(false);
  }, [selected?.title]);

  function select(market: MarketOption) {
    onChange(market.id);
    setInputValue(market.title);
    setOpen(false);
  }

  function close() {
    setInputValue(selected?.title ?? "");
    setOpen(false);
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-xs)", position: "relative" }}>
      {showLabel && <label htmlFor={inputId} style={labelStyle}>{label}</label>}
      <input
        id={inputId}
        role="combobox"
        aria-label={showLabel ? undefined : label}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-activedescendant={open && results[highlightedIndex] ? `${listboxId}-option-${highlightedIndex}` : undefined}
        autoComplete="off"
        placeholder={placeholder}
        value={inputValue}
        onFocus={(event) => {
          event.currentTarget.select();
          setHighlightedIndex(0);
          setOpen(true);
        }}
        onChange={(event) => {
          setInputValue(event.target.value);
          setHighlightedIndex(0);
          setOpen(true);
        }}
        onBlur={close}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            close();
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            if (results.length > 0) {
              const direction = event.key === "ArrowDown" ? 1 : -1;
              setHighlightedIndex((index) => (index + direction + results.length) % results.length);
            }
          } else if (event.key === "Enter" && open && results[highlightedIndex]) {
            event.preventDefault();
            select(results[highlightedIndex]);
          }
        }}
        style={inputStyle}
      />
      {open && results.length > 0 && (
        <ul id={listboxId} role="listbox" aria-label={`${label} results`} style={listboxStyle}>
          {results.map((market, index) => (
            <li
              id={`${listboxId}-option-${index}`}
              key={market.id}
              role="option"
              aria-selected={market.id === value}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setHighlightedIndex(index)}
              onClick={() => select(market)}
              style={{
                ...optionStyle,
                background: index === highlightedIndex ? "var(--color-bg-hover)" : "transparent",
              }}
            >
              {market.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = { fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--color-text-muted)" };
const inputStyle: React.CSSProperties = { width: "100%", padding: "10px 12px", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text)" };
const listboxStyle: React.CSSProperties = { position: "absolute", zIndex: 10, top: "100%", left: 0, right: 0, maxHeight: 360, overflowY: "auto", marginTop: "var(--space-xs)", padding: "var(--space-xs)", listStyle: "none", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", background: "var(--color-bg-surface)" };
const optionStyle: React.CSSProperties = { padding: "8px 10px", borderRadius: "var(--radius-sm)", cursor: "pointer", color: "var(--color-text)" };
