# Identity provider integration

SecPolicyGen delegates human authentication to any conforming OpenID Connect
provider. It does not own passwords and does not require a provider-specific
SDK, group format, or administration API.

## Provider contract

Configure one issuer per deployment with `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, and `OIDC_SCOPES`. The issuer must
publish OpenID Connect Discovery metadata at
`${OIDC_ISSUER_URL}/.well-known/openid-configuration` and support Authorization
Code flow with PKCE. The first integration profile is a confidential web client
using `client_secret_basic`. Register `OIDC_REDIRECT_URI` exactly at the
provider. Production issuer and callback URLs must use HTTPS; HTTP is accepted
only for localhost development.

The application identifies a human principal by the immutable pair
`(issuer, subject)`. Email and display name are optional presentation data;
they are never authorization keys. Provider groups and roles are ignored.

## Responsibility boundary

The identity provider authenticates the human. SecPolicyGen owns organizations,
memberships, application roles, permissions, tenant isolation, and audit events.
Service-to-service identities are a separate INIT-11 contract.

An authenticated principal has no application access until an explicit local
membership exists. Provision the first administrator from the Context Agent
container or an equivalent controlled administrative job:

```bash
python manage_identity.py \
  --issuer https://identity.example.com/tenant/secpolicygen \
  --subject verified-provider-subject \
  --organization-id example-organization \
  --organization-name "Example Organization" \
  --role admin
```

## Existing data

Tenant ownership is mandatory for contexts, interactions, pipeline jobs, events,
and diagnostics. Audit a legacy single-tenant installation before assignment:

```bash
python scripts/migrate_tenant_scope.py example-organization
```

Review the JSON counts, back up MongoDB, then apply the explicit assignment:

```bash
python scripts/migrate_tenant_scope.py example-organization --apply
```

The migration never infers ownership from email domains or identity-provider
claims. Fixture imports also require `CONTEXT_IMPORT_ORGANIZATION_ID` (or
`--organization-id`) and only replace data owned by that organization.

The command is idempotent. Provider groups and roles are never imported as
SecPolicyGen permissions.

Keycloak, Entra ID, Okta, Auth0, Dex, and other conforming providers can be used
without changing application code. Any local provider added to Docker is a test
fixture only, not a production dependency.

## Local interoperability fixture

The Docker stack includes a disposable Keycloak realm to prove the same OIDC
contract over development HTTP and trusted local HTTPS. It uses fixed fake
credentials and generated, ignored TLS keys; do not promote either to another
environment.

```bash
make local-oidc-http-smoke
make local-oidc-https-smoke
# Or run the complete INIT-26 regression gate:
make init-26-security-gate
```

Both commands start the provider and Context Agent, provision the provider
subject into a local SecPolicyGen organization, and exercise the browser login
through Playwright inside Docker. The application still consumes only Discovery
metadata and standard OIDC claims; no Keycloak SDK or provider role mapping is
used.

The HTTP issuer mode requires `OIDC_ALLOW_INSECURE_HTTP=true` and is rejected
outside development. HTTPS uses the generated local CA only for OIDC requests;
public API clients retain the platform trust store. The browser fixture pins the
generated certificate SPKI instead of disabling TLS validation globally.
The local runner aligns the disposable Keycloak process UID with the owner of
its `0600` leaf key so bind-mounted permissions behave consistently on Linux
and Docker Desktop; no container receives the CA private key.

The complete gate also runs the advisory reverse PoC and asserts that anonymous,
membership-less, and cross-tenant read/write/delete attempts leave persistence
unchanged.
