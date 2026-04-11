import {
  NETWORK_EXPORT_VERSION,
  type NetworkExportSchema,
  type NetworkExportNode,
  type NetworkExportEdge,
} from "./networkExportSchema";
import type { CliqueSummary } from "@/lib/api/types";

// --------------- Type guards ---------------

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

function isValidNode(v: unknown): v is NetworkExportNode {
  if (!isRecord(v)) return false;
  if (typeof v.id !== "string" || typeof v.title !== "string") return false;
  if (typeof v.status !== "string") return false;
  if (typeof v.liquidity !== "number" || typeof v.volume !== "number") return false;
  if (typeof v.expires_at !== "string") return false;
  if (!isRecord(v.position)) return false;
  if (typeof v.position.x !== "number" || typeof v.position.y !== "number") return false;
  return true;
}

function isValidEdge(v: unknown): v is NetworkExportEdge {
  if (!isRecord(v)) return false;
  if (typeof v.source !== "string" || typeof v.target !== "string") return false;
  if (v.type !== "clique" && v.type !== "conditional") return false;
  return true;
}

function isValidClique(v: unknown): v is CliqueSummary {
  if (!isRecord(v)) return false;
  if (typeof v.id !== "string") return false;
  if (!isStringArray(v.nodes)) return false;
  if (typeof v.size !== "number" || typeof v.states !== "number") return false;
  return true;
}

export type ImportResult =
  | { ok: true; data: NetworkExportSchema }
  | { ok: false; error: string };

/**
 * Validate a parsed JSON value against NetworkExportSchema.
 */
export function validateNetworkExport(raw: unknown): ImportResult {
  if (!isRecord(raw)) {
    return { ok: false, error: "File is not a valid JSON object." };
  }

  if (raw.version !== NETWORK_EXPORT_VERSION) {
    return {
      ok: false,
      error: `Unsupported version: expected ${NETWORK_EXPORT_VERSION}, got ${String(raw.version)}.`,
    };
  }

  if (typeof raw.exportedAt !== "string") {
    return { ok: false, error: "Missing exportedAt timestamp." };
  }

  if (!isRecord(raw.metadata)) {
    return { ok: false, error: "Missing metadata object." };
  }

  if (!Array.isArray(raw.nodes) || !raw.nodes.every(isValidNode)) {
    return { ok: false, error: "Invalid or missing nodes array." };
  }

  if (!Array.isArray(raw.edges) || !raw.edges.every(isValidEdge)) {
    return { ok: false, error: "Invalid or missing edges array." };
  }

  if (!Array.isArray(raw.cliques) || !raw.cliques.every(isValidClique)) {
    return { ok: false, error: "Invalid or missing cliques array." };
  }

  return { ok: true, data: raw as unknown as NetworkExportSchema };
}

/**
 * Read a File object and validate its contents as a NetworkExportSchema.
 * Returns a promise that resolves with the import result.
 */
export function readAndValidateFile(file: File): Promise<ImportResult> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed: unknown = JSON.parse(reader.result as string);
        resolve(validateNetworkExport(parsed));
      } catch {
        resolve({ ok: false, error: "File is not valid JSON." });
      }
    };
    reader.onerror = () => {
      resolve({ ok: false, error: "Failed to read file." });
    };
    reader.readAsText(file);
  });
}
