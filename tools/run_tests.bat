@echo off
rem Runs comfyui_pcg's test suites with the portable ComfyUI's own Python (double-click, or run from a console).
rem   run_tests.bat            all suites but the heavy production workflows (a few minutes)
rem   run_tests.bat --full     the production workflows too (about 45 minutes, up to 6 GB of memory)
rem   run_tests.bat -k cop     only the suites whose file name contains "cop"
rem The output of every suite is written to test-logs\ next to the plugin's README.
setlocal
set "PLUGIN=%~dp0.."
set "PY=%PLUGIN%\..\..\..\python_embeded\python.exe"
if not exist "%PY%" set "PY=python"
set "ARGS=--quick"
if /I "%~1"=="--full" (
  set "ARGS="
  shift
)
pushd "%PLUGIN%"
"%PY%" -B tests\run_tests.py %ARGS% --logs test-logs %1 %2 %3 %4 %5 %6
set "RC=%ERRORLEVEL%"
popd
echo.
if "%RC%"=="0" (echo All suites passed.) else (echo Some suites failed: see test-logs\ for their output.)
pause
exit /b %RC%
