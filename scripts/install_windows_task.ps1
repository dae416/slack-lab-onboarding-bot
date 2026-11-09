# install_windows_task.ps1 - run the onboarding bot in the background on Windows with Task Scheduler (no admin rights).
#
# The task starts the venv's pythonw.exe (no console window) at every logon of the current user, restarts it every
# minute if it exits with an error, never stops it for running too long (the default limit is 3 days), and never starts
# a second copy. A second trigger (daily, repeating every 5 minutes) starts it again if it is not running; once
# enable_no_login.ps1 has been run, that brings the bot back within 5 minutes of a reboot even without a logon.
# The bot notices it has no console and writes its log to bot.log next to onboarding_bot.py.
#
# Run in a normal (non-elevated) PowerShell from the repository folder, after the venv is set up and a manual run works:
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
# Options: -TaskName <name> (default LabOnboardingBot), -BotDir <folder with onboarding_bot.py> (default: this repo)
param(
    [string]$TaskName = "LabOnboardingBot",
    [string]$BotDir = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
$pythonw = Join-Path $BotDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Not found: $pythonw (create the venv first: README.md, step 4)" }
if (-not (Test-Path (Join-Path $BotDir "onboarding_bot.py"))) { throw "onboarding_bot.py is not in $BotDir" }

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "onboarding_bot.py" -WorkingDirectory $BotDir
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$watchdog = New-ScheduledTaskTrigger -Daily -At "00:00"
$watchdog.Repetition = (New-ScheduledTaskTrigger -Once -At "00:00" -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$watchdog.Repetition.StopAtDurationEnd = $false  # never kill the running instance at the end of the day
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"  # no time limit
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$description = "Lab onboarding Slack bot (Socket Mode). Log: $BotDir\bot.log. " +
    "Restart: Stop-ScheduledTask -TaskName $TaskName; Start-ScheduledTask -TaskName $TaskName"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atLogon, $watchdog) -Settings $settings `
    -Principal $principal -Description $description -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 15
Write-Host "Task $TaskName state: $((Get-ScheduledTask -TaskName $TaskName).State)  (expected: Running)"
$log = Join-Path $BotDir "bot.log"
if (Test-Path $log) {
    Write-Host "Last lines of bot.log (expect 'Bolt app is running!'):"
    Get-Content $log -Tail 6 -Encoding UTF8
}
Write-Host ""
Write-Host "Watch the log:  Get-Content `"$log`" -Wait -Tail 20 -Encoding UTF8"
Write-Host "Restart:        Stop-ScheduledTask -TaskName $TaskName; Start-ScheduledTask -TaskName $TaskName"
Write-Host "Remove:         Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host "Run without a logon after reboots (optional): scripts\enable_no_login.ps1"
