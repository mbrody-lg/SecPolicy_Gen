"""Administrative bootstrap commands for provider-neutral identity records."""

import argparse

from app import create_app
from app.access_control import provision_membership, provision_organization, sync_principal


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage SecPolicyGen identity memberships")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--role", action="append", choices=("admin", "operator", "viewer"), required=True)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        principal = sync_principal(issuer=args.issuer, subject=args.subject)
        organization = provision_organization(
            organization_id=args.organization_id,
            name=args.organization_name,
        )
        provision_membership(
            principal_id=principal["_id"],
            organization_id=organization["organization_id"],
            roles=args.role,
            is_default=True,
        )
    print(f"Provisioned {args.subject} in {args.organization_id}")


if __name__ == "__main__":
    main()
