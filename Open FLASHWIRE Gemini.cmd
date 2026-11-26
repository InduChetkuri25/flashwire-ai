@echo off
start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" "--user-data-dir=%~dp0..\..\work\flashwire-state\gemini-profile" --no-first-run --no-default-browser-check https://gemini.google.com/app
