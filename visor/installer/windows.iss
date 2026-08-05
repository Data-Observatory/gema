; Inno Setup script for Visor. Compiled by CI (.github/workflows/visor-build.yml)
; via a maintained Inno Setup GitHub Action, or manually with `iscc` on Windows
; after `make build-visor` has produced dist/Visor/ (the PyInstaller onedir
; output) at the repo root. Never run on its own without that step first.

#define MyAppName "Visor"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Data Observatory"
#define MyAppExeName "Visor.exe"

[Setup]
AppId={{4F3B8C2A-9E1D-4A6F-9B7C-9A2F6C1E7D3B}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist_installer
OutputBaseFilename=Visor-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\Visor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
