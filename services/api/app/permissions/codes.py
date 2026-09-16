"""Permission codes and role→permission maps."""

from __future__ import annotations

from app.domain.enums import OrgRole

ORG_CONFIGURE = "org.configure"
MEMBERS_MANAGE = "members.manage"
DIRECTORY_MANAGE = "directory.manage"
DIRECTORY_READ = "directory.read"
SUPPLIERS_MANAGE = "suppliers.manage"
SUPPLIERS_READ = "suppliers.read"
POLICIES_MANAGE = "policies.manage"
POLICIES_READ = "policies.read"
DOCUMENTS_UPLOAD = "documents.upload"
DOCUMENTS_READ = "documents.read"
DOCUMENTS_DELETE = "documents.delete"
PROCESSES_CREATE = "processes.create"
PROCESSES_READ = "processes.read"
PROCESSES_CANCEL = "processes.cancel"
APPROVALS_DECIDE = "approvals.decide"
APPROVALS_READ = "approvals.read"
EXECUTION_RUN = "execution.run"
INTEGRATIONS_CONFIGURE = "integrations.configure"
AUDIT_READ = "audit.read"
USAGE_READ = "usage.read"
BILLING_MANAGE = "billing.manage"

ROLE_PERMISSIONS: dict[OrgRole, frozenset[str]] = {
    OrgRole.OWNER: frozenset(
        {
            ORG_CONFIGURE,
            MEMBERS_MANAGE,
            DIRECTORY_MANAGE,
            DIRECTORY_READ,
            SUPPLIERS_MANAGE,
            SUPPLIERS_READ,
            POLICIES_MANAGE,
            POLICIES_READ,
            DOCUMENTS_UPLOAD,
            DOCUMENTS_READ,
            DOCUMENTS_DELETE,
            PROCESSES_CREATE,
            PROCESSES_READ,
            PROCESSES_CANCEL,
            APPROVALS_DECIDE,
            APPROVALS_READ,
            EXECUTION_RUN,
            INTEGRATIONS_CONFIGURE,
            AUDIT_READ,
            USAGE_READ,
            BILLING_MANAGE,
        }
    ),
    OrgRole.ADMIN: frozenset(
        {
            ORG_CONFIGURE,
            MEMBERS_MANAGE,
            DIRECTORY_MANAGE,
            DIRECTORY_READ,
            SUPPLIERS_MANAGE,
            SUPPLIERS_READ,
            POLICIES_MANAGE,
            POLICIES_READ,
            DOCUMENTS_UPLOAD,
            DOCUMENTS_READ,
            DOCUMENTS_DELETE,
            PROCESSES_CREATE,
            PROCESSES_READ,
            PROCESSES_CANCEL,
            APPROVALS_DECIDE,
            APPROVALS_READ,
            EXECUTION_RUN,
            INTEGRATIONS_CONFIGURE,
            AUDIT_READ,
            USAGE_READ,
            BILLING_MANAGE,
        }
    ),
    OrgRole.MANAGER: frozenset(
        {
            DIRECTORY_MANAGE,
            DIRECTORY_READ,
            SUPPLIERS_READ,
            POLICIES_READ,
            DOCUMENTS_UPLOAD,
            DOCUMENTS_READ,
            PROCESSES_CREATE,
            PROCESSES_READ,
            PROCESSES_CANCEL,
            APPROVALS_DECIDE,
            APPROVALS_READ,
            EXECUTION_RUN,
        }
    ),
    OrgRole.EMPLOYEE: frozenset(
        {
            DIRECTORY_READ,
            SUPPLIERS_READ,
            POLICIES_READ,
            DOCUMENTS_UPLOAD,
            DOCUMENTS_READ,
            PROCESSES_CREATE,
            PROCESSES_READ,
            APPROVALS_READ,
        }
    ),
    OrgRole.COMPLIANCE: frozenset(
        {
            DIRECTORY_READ,
            SUPPLIERS_READ,
            POLICIES_MANAGE,
            POLICIES_READ,
            DOCUMENTS_UPLOAD,
            DOCUMENTS_READ,
            PROCESSES_READ,
            APPROVALS_DECIDE,
            APPROVALS_READ,
            AUDIT_READ,
        }
    ),
    OrgRole.AUDITOR: frozenset(
        {
            DIRECTORY_READ,
            SUPPLIERS_READ,
            POLICIES_READ,
            DOCUMENTS_READ,
            PROCESSES_READ,
            APPROVALS_READ,
            AUDIT_READ,
            USAGE_READ,
        }
    ),
}


def permissions_for_role(role: OrgRole) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())
