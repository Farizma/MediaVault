; Media Vault setup: the standard Windows install wizard (Inno Setup 6).
; Build:  python build_installer.py   (makes dist\MediaVault with PyInstaller, then runs:  iscc /DAppVersion=x.y.z installer.iss)
;
; Where it installs: anywhere you choose. Setup starts without administrator rights (the default folder is your own
; %LOCALAPPDATA%\Programs\Media Vault, no prompt). If you pick "Install for all users", or a folder you cannot write
; to (C:\Program Files, another drive's root, ...), it asks Windows for administrator permission (UAC) and carries on
; elevated with the folder you chose. Upgrades reuse the folder of the installed version.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
; never change AppId: it is how setup recognises an installed Media Vault (upgrades, uninstall)
AppId={{6F1C2D4E-8A3B-4C7D-9E21-5B0F7A9C3D18}
AppName=Media Vault
AppVersion={#AppVersion}
AppVerName=Media Vault {#AppVersion}
AppPublisher=Farizma
AppPublisherURL=https://github.com/Farizma/MediaVault
AppSupportURL=https://github.com/Farizma/MediaVault/issues
AppUpdatesURL=https://github.com/Farizma/MediaVault/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Media Vault
DefaultGroupName=Media Vault
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
; per-user by default; the first page offers "Install for all users", which elevates
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=MediaVault_v{#AppVersion}_setup
SetupIconFile=icon.ico
WizardImageFile=ui\brand\wizard-large.bmp
WizardSmallImageFile=ui\brand\wizard-small.bmp
UninstallDisplayIcon={app}\MediaVault.exe
UninstallDisplayName=Media Vault
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\MediaVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Media Vault"; Filename: "{app}\MediaVault.exe"
Name: "{group}\Uninstall Media Vault"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Media Vault"; Filename: "{app}\MediaVault.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MediaVault.exe"; Description: "Start Media Vault"; Flags: nowait postinstall skipifsilent
; an update from inside Media Vault runs setup with no wizard (/VERYSILENT /RELAUNCH): start Media Vault again after,
; as the person who asked for it (not as administrator, when an all-users copy needed elevation)
Filename: "{app}\MediaVault.exe"; Flags: nowait runasoriginaluser; Check: RelaunchAfterUpdate

[Registry]
; Media Vault itself writes its "Open with" entries (Settings › Integrations & APIs); uninstalling removes them.
; dontcreatekey: setup never adds them, it only cleans them up.
Root: HKCU; Subkey: "Software\Classes\MediaVault.Video"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: none; ValueName: "MediaVault.Video"; Flags: uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: none; ValueName: "MediaVault.Video"; Flags: uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Software\Classes\.avi\OpenWithProgids"; ValueType: none; ValueName: "MediaVault.Video"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; things Media Vault downloads into its own folder after install (video engines, shader)
Type: filesandordirs; Name: "{app}\bin"

[Code]
var
  Relaunched: Boolean;

// Media Vault's own updater passes /RELAUNCH with /VERYSILENT.
function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (Pos('/RELAUNCH', Uppercase(GetCmdTail)) > 0);
end;

// The nearest folder of Path that exists (setup creates the rest).
function ExistingParent(Path: String): String;
begin
  Result := RemoveBackslashUnlessRoot(Path);
  while (Result <> '') and not DirExists(Result) do
  begin
    if Result = ExtractFileDrive(Result) then begin Result := ''; Exit; end;
    Result := ExtractFileDir(Result);
  end;
end;

// Can this user create files there without administrator rights?
function CanWriteTo(Path: String): Boolean;
var
  Base, Probe: String;
begin
  Base := ExistingParent(Path);
  if Base = '' then begin Result := False; Exit; end;
  Probe := AddBackslash(Base) + 'mv-setup-' + IntToStr(Random(1000000)) + '.tmp';
  Result := SaveStringToFile(Probe, 'x', False);
  if Result then DeleteFile(Probe);
end;

// The folder needs administrator rights and this setup does not have them: start setup again elevated
// (UAC prompt), for all users, in the folder chosen, and close this copy.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: Integer;
  Params: String;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and (not WizardSilent) and (not IsAdminInstallMode) and (not CanWriteTo(WizardDirValue)) then
  begin
    if MsgBox('Installing to' + #13#10 + WizardDirValue + #13#10#13#10 +
              'needs administrator permission. Continue as administrator?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      // Start setup again in "all users" mode: setup's own loader then asks Windows for administrator
      // permission (the same UAC prompt as "Run as administrator"). The verb is left empty on purpose:
      // "runas" from inside the wizard fails on some PCs, while the loader's own elevation always works.
      Params := '/ALLUSERS /DIR="' + WizardDirValue + '"';
      if ShellExec('', ExpandConstant('{srcexe}'), Params, '', SW_SHOW, ewNoWait, Code) then
      begin
        Relaunched := True;
        WizardForm.Close;
      end
      else
        MsgBox('Setup could not restart as administrator (' + SysErrorMessage(Code) + ').' + #13#10#13#10 +
               'Right-click the setup file and choose "Run as administrator", or pick a folder you can write to, such as' + #13#10 +
               ExpandConstant('{localappdata}') + '\Programs\Media Vault', mbError, MB_OK);
    end;
    Result := False;
  end;
end;

// Closing because the elevated copy took over: no "Exit Setup?" question.
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Relaunched then Confirm := False;
end;
