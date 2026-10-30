#ifndef MyAppVersion
#define MyAppVersion "1.2.0"
#endif

[Setup]
AppId={{8E67B8C0-0D37-4E96-AF1E-6A9D3E7C4E21}
AppName=Реестр договоров
AppVersion={#MyAppVersion}
AppVerName=Реестр договоров {#MyAppVersion}
AppPublisher=Zakharevich Igor
AppPublisherURL=http://csl.by
AppSupportURL=mailto:ziv@csl.by
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
var
  AdminPage: TInputQueryWizardPage;
  AdminUsername: String;
  AdminPassword: String;

function AdminConfigured: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonappdata}\ReestrDogovorov\auth.json'));
end;

function AdminBootstrapPath: String;
begin
  Result := ExpandConstant('{commonappdata}\ReestrDogovorov\bootstrap-admin.json');
end;

procedure InitializeWizard;
begin
  AdminPage := CreateInputQueryPage(wpSelectDir,
    'Администратор резервных копий',
    'Создание защищённой учётной записи',
    'Только этот администратор сможет управлять копиями и восстанавливать базу. Остальные пользователи продолжат работать по имени без пароля.');
  AdminPage.Add('Логин администратора:', False);
  AdminPage.Add('Пароль (от 8 до 256 символов):', True);
  AdminPage.Add('Повторите пароль:', True);
  AdminPage.Values[0] := 'admin';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = AdminPage.ID) and AdminConfigured;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = AdminPage.ID then
  begin
    if (Length(Trim(AdminPage.Values[0])) < 3) or (Length(Trim(AdminPage.Values[0])) > 64) then
    begin
      MsgBox('Логин администратора должен содержать от 3 до 64 символов.', mbError, MB_OK);
      Result := False;
      exit;
    end;
    if (Length(AdminPage.Values[1]) < 8) or (Length(AdminPage.Values[1]) > 256) then
    begin
      MsgBox('Пароль администратора должен содержать от 8 до 256 символов.', mbError, MB_OK);
      Result := False;
      exit;
    end;
    if AdminPage.Values[1] <> AdminPage.Values[2] then
    begin
      MsgBox('Пароли не совпадают.', mbError, MB_OK);
      Result := False;
      exit;
    end;
    AdminUsername := Trim(AdminPage.Values[0]);
    AdminPassword := AdminPage.Values[1];
  end;
end;

function JsonEscape(const Value: String): String;
var
  I: Integer;
  Code: Integer;
begin
  // ASCII-only JSON is independent of the ANSI/UTF-8 encoding used by SaveStringToFile.
  // Inno strings are UTF-16; Python json.loads also combines escaped surrogate pairs.
  Result := '';
  for I := 1 to Length(Value) do
  begin
    Code := Ord(Value[I]);
    if (Code < 32) or (Code > 126) then
      Result := Result + '\u' + IntToHex(Code, 4)
    else if (Code = 34) or (Code = 92) then
      Result := Result + '\' + Value[I]
    else
      Result := Result + Value[I];
  end;
end;

function PrepareAdminBootstrap: String;
var
  BootstrapDir: String;
  Params: String;
  Json: String;
  ResultCode: Integer;
begin
  Result := '';
  if AdminConfigured then
    exit;
  if (AdminUsername = '') or (AdminPassword = '') then
  begin
    Result := 'Не указаны учётные данные администратора. Выполните установку в интерактивном режиме.';
    exit;
  end;
  BootstrapDir := ExpandConstant('{commonappdata}\ReestrDogovorov');
  if not ForceDirectories(BootstrapDir) then
  begin
    Result := 'Не удалось создать каталог ProgramData для настройки администратора.';
    exit;
  end;
  Params := '"' + BootstrapDir + '" /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F"';
  if not Exec('icacls.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Result := 'Не удалось защитить временный файл учётных данных администратора.';
    exit;
  end;
  Json := '{"username":"' + JsonEscape(AdminUsername) + '","password":"' + JsonEscape(AdminPassword) + '"}';
  if not SaveStringToFile(AdminBootstrapPath, Json, False) then
    Result := 'Не удалось подготовить инициализацию администратора.';
end;

procedure DeinitializeSetup;
begin
  if FileExists(AdminBootstrapPath) then
    DeleteFile(AdminBootstrapPath);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  OldScript: String;
begin
  Result := PrepareAdminBootstrap;
  if Result <> '' then
    exit;
  OldScript := ExpandConstant('{app}\setup\remove-server.ps1');
  if FileExists(OldScript) then
    Exec('powershell.exe', '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + OldScript + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM ReestrDogovorov.exe /F /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);
  Result := '';
end;
