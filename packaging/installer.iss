; SCAN2BOOK telepítő (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1E2B57-3F4A-4E7B-9C1D-SCAN2BOOK0001}
AppName=SCAN2BOOK
AppVersion={#AppVersion}
AppPublisher=Ekidio
DefaultDirName={autopf}\SCAN2BOOK
DefaultGroupName=SCAN2BOOK
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=SCAN2BOOK-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\SCAN2BOOK.exe
LicenseFile=..\LICENSE
AppPublisherURL=https://ekidio.github.io/SCAN2BOOK/
AppSupportURL=https://github.com/Ekidio/SCAN2BOOK

[Languages]
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\SCAN2BOOK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SCAN2BOOK"; Filename: "{app}\SCAN2BOOK.exe"
Name: "{group}\{cm:UninstallProgram,SCAN2BOOK}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SCAN2BOOK"; Filename: "{app}\SCAN2BOOK.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SCAN2BOOK.exe"; Description: "{cm:LaunchProgram,SCAN2BOOK}"; Flags: nowait postinstall skipifsilent
