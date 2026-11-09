# enable_no_login.ps1 - optional: let the bot's scheduled task run without an interactive logon, so the bot comes back
# by itself within 5 minutes after any reboot (Windows-update restarts included) even if nobody logs in.
#
# Run it in YOUR OWN PowerShell window; it asks for your Windows password (never type it into a chat or a file):
#   powershell -ExecutionPolicy Bypass -File scripts\enable_no_login.ps1 [-TaskName LabOnboardingBot]
#
# Task Scheduler stores the password encrypted (an LSA secret, readable only by SYSTEM and admins). Windows auto-login
# is NOT used. Re-run this script after every password change, otherwise the task fails with "Logon failure"
# (0x8007052E). If it fails with 0x80070569, your account lacks the "Log on as a batch job" right on this PC: ask IT.
param([string]$TaskName = "LabOnboardingBot")

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) { Write-Host "No task named $TaskName; run scripts\install_windows_task.ps1 first."; exit 1 }
$botDir = $task.Actions[0].WorkingDirectory
$log = Join-Path $botDir "bot.log"
$user = "$env:USERDOMAIN\$env:USERNAME"

$cred = Get-Credential -UserName $user -Message "Windows password for $user (stored by Task Scheduler for the $TaskName task)"
if ($null -eq $cred) { Write-Host "Cancelled."; exit 1 }

try {
    Set-ScheduledTask -TaskName $TaskName -User $cred.UserName -Password $cred.GetNetworkCredential().Password -ErrorAction Stop | Out-Null
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
    Write-Host "If the message mentions the logon type or 0x80070569, your account lacks the 'Log on as a batch job' right on this PC."
    Write-Host "Ask IT to grant it (Local Security Policy > User Rights Assignment > Log on as a batch job), then run this script again."
    exit 1
}

Write-Host "Task logon type is now: $((Get-ScheduledTask -TaskName $TaskName).Principal.LogonType) (expected: Password)"
Write-Host "Restarting the bot under the new logon type..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 20
Write-Host "Task state: $((Get-ScheduledTask -TaskName $TaskName).State)  (expected: Running)"
Write-Host "Last lines of bot.log (expect a fresh 'Bolt app is running!'):"
Get-Content $log -Tail 4 -Encoding UTF8
Write-Host ""
Write-Host "If bot.log shows 'Missing SLACK_BOT_TOKEN ...', the task cannot see your env file: set ONBOARDING_BOT_ENV as a"
Write-Host "user environment variable pointing to it, or check that the file is in your home folder."
