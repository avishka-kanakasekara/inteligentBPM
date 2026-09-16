import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DocumentSearchHit } from "@bpm/frontend-types";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS, permissionsForRole } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

const policySchema = z.object({
  code: z.string().min(1),
  title: z.string().min(1),
  category: z.string().optional(),
  description: z.string().optional(),
});

type PolicyForm = z.infer<typeof policySchema>;

export function PoliciesDocumentsPage() {
  const { activeOrganization } = useOrganization();
  const canManagePolicies =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.POLICIES_MANAGE);
  const canUpload =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.DOCUMENTS_UPLOAD);
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("laptop");
  const [searchHits, setSearchHits] = useState<DocumentSearchHit[]>([]);
  const [agentContext, setAgentContext] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const policiesQuery = useQuery({
    queryKey: ["policies", activeOrganization?.id],
    queryFn: () => apiClient.listPolicies(),
    enabled: Boolean(activeOrganization?.id),
  });

  const documentsQuery = useQuery({
    queryKey: ["documents", activeOrganization?.id],
    queryFn: () => apiClient.listDocuments(),
    enabled: Boolean(activeOrganization?.id),
  });

  const form = useForm<PolicyForm>({
    resolver: zodResolver(policySchema),
    defaultValues: { code: "", title: "", category: "", description: "" },
  });

  const createMutation = useMutation({
    mutationFn: (values: PolicyForm) =>
      apiClient.createPolicy({
        ...values,
        metadata: { source: "management-ui" },
      }),
    onSuccess: () => {
      form.reset();
      void queryClient.invalidateQueries({ queryKey: ["policies"] });
    },
  });

  const searchMutation = useMutation({
    mutationFn: () =>
      apiClient.searchDocuments({
        query: searchQuery,
        mode: "hybrid",
        include_agent_context: true,
        similarity_threshold: 0.05,
      }),
    onSuccess: (data) => {
      setSearchHits(data.hits);
      setAgentContext(data.agent_context ?? null);
    },
  });

  async function onFileSelected(file: File | null) {
    if (!file) return;
    setUploadError(null);
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    bytes.forEach((b) => {
      binary += String.fromCharCode(b);
    });
    const content_base64 = btoa(binary);
    try {
      await apiClient.ingestDocument({
        title: file.name,
        file_name: file.name,
        content_base64,
        mime_type: file.type || undefined,
      });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  return (
    <RequirePermission
      permission={PERMISSIONS.POLICIES_READ}
      fallback={
        <EmptyState
          title="Access restricted"
          description="Policies and documents require read permission."
        />
      }
    >
      <section>
        <h1>Policies and documents</h1>
        <p className="lede">
          Policy metadata and document ingestion with organization-scoped search. Retrieved
          document text is treated as untrusted data.
        </p>

        {policiesQuery.isLoading ? <LoadingState label="Loading policies…" /> : null}
        {policiesQuery.isError ? (
          <RetryState
            title="Could not load policies"
            message="Retry to reload policy metadata."
            onRetry={() => void policiesQuery.refetch()}
          />
        ) : null}

        {policiesQuery.data?.items.length === 0 ? (
          <EmptyState title="No policies" description="Create policy metadata to begin." />
        ) : null}

        {policiesQuery.data && policiesQuery.data.items.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Code</th>
                <th scope="col">Title</th>
                <th scope="col">Category</th>
                <th scope="col">Status</th>
                <th scope="col">Metadata</th>
              </tr>
            </thead>
            <tbody>
              {policiesQuery.data.items.map((p) => (
                <tr key={p.id}>
                  <td>{p.code}</td>
                  <td>{p.title}</td>
                  <td>{p.category ?? "—"}</td>
                  <td>{p.status}</td>
                  <td>
                    <code>{JSON.stringify(p.metadata ?? {})}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}

        {canManagePolicies ? (
          <form
            className="mgmt-form"
            onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}
            noValidate
          >
            <h2>Add policy metadata</h2>
            <div className="form-grid">
              <label>
                Code
                <input {...form.register("code")} />
              </label>
              <label>
                Title
                <input {...form.register("title")} />
              </label>
              <label>
                Category
                <input {...form.register("category")} />
              </label>
              <label>
                Description
                <input {...form.register("description")} />
              </label>
            </div>
            <button type="submit">Create policy</button>
          </form>
        ) : null}

        <article className="import-panel" style={{ marginTop: "1.5rem" }}>
          <h2>Documents</h2>
          <p className="muted">
            Supported: PDF, DOCX, XLSX, CSV, TXT, Markdown, email exports. Private org storage;
            malware scan, extraction, chunking, embeddings, and hybrid search.
          </p>

          {canUpload ? (
            <label>
              Upload document
              <input
                type="file"
                accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.markdown,.eml,.msg"
                onChange={(e) => void onFileSelected(e.target.files?.[0] ?? null)}
              />
            </label>
          ) : null}
          {uploadError ? (
            <p className="field-error" role="alert">
              {uploadError}
            </p>
          ) : null}

          {documentsQuery.isLoading ? <LoadingState label="Loading documents…" /> : null}
          {documentsQuery.data?.items.length === 0 ? (
            <EmptyState title="No documents" description="Upload a file to begin ingestion." />
          ) : null}
          {documentsQuery.data && documentsQuery.data.items.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Title</th>
                  <th scope="col">File</th>
                  <th scope="col">Status</th>
                  <th scope="col">Chunks</th>
                  <th scope="col">Flags</th>
                </tr>
              </thead>
              <tbody>
                {documentsQuery.data.items.map((d) => (
                  <tr key={d.id}>
                    <td>{d.title}</td>
                    <td>{d.file_name ?? d.storage_path}</td>
                    <td>
                      <span
                        className={`status-pill ${
                          d.status === "indexed"
                            ? "tone-success"
                            : d.status === "failed" || d.status === "quarantined"
                              ? "tone-danger"
                              : "tone-warning"
                        }`}
                      >
                        {d.status}
                      </span>
                    </td>
                    <td>{d.chunk_count ?? 0}</td>
                    <td>{(d.suspicious_flags ?? []).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}

          <div className="toolbar">
            <label>
              Search documents
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Document search query"
              />
            </label>
            <button
              type="button"
              onClick={() => searchMutation.mutate()}
              disabled={searchMutation.isPending || !searchQuery.trim()}
            >
              Hybrid search
            </button>
          </div>

          {searchHits.length > 0 ? (
            <ul className="simple-list" aria-label="Search results">
              {searchHits.map((hit) => (
                <li key={`${hit.document_id}-${hit.chunk_id}`}>
                  <strong>{hit.title}</strong> (score {hit.score.toFixed(2)})
                  {hit.citation.page_number != null
                    ? ` — page ${hit.citation.page_number}`
                    : ""}
                  {hit.citation.section_heading
                    ? ` — ${hit.citation.section_heading}`
                    : ""}
                  <div className="muted">{hit.citation.excerpt}</div>
                  {hit.suspicious ? (
                    <span className="status-pill tone-danger">suspicious content flagged</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          {agentContext ? (
            <details>
              <summary>Agent context (delimited untrusted data)</summary>
              <pre className="agent-context">{agentContext}</pre>
            </details>
          ) : null}
        </article>
      </section>
    </RequirePermission>
  );
}
