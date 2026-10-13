; Installateur Windows de CAT Pilot (Inno Setup 6).
; Installation par utilisateur, sans droits d'administrateur : la mise à jour
; automatique peut ainsi remplacer CATPilot.exe.
#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
AppId={{6C3D2A9E-5F1B-4C7A-9E2D-CA7B11F4A705}
AppName=CAT Pilot
AppVersion={#MyVersion}
AppPublisher=F4JCF
AppPublisherURL=https://github.com/F4JCF/catpilot
DefaultDirName={localappdata}\Programs\CATPilot
DefaultGroupName=CAT Pilot
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=CATPilot-Setup-{#MyVersion}
SetupIconFile=assets\catpilot.ico
UninstallDisplayIcon={app}\CATPilot.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\CATPilot.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CAT Pilot"; Filename: "{app}\CATPilot.exe"
Name: "{group}\{cm:UninstallProgram,CAT Pilot}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\CAT Pilot"; Filename: "{app}\CATPilot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CATPilot.exe"; Description: "{cm:LaunchProgram,CAT Pilot}"; Flags: nowait postinstall skipifsilent
