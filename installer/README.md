# Vaelor Installer

## For people who are not computer experts

1. Double-click INSTALL.bat
2. Wait for ALL DONE
3. Double-click the desktop icon Vaelor
4. Click the closed book

If Python is missing, the installer tries to install it automatically.

See also: READ ME FIRST.txt

## For coders

powershell -ExecutionPolicy Bypass -File installer\Install-Vaelor-Alpha.ps1
powershell -ExecutionPolicy Bypass -File installer\Build-AlphaPackage.ps1
python installer\verify_clean_package.py

Zip output: dist\Vaelor-Alpha-1.1.4-alpha.zip


Frozen desktop (1.1.4-alpha): run Build-Vaelor-Exe.ps1 with -Python pointing to
an environment containing requirements.txt and PyInstaller, and -OutDir pointing
to a fresh folder. No virtual environment is shipped. Run verify_desktop.py on
the resulting Vaelor folder to test relocation, bundled runtime and native UI.
Extract the entire desktop ZIP before running Vaelor.exe; _internal is required.
Install-Desktop.ps1 creates a fresh per-user copy and desktop shortcut. It refuses
an existing destination to preserve memory/configuration. WebView2 and a configured
model backend are separate prerequisites. This alpha is not code-signed.
