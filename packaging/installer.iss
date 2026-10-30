#ifndef MyAppVersion
#define MyAppVersion "1.1.0"
#endif

[Setup]
AppId={{8E67B8C0-0D37-4E96-AF1E-6A9D3E7C4E21}
AppName=Реестр договоров
AppVersion={#MyAppVersion}
AppVerName=Реестр договоров {#MyAppVersion}
AppPublisher=Reestr Dogovorov
DefaultDirName={autopf}\ReestrDogovorov
DefaultGroupName=Реестр договоров
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ReestrDogovorov-Setup-{#MyAppVersion}
SetupIconFile=reestr.ico
UninstallDisplayIcon={app}\ReestrDogovorov.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=Установщик сетевого реестра договоров

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе сервера"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\ReestrDogovorov\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "register-server.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion
Source: "remove-server.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion
Source: "CLIENT-README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\Реестр договоров1.xlsx"; DestDir: "{app}\Образцы"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\ReestrDogovorov\data"; Flags: uninsneveruninstall
Name: "{commonappdata}\ReestrDogovorov\backups"; Flags: uninsneveruninstall
Name: "{commonappdata}\ReestrDogovorov\exports"; Flags: uninsneveruninstall
Name: "{commonappdata}\ReestrDogovorov\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Реестр договоров"; Filename: "{app}\ReestrDogovorov.exe"; Parameters: "--launch"; IconFilename: "{app}\ReestrDogovorov.exe"
Name: "{group}\Подключение пользователей"; Filename: "{app}\CLIENT-README.txt"
Name: "{commondesktop}\Реестр договоров"; Filename: "{app}\ReestrDogovorov.exe"; Parameters: "--launch"; IconFilename: "{app}\ReestrDogovorov.exe"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\register-server.ps1"" -InstallDir ""{app}"""; Flags: runhidden waituntilterminated; StatusMsg: "Настройка общего сервера и сетевого доступа…"
Filename: "{app}\ReestrDogovorov.exe"; Parameters: "--launch"; Description: "Открыть Реестр договоров"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\remove-server.ps1"""; Flags: runhidden waituntilterminated

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  OldScript: String;
begin
  OldScript := ExpandConstant('{app}\setup\remove-server.ps1');
  if FileExists(OldScript) then
    Exec('powershell.exe', '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + OldScript + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM ReestrDogovorov.exe /F /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);
  Result := '';
end;
