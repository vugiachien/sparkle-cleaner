; Bộ cài Sparkle Cleaner cho Windows (NSIS 3, biên dịch với -INPUTCHARSET UTF8).
;
; Cài cho người dùng hiện tại vào %LOCALAPPDATA%\Programs\Sparkle Cleaner, không
; cần quyền admin. Sau khi chép file, chạy "Sparkle Cleaner.bat --setup-only" để
; tải Python nhúng + thư viện về ngay trong lúc cài (cần mạng, ~250 MB).
; Gỡ cài đặt xoá toàn bộ thư mục, kể cả Python và thư viện đã tải.

Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!define APPNAME "Sparkle Cleaner"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SparkleCleaner"

Name "${APPNAME}"
OutFile "..\..\dist\SparkleCleaner-${VERSION}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Sparkle Cleaner"
InstallDirRegKey HKCU "${REGKEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

!define MUI_ICON "..\..\assets\sparkle.ico"
!define MUI_UNICON "..\..\assets\sparkle.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Cài ${APPNAME}"
!define MUI_WELCOMEPAGE_TEXT "Trình cài đặt sẽ chép chương trình vào máy, rồi tự tải Python và các thư viện cần thiết (khoảng 250 MB, cần mạng, 2–5 phút).$\r$\n$\r$\nKhông cần quyền quản trị, không cần cài Python trước.$\r$\n$\r$\nNhấn nút tiếp theo để bắt đầu."
!define MUI_FINISHPAGE_RUN "$INSTDIR\Sparkle Cleaner.bat"
!define MUI_FINISHPAGE_RUN_TEXT "Mở ${APPNAME} ngay"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Vietnamese"

; Thông tin phiên bản hiện trong Properties của file Setup.exe. Phải đặt sau khi
; đã nạp ngôn ngữ, và ghi rõ /LANG để makensis không phải đoán.
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=${LANG_VIETNAMESE} "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=${LANG_VIETNAMESE} "FileDescription" "Bộ cài ${APPNAME}"
VIAddVersionKey /LANG=${LANG_VIETNAMESE} "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_VIETNAMESE} "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_VIETNAMESE} "LegalCopyright" "${APPNAME}"

Section "Cài đặt"
  SetOutPath "$INSTDIR"
  File "..\..\Sparkle Cleaner.bat"
  File "..\..\requirements.txt"
  File "..\..\README.md"
  File "..\..\assets\sparkle.ico"
  SetOutPath "$INSTDIR\sparkle_cleaner"
  File "..\..\sparkle_cleaner\*.py"
  File "..\..\sparkle_cleaner\sparkle.png"
  ; Bộ cài offline: .bat gọi tới file này khi có sẵn thư mục win-runtime.
  SetOutPath "$INSTDIR\tools"
  File "..\..\tools\win_install_wheels.py"
  SetOutPath "$INSTDIR"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\sparkle.ico"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${REGKEY}" "Publisher" "${APPNAME}"
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\Sparkle Cleaner.bat" "" "$INSTDIR\sparkle.ico" 0 SW_SHOWMINIMIZED
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Gỡ cài đặt ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\Sparkle Cleaner.bat" "" "$INSTDIR\sparkle.ico" 0 SW_SHOWMINIMIZED

  DetailPrint "Đang tải Python và thư viện (cần mạng, 2–5 phút)…"
  ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\Sparkle Cleaner.bat" --setup-only"' $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONEXCLAMATION "Chưa tải xong thư viện (có thể do mất mạng).$\r$\nKhông sao: lần mở ${APPNAME} tiếp theo sẽ tự tải tiếp."
  ${EndIf}
SectionEnd

Section "Uninstall"
  ; Chỉ xoá khi đúng là thư mục của app, tránh xoá nhầm nếu người dùng chọn chỗ lạ.
  ${If} ${FileExists} "$INSTDIR\sparkle_cleaner\app.py"
    RMDir /r "$INSTDIR"
  ${EndIf}
  Delete "$SMPROGRAMS\${APPNAME}\*.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
