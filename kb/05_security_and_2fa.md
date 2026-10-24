# Security and Two-Factor Authentication

## Enabling two-factor authentication (2FA)
Go to Settings > Security > Two-factor authentication and scan the QR code with an authenticator app such as Google Authenticator or Authy. Enter the 6-digit code to confirm.
TaskPilot does not support SMS codes.

## Backup codes
When you enable 2FA we generate 10 single-use backup codes. Store them somewhere safe. You can regenerate them in Settings > Security, which invalidates the old set.

## Lost authenticator device
Use a backup code to sign in, then reset 2FA in Settings > Security. If you have no backup codes, workspace Owners can disable 2FA for a member from Members > Manage.

## Single sign-on (SSO)
SAML 2.0 SSO is available on Business and Enterprise plans. Setup instructions are under Settings > Security > SSO. SCIM user provisioning is available on Enterprise only.
