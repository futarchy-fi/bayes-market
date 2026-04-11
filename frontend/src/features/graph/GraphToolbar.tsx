import { useRef, useCallback, useState } from "react";
import { readAndValidateFile } from "./networkImport";
import type { NetworkExportSchema } from "./networkExportSchema";

export type GraphView = "force" | "circular";

interface GraphToolbarProps {
  view: GraphView;
  onViewChange: (view: GraphView) => void;
  onExport: () => void;
  onImportSuccess: (data: NetworkExportSchema) => void;
}

export function GraphToolbar({
  view,
  onViewChange,
  onExport,
  onImportSuccess,
}: GraphToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const handleImportFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportError(null);
    const result = await readAndValidateFile(file);
    if (result.ok) {
      onImportSuccess(result.data);
    } else {
      setImportError(result.error);
    }
    e.target.value = "";
  }, [onImportSuccess]);

  return (
    <div style={toolbarStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
        {/* View toggle */}
        <div style={toggleGroupStyle}>
          <button
            type="button"
            onClick={() => onViewChange("force")}
            style={view === "force" ? toggleActiveStyle : toggleStyle}
          >
            Force
          </button>
          <button
            type="button"
            onClick={() => onViewChange("circular")}
            style={view === "circular" ? toggleActiveStyle : toggleStyle}
          >
            Circular
          </button>
        </div>

        <button type="button" onClick={onExport} style={btnStyle} title="Export network as JSON">
          Export
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          style={btnStyle}
          title="Import network from JSON"
        >
          Import
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          style={{ display: "none" }}
          onChange={handleImportFile}
        />
      </div>

      {importError && (
        <div style={{ fontSize: "0.75rem", color: "var(--color-danger)", marginTop: 4 }}>
          Import failed: {importError}
        </div>
      )}
    </div>
  );
}

const toolbarStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const toggleGroupStyle: React.CSSProperties = {
  display: "flex",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  overflow: "hidden",
};

const toggleStyle: React.CSSProperties = {
  padding: "2px 10px",
  fontSize: "0.7rem",
  border: "none",
  background: "var(--color-bg)",
  color: "var(--color-text-muted)",
  cursor: "pointer",
  fontWeight: 500,
};

const toggleActiveStyle: React.CSSProperties = {
  ...toggleStyle,
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
};

const btnStyle: React.CSSProperties = {
  padding: "2px 8px",
  fontSize: "0.7rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  cursor: "pointer",
  fontWeight: 500,
};
