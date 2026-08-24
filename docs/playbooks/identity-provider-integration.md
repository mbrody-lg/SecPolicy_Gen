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

Keycloak, Entra ID, Okta, Auth0, Dex, and other conforming providers can be used
without changing application code. Any local provider added to Docker is a test
fixture only, not a production dependency.
