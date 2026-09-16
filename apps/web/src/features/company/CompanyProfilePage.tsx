import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";
import { useAuth } from "../../providers/AuthProvider";
import { permissionsForRole } from "../../lib/permissions";

const profileSchema = z.object({
  legal_name: z.string().min(1, "Legal name is required"),
  trading_name: z.string().optional(),
  industry: z.string().optional(),
  country_code: z.string().max(2).optional(),
  default_timezone: z.string().min(1),
  default_currency: z.string().min(1),
  tax_id: z.string().optional(),
  tax_registration: z.string().optional(),
  tax_country_code: z.string().optional(),
});

type ProfileForm = z.infer<typeof profileSchema>;

export function CompanyProfilePage() {
  const { activeOrganization } = useOrganization();
  const { user } = useAuth();
  const canEdit =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.ORG_CONFIGURE);

  const query = useQuery({
    queryKey: ["org-profile", activeOrganization?.id],
    queryFn: () => apiClient.getOrganizationProfile(activeOrganization!.id),
    enabled: Boolean(activeOrganization?.id),
  });

  const queryClient = useQueryClient();
  const form = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    values: {
      legal_name: query.data?.legal_name ?? activeOrganization?.name ?? "",
      trading_name: query.data?.trading_name ?? "",
      industry: query.data?.industry ?? "",
      country_code: query.data?.country_code ?? "",
      default_timezone: query.data?.default_timezone ?? "UTC",
      default_currency: query.data?.default_currency ?? "USD",
      tax_id: query.data?.tax_id ?? "",
      tax_registration: query.data?.tax_registration ?? "",
      tax_country_code: query.data?.tax_country_code ?? "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: ProfileForm) =>
      apiClient.updateOrganizationProfile(activeOrganization!.id, {
        ...values,
        tax_information: {
          ...(query.data?.tax_information ?? {}),
          tax_id: values.tax_id,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["org-profile"] });
    },
  });

  if (query.isLoading) return <LoadingState label="Loading company profile…" />;
  if (query.isError) {
    return (
      <RetryState
        title="Could not load company profile"
        message="Check your connection and try again."
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <section>
      <h1>Company profile</h1>
      <p className="lede">
        Legal identity, tax details, and locale settings for {activeOrganization?.name}.
      </p>

      <RequirePermission
        permission={PERMISSIONS.ORG_CONFIGURE}
        fallback={
          <EmptyState
            title="Read-only profile"
            description="Your role can view company details but cannot edit configuration."
          />
        }
      >
        <form
          className="mgmt-form"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
        >
          <div className="form-grid">
            <label>
              Legal name
              <input {...form.register("legal_name")} disabled={!canEdit} />
              {form.formState.errors.legal_name ? (
                <span className="field-error">{form.formState.errors.legal_name.message}</span>
              ) : null}
            </label>
            <label>
              Trading name
              <input {...form.register("trading_name")} disabled={!canEdit} />
            </label>
            <label>
              Industry
              <input {...form.register("industry")} disabled={!canEdit} />
            </label>
            <label>
              Country
              <input {...form.register("country_code")} disabled={!canEdit} maxLength={2} />
            </label>
            <label>
              Timezone
              <input {...form.register("default_timezone")} disabled={!canEdit} />
            </label>
            <label>
              Currency
              <input {...form.register("default_currency")} disabled={!canEdit} />
            </label>
            <label>
              Tax ID
              <input {...form.register("tax_id")} disabled={!canEdit} />
            </label>
            <label>
              Tax registration
              <input {...form.register("tax_registration")} disabled={!canEdit} />
            </label>
            <label>
              Tax country
              <input {...form.register("tax_country_code")} disabled={!canEdit} />
            </label>
          </div>
          {canEdit ? (
            <button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save company profile"}
            </button>
          ) : null}
          {mutation.isSuccess ? <p role="status">Profile saved.</p> : null}
          {mutation.isError ? (
            <p className="field-error" role="alert">
              Could not save profile.
            </p>
          ) : null}
        </form>
      </RequirePermission>

      <dl className="status-grid" style={{ marginTop: "1.5rem" }}>
        <div>
          <dt>Plan</dt>
          <dd>{activeOrganization?.plan_code}</dd>
        </div>
        <div>
          <dt>Your role</dt>
          <dd>{activeOrganization?.membership_role}</dd>
        </div>
        <div>
          <dt>Signed in as</dt>
          <dd>{user?.email}</dd>
        </div>
      </dl>
    </section>
  );
}
