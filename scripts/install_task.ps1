<#
.SYNOPSIS
    Register Job Radar as a daily Windows scheduled task.

.DESCRIPTION
    Generates the task definition from this checkout -- your paths, your user
    account -- and registers it. The generated XML is gitignored, because it
    contains a local username and absolute paths.

    Three settings here cannot be set from a plain `schtasks` command line and
    matter on a laptop:

      StartWhenAvailable          runs a job missed while the machine was
                                  asleep, instead of skipping the day
      DisallowStartIfOnBatteries  off, or nothing runs while unplugged
      RestartOnFailure            retries, covering a wake before the network

    The first trigger is set for TOMORROW. Dating it today would combine with
    StartWhenAvailable to fire a full fetch-score-post run the moment you
    register it, which is a surprise nobody wants.

    On macOS or Linux, use cron instead:
      0 6 * * * cd /path/to/job-radar && ./venv/bin/python scripts/run_daily.py

.PARAMETER Time
    24 hour HH:mm. Defaults to 06:00.

.PARAMETER TaskName
    Defaults to "Job Radar".

.EXAMPLE
    .\scripts\install_task.ps1
    .\scripts\install_task.ps1 -Time 07:30
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = "06:00",

    [string]$TaskName = "Job Radar"
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectDir "venv\Scripts\python.exe"
$xmlPath = Join-Path $PSScriptRoot "job_radar_task.xml"
$user = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path $python)) {
    throw "No virtualenv at $python. Run: python -m venv venv; venv\Scripts\pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $projectDir ".env"))) {
    Write-Warning "No .env found. The task will run but cannot fetch or score until you create one."
}
if (-not (Test-Path (Join-Path $projectDir "profile.txt"))) {
    Write-Warning "No profile.txt found. Copy profile.example.txt to profile.txt and edit it."
}

# Start tomorrow, so registering does not trigger an immediate catch-up run.
$start = (Get-Date).Date.AddDays(1).ToString("yyyy-MM-dd") + "T$Time`:00"

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Job Radar: fetch free job boards, score new postings, post the daily digest to Slack.</Description>
    <URI>\$TaskName</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT15M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$python</Command>
      <Arguments>scripts\run_daily.py</Arguments>
      <WorkingDirectory>$projectDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$xml | Out-File -FilePath $xmlPath -Encoding Unicode
schtasks /create /tn $TaskName /xml $xmlPath /f | Out-Null

Write-Host "Registered '$TaskName' for $user, daily at $Time." -ForegroundColor Green
schtasks /query /tn $TaskName /fo list /v |
    Select-String -Pattern "Next Run Time|Task To Run|Start In"
Write-Host ""
Write-Host "Run it now with:  schtasks /run /tn `"$TaskName`""
Write-Host "Remove it with:   schtasks /delete /tn `"$TaskName`" /f"
