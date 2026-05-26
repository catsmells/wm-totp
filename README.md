# wm-totp
TOTP Authenticator, as a WindowMaker Dockapp.

## Usage
Left Click: Cycle accounts.
Right Click: Reload accounts from disk.
Middle Click: Copy current code to clipboard (requires xclip).

Accounts are stored at ~/.config/wm-totp/accounts.json
Add accounts with: `python manage.py add <name> <base32-secret>`
