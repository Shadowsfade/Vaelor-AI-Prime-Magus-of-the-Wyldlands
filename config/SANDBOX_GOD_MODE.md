# Vaelor Access Policy — Full Access / OS-Safe

Vaelor has broad system access for development and installs, with hard failsafes against destroying the operating system.

## Profile
- mode: admin
- profile: full_access_os_safe
- Config: config/autonomy.json (generated per machine at install)

## Allowed (on the user's PC)
- Their user profile folder
- The Vaelor install folder
- Common document/desktop/download folders
- Extra drives if present
- Installs via free tools (winget/pip/etc.)

## NOT allowed
- Full delete/wipe of core OS trees (Windows/System32, Program Files bulk delete, boot/EFI, other users)
- Disk format, diskpart, bcdedit, forced reboot bombs

## Notes for packagers
Installer runs installer/init_local_config.py so each PC gets its own paths and a free local port.
Do not ship another user's autonomy.json, network.json, setup_complete.json, or memory dumps.
