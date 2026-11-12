#define MyAppName "Traderefy Control Center"
#define MyAppVersion "0.1.0"
[Setup]
AppId={{A4E2DFE4-71A1-45A4-96C4-2C4BB3D21002}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\Traderefy Control Center
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=Traderefy_Control_Center_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TraderefyControlCenter.exe
[Files]
Source: "..\dist\TraderefyControlCenter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{autoprograms}\Traderefy Control Center"; Filename: "{app}\TraderefyControlCenter.exe"
Name: "{autodesktop}\Traderefy Control Center"; Filename: "{app}\TraderefyControlCenter.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce
[Run]
Filename: "{app}\TraderefyControlCenter.exe"; Description: "Launch Traderefy Control Center"; Flags: nowait postinstall skipifsilent
