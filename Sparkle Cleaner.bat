@echo off
rem =====================================================================
rem  Sparkle Cleaner - bo khoi chay cho Windows.
rem
rem  CACH DUNG: nhan dup vao file nay.
rem
rem  [A] Lan dau chay se tu cai (30-60 giay): giai nen Python nhung va
rem      thu vien tu thu muc "win-runtime" nam canh file nay.
rem      KHONG CAN MANG, khong can quyen admin, khong can cai Python.
rem      Cac lan sau mo thang, khong cai lai.
rem
rem  [B] Neu KHONG co thu muc "win-runtime": chuyen sang tai tu Internet
rem      (Python ~11 MB va thu vien ~250 MB, 2-5 phut).
rem      Muon chuan bi truoc de chay offline, tren may co mang chay:
rem          python3 tools/fetch_windows_runtime.py
rem
rem  Tham so:
rem      --setup-only   chi cai dat, khong mo app
rem      --selftest     tu kiem tra roi in ket qua (dung khi bao loi)
rem
rem  File nay chi dung ky tu ASCII. cmd.exe doc sai ky tu co dau va se
rem  lam hong ca lenh goto/label, nen o day khong viet tieng Viet co dau.
rem =====================================================================
setlocal
cd /d "%~dp0"
title Sparkle Cleaner

rem Cho phep Python in tieng Viet co dau ra cua so nay. Khong anh huong
rem cac dong echo ASCII ben duoi.
chcp 65001 >nul 2>&1

set "PYVER=3.12.10"
set "PYTAG=312"
set "PYDIR=%~dp0python"
set "PY=%PYDIR%\python.exe"
set "PYW=%PYDIR%\pythonw.exe"
set "RUNTIME=%~dp0win-runtime"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
set "INSTALLER=%~dp0tools\win_install_wheels.py"
set "FRESH="

rem ---- 0. May phai la Windows 64-bit -------------------------------------
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 goto :fail_arch

rem ---- 1. Python nhung ---------------------------------------------------
if exist "%PY%" goto :have_python
echo.
if exist "%RUNTIME%\%PYZIP%" goto :python_offline

echo [1/3] Dang tai Python %PYVER% tu Internet (khoang 11 MB)...
call :download "%PYURL%" "%TEMP%\%PYZIP%"
if errorlevel 1 goto :fail_download
call :unzip_python "%TEMP%\%PYZIP%" "%PYDIR%"
del "%TEMP%\%PYZIP%" >nul 2>&1
goto :python_done

:python_offline
echo [1/3] Dang giai nen Python %PYVER% (co san, khong can mang)...
call :unzip_python "%RUNTIME%\%PYZIP%" "%PYDIR%"

:python_done
if not exist "%PY%" goto :fail_extract
if not exist "%PYW%" goto :fail_extract
set "FRESH=1"
:have_python

rem ---- 2. Thu vien -------------------------------------------------------
if exist "%RUNTIME%\wheels\" goto :deps_offline

rem --- [B] khong co san thi tai ve bang pip ---
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :have_pip
echo.
echo [2/3] Dang cai pip...
rem pip chi tim thay Lib\site-packages khi ._pth co dong "import site".
> "%PYDIR%\python%PYTAG%._pth" echo python%PYTAG%.zip
>> "%PYDIR%\python%PYTAG%._pth" echo .
>> "%PYDIR%\python%PYTAG%._pth" echo ..
>> "%PYDIR%\python%PYTAG%._pth" echo Lib\site-packages
>> "%PYDIR%\python%PYTAG%._pth" echo import site
call :download "https://bootstrap.pypa.io/get-pip.py" "%TEMP%\get-pip.py"
if errorlevel 1 goto :fail_download
"%PY%" "%TEMP%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto :fail_pip
del "%TEMP%\get-pip.py" >nul 2>&1
set "FRESH=1"
:have_pip
fc /b "requirements.txt" "%PYDIR%\.deps-ok" >nul 2>&1
if not errorlevel 1 goto :deps_done
echo.
echo [3/3] Dang tai thu vien tu Internet (khoang 250 MB, 2-5 phut)...
"%PY%" -m pip install --no-warn-script-location -r requirements.txt
if errorlevel 1 goto :fail_pip
copy /y "requirements.txt" "%PYDIR%\.deps-ok" >nul
set "FRESH=1"
goto :deps_done

rem --- [A] co san thi giai nen thang, khong can pip, khong can mang ---
:deps_offline
if not exist "%INSTALLER%" goto :fail_missing_installer
echo.
echo [2/3] Dang cai thu vien tu "win-runtime" (khong can mang)...
"%PY%" "%INSTALLER%" "%RUNTIME%" "%PYDIR%"
if errorlevel 1 goto :fail_deps_offline

:deps_done
if not defined FRESH goto :launch

rem ---- 3. Tu kiem tra ban cai --------------------------------------------
echo.
echo [3/3] Dang kiem tra ban cai...
"%PY%" -m sparkle_cleaner --selftest
if errorlevel 1 goto :fail_selftest
echo.
echo Cai dat xong. Cac lan sau mo se khong phai cho nua.

:launch
if /i "%~1"=="--setup-only" exit /b 0
if /i "%~1"=="--selftest" goto :run_selftest
start "" "%PYW%" -m sparkle_cleaner
exit /b 0

:run_selftest
echo.
"%PY%" -m sparkle_cleaner --selftest
rem Chot ma loi ngay: lenh "echo." ben duoi se dat lai errorlevel ve 0.
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%

rem ---- Thong bao loi ------------------------------------------------------
:fail_arch
echo.
echo LOI: may nay la Windows 32-bit, ma Sparkle Cleaner chi co ban 64-bit.
echo Hau het may tu nam 2012 tro lai deu la 64-bit. Kiem tra bang cach
echo nhan phim Windows + Pause, xem muc "System type".
goto :fail_end
:fail_download
echo.
echo LOI: khong tai duoc file tu Internet.
echo Kiem tra ket noi mang roi mo lai. Hoac lay ban co san thu muc
echo "win-runtime" de cai offline, khoi can mang.
goto :fail_end
:fail_extract
echo.
echo LOI: khong giai nen duoc Python.
echo - Neu dang chay thang tu USB: chep ca thu muc nay vao o C: hoac
echo   Desktop roi chay lai (USB co the bi chong ghi, va chay tu USB rat cham).
echo - Neu khong: xoa thu muc "python" nam canh file nay roi mo lai.
goto :fail_end
:fail_missing_installer
echo.
echo LOI: thieu file tools\win_install_wheels.py.
echo Thu muc chua duoc chep day du. Hay chep lai toan bo thu muc.
goto :fail_end
:fail_deps_offline
echo.
echo LOI: cai thu vien that bai. Xem thong bao tieng Viet phia tren.
echo Neu bao file hong thi chep lai ca thu muc tu nguon roi thu lai.
goto :fail_end
:fail_pip
echo.
echo LOI: cai thu vien that bai. Xem thong bao phia tren;
echo thu mo lai khi co mang on dinh.
goto :fail_end
:fail_selftest
echo.
echo LOI: ban cai chua chay duoc.
echo Chup lai ca cua so nay gui cho nguoi lam tool.
goto :fail_end
:fail_end
echo.
pause
exit /b 1

rem ---- Ham phu ------------------------------------------------------------
rem Tai file: %1 = URL, %2 = duong dan dich.
rem Dung curl.exe co san tren Windows 10 1803 tro len; khong co thi PowerShell.
:download
where curl.exe >nul 2>&1
if errorlevel 1 goto :download_ps
curl.exe -L --fail --silent --show-error -o %2 %1
exit /b %errorlevel%
:download_ps
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; (New-Object Net.WebClient).DownloadFile('%~1', '%~2')"
exit /b %errorlevel%

rem Giai nen bo Python nhung: %1 = file zip, %2 = thu muc dich.
rem Thu tar.exe truoc (co san tu Windows 10 1803, nhanh, khong dinh chinh
rem sach chay script), that bai thi lui ve PowerShell. Khong xet ma loi cua
rem tung lenh ma xet ket qua that: co python.exe trong thu muc dich hay chua.
:unzip_python
if not exist "%~2" mkdir "%~2"
tar.exe -xf "%~1" -C "%~2" >nul 2>&1
if exist "%~2\python.exe" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~1' -DestinationPath '%~2' -Force" >nul 2>&1
exit /b 0
