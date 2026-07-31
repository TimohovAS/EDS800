; Windows installer for the ENC inverter parameter editor.
;
; It packs whatever packaging/build.ps1 left in packaging/dist, so compile it
; through that script - on its own it will fail on a missing source folder.
;
;   ISCC.exe /DAppVersion=3.0.2 packaging\installer.iss

#define AppName "ENC Inverter Parameter Editor"
#define AppExeName "ENC Inverter Editor.exe"
#define AppPublisher "ENC"

#ifndef AppVersion
  #error AppVersion is not defined - build through packaging\build.ps1
#endif

#define SourceDir "dist\ENC Inverter Editor"

[Setup]
; Never reuse this GUID for another product: it is what lets an upgrade
; replace the previous install instead of stacking a second copy.
AppId={{6C92B4C7-DE01-4572-9533-26377D978B21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\ENC Inverter Editor
DefaultGroupName=ENC Inverter Editor
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=output
OutputBaseFilename=ENC-Inverter-Editor-{#AppVersion}-Setup
SetupIconFile=enc_editor.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The editor is 64-bit because the Python it is frozen from is.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Machine-wide by default, but a technician without admin rights can still
; install it under their own profile from the first wizard page.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
ShowLanguageDialog=auto

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Profiles added by hand after installation live here and are not tracked by
; the installer, so remove the folder outright.
Type: filesandordirs; Name: "{app}\_internal\profiles"
