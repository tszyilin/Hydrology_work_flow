@echo off
rem Starts the standalone Landsat Bulk Downloader with Anaconda Python
"C:\ProgramData\anaconda3\python.exe" "%~dp0landsat_gui.py"
if errorlevel 1 pause
