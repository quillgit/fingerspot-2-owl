[Setup]
AppName=FP2 Pivot App
AppVersion=1.0
DefaultDirName={pf}\FP2PivotApp
DefaultGroupName=FP2 Pivot App
OutputDir=Output
OutputBaseFilename=FP2PivotApp_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\FP2PivotApp.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FP2 Pivot App"; Filename: "{app}\FP2PivotApp.exe"
Name: "{commondesktop}\FP2 Pivot App"; Filename: "{app}\FP2PivotApp.exe"

[Run]
Filename: "{app}\FP2PivotApp.exe"; Description: "Launch FP2 Pivot App"; Flags: nowait postinstall skipifsilent