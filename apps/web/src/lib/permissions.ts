/** Client-side permission and entitlement maps (UI only — server re-enforces). */

import type { OrgRole } from "@bpm/frontend-types";

export const PERMISSIONS = {
  ORG_CONFIGURE: "org.configure",
  DIRECTORY_MANAGE: "directory.manage",
  DIRECTORY_READ: "directory.read",
  SUPPLIERS_MANAGE: "suppliers.manage",
  SUPPLIERS_READ: "suppliers.read",
  POLICIES_MANAGE: "policies.manage",
  POLICIES_READ: "policies.read",
  DOCUMENTS_UPLOAD: "documents.upload",
  DOCUMENTS_READ: "documents.read",
  PROCESSES_CREATE: "processes.create",
  PROCESSES_READ: "processes.read",
  APPROVALS_DECIDE: "approvals.decide",
  APPROVALS_READ: "approvals.read",
  EXECUTION_RUN: "execution.run",
  INTEGRATIONS_CONFIGURE: "integrations.configure",
  AUDIT_READ: "audit.read",
  BILLING_MANAGE: "billing.manage",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

const ROLE_PERMISSIONS: Record<OrgRole, ReadonlySet<Permission>> = {
  owner: new Set(Object.values(PERMISSIONS)),
  admin: new Set(Object.values(PERMISSIONS)),
  manager: new Set([
    PERMISSIONS.DIRECTORY_MANAGE,
    PERMISSIONS.DIRECTORY_READ,
    PERMISSIONS.SUPPLIERS_READ,
    PERMISSIONS.POLICIES_READ,
    PERMISSIONS.DOCUMENTS_UPLOAD,
    PERMISSIONS.DOCUMENTS_READ,
    PERMISSIONS.PROCESSES_CREATE,
    PERMISSIONS.PROCESSES_READ,
    PERMISSIONS.APPROVALS_DECIDE,
    PERMISSIONS.APPROVALS_READ,
    PERMISSIONS.EXECUTION_RUN,
  ]),
  employee: new Set([
    PERMISSIONS.DIRECTORY_READ,
    PERMISSIONS.SUPPLIERS_READ,
    PERMISSIONS.POLICIES_READ,
    PERMISSIONS.DOCUMENTS_UPLOAD,
    PERMISSIONS.DOCUMENTS_READ,
    PERMISSIONS.PROCESSES_CREATE,
    PERMISSIONS.PROCESSES_READ,
    PERMISSIONS.APPROVALS_READ,
  ]),
  compliance: new Set([
    PERMISSIONS.DIRECTORY_READ,
    PERMISSIONS.POLICIES_MANAGE,
    PERMISSIONS.POLICIES_READ,
    PERMISSIONS.DOCUMENTS_READ,
    PERMISSIONS.PROCESSES_READ,
    PERMISSIONS.APPROVALS_DECIDE,
    PERMISSIONS.APPROVALS_READ,
    PERMISSIONS.AUDIT_READ,
  ]),
  auditor: new Set([
    PERMISSIONS.DIRECTORY_READ,
    PERMISSIONS.POLICIES_READ,
    PERMISSIONS.DOCUMENTS_READ,
    PERMISSIONS.PROCESSES_READ,
    PERMISSIONS.APPROVALS_READ,
    PERMISSIONS.AUDIT_READ,
  ]),
};

export function permissionsForRole(role: OrgRole): ReadonlySet<Permission> {
  return ROLE_PERMISSIONS[role];
}

export type PlanCode = "pro" | "enterprise" | "pro_max";

export const PLAN_FEATURES: Record<PlanCode, ReadonlySet<string>> = {
  pro: new Set([
    "process.discovery",
    "process.execution",
    "documents.upload",
    "integrations.email_enabled",
    "integrations.supplier_quotes_enabled",
    "integrations.basic",
  ]),
  enterprise: new Set([
    "process.discovery",
    "process.execution",
    "documents.upload",
    "approvals.multi_role",
    "audit.export",
    "audit.export_enabled",
    "integrations.basic",
    "integrations.email_enabled",
    "integrations.supplier_quotes_enabled",
    "integrations.advanced",
    "integrations.advanced_enabled",
    "security.sso_enabled",
    "security.scim_enabled",
    "security.advanced_rbac_enabled",
    "analytics.advanced_enabled",
    "support.priority",
  ]),
  pro_max: new Set([
    "process.discovery",
    "process.execution",
    "documents.upload",
    "approvals.multi_role",
    "audit.export",
    "audit.export_enabled",
    "integrations.basic",
    "integrations.email_enabled",
    "integrations.supplier_quotes_enabled",
    "integrations.advanced",
    "integrations.advanced_enabled",
    "integrations.dedicated_enabled",
    "security.sso_enabled",
    "security.scim_enabled",
    "security.advanced_rbac_enabled",
    "analytics.advanced_enabled",
    "workers.dedicated_capacity",
    "models.advanced_routing",
    "policies.custom_packs",
    "networking.private_enabled",
    "support.priority",
    "support.premium",
  ]),
};

export function planHasFeature(plan: PlanCode, feature: string): boolean {
  return PLAN_FEATURES[plan]?.has(feature) ?? false;
}
