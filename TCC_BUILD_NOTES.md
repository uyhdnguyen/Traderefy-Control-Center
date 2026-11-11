# Traderefy Control Center — Windows desktop build source

This package is based on the supplied Trading Journal AI source. The original MIT license and third-party notices are retained. It retains the original journal analytics and adds Traderefy branding, the approved slate-blue palette, and persistent desktop left navigation.

## Build the Windows installer

1. Upload this extracted folder to a private GitHub repository (do not upload journal databases, API keys, or `.env` files).
2. In GitHub Actions, run **Build Traderefy Windows Installer**.
3. Download the workflow artifact `Traderefy-Control-Center-Windows-Installer`.
4. Install `Traderefy_Control_Center_Setup.exe` on Windows.

The installer is not prebuilt in this ZIP. It requires Windows CI to compile the desktop executable and package its bundled Python backend and React frontend. The resulting app starts both automatically with one desktop shortcut; no separate browser or terminal is required. The desktop webview requires the Microsoft Edge WebView2 runtime (normally present on current Windows 11 installations).

## Safety and limitations

- This first build is **journal-only**. It does not include a TCS telemetry bridge, TUS/TEE live links, TEM integration, or any order routing. Do not mistake the existing journal for a connected trading execution system.
- Database is stored in `%LOCALAPPDATA%\Traderefy\ControlCenter\trading_journal.db`, outside the installation directory, so reinstalling should not overwrite it. Back up this directory before upgrades.
- Backend listens only on `127.0.0.1:8010`. Other local processes may access that port; do not expose it to a network.
- The launcher and build workflow are source-validated only; Windows compilation, installation, and runtime behavior require verification on a Windows runner and target machine.
- Trading Journal AI MIT copyright/license is preserved.
