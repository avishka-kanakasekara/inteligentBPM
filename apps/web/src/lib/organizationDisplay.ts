/** Display helpers for organization records. They do not change the organization id. */

export function organizationDisplayName(org: { name?: string | null }): string {
  const name = org.name?.trim() ?? "";
  return name || "Workspace";
}

export function organizationPlanLabel(plan: string | null | undefined): string | null {
  const value = plan?.trim() ?? "";
  return value || null;
}

/** Return the requested id only when that organization was returned for this user. */
export function authorizedOrganizationId(
  requestedId: string,
  organizations: readonly { id: string }[],
): string | null {
  return organizations.some((org) => org.id === requestedId) ? requestedId : null;
}
