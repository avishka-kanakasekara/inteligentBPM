import { useState } from "react";
import type { ImportPreview } from "@bpm/frontend-types";
import { ApiError } from "../../lib/apiClient";

type Props = {
  title: string;
  sampleCsv: string;
  onPreview: (csv: string) => Promise<ImportPreview>;
  onCommit: (csv: string) => Promise<{ created_count: number }>;
  onCommitted?: () => void;
};

export function CsvImportPanel({
  title,
  sampleCsv,
  onPreview,
  onCommit,
  onCommitted,
}: Props) {
  const [csv, setCsv] = useState(sampleCsv);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  async function runPreview() {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await onPreview(csv);
      setPreview(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function runCommit() {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await onCommit(csv);
      setSuccess(`Imported ${result.created_count} row(s).`);
      setPreview(null);
      onCommitted?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="import-panel" aria-labelledby="import-heading">
      <h2 id="import-heading">{title}</h2>
      <p className="muted">Preview validates rows, reports duplicates, then commits.</p>
      <label htmlFor="csv-input">CSV content</label>
      <textarea
        id="csv-input"
        rows={6}
        value={csv}
        onChange={(e) => setCsv(e.target.value)}
        aria-describedby="csv-help"
      />
      <p id="csv-help" className="muted">
        Include a header row. Invalid rows are reported before commit.
      </p>
      <div className="button-row">
        <button type="button" onClick={() => void runPreview()} disabled={busy}>
          Preview import
        </button>
        <button
          type="button"
          onClick={() => void runCommit()}
          disabled={
            busy ||
            !preview ||
            preview.error_count > 0 ||
            preview.duplicate_count > 0 ||
            preview.valid_count === 0
          }
        >
          Commit import
        </button>
      </div>
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      {success ? <p className="tone-success" role="status">{success}</p> : null}
      {preview ? (
        <div className="import-report" aria-live="polite">
          <p>
            {preview.valid_count} valid / {preview.error_count} errors /{" "}
            {preview.duplicate_count} duplicates (of {preview.total_rows})
          </p>
          {(preview.errors.length > 0 || preview.duplicates.length > 0) && (
            <ul className="simple-list">
              {[...preview.errors, ...preview.duplicates].map((item) => (
                <li key={`${item.row_number}-${item.code}-${item.field}`}>
                  Row {item.row_number}: [{item.code}] {item.message}
                  {item.field ? ` (${item.field})` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
