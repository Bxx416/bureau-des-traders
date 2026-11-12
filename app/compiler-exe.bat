@echo off
rem Recompile "Bureau des Traders.exe" (compilateur C# fourni avec Windows).
cd /d "%~dp0.."
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /win32icon:app\icone.ico /r:System.Windows.Forms.dll /out:"Bureau des Traders.exe" app\lanceur.cs
