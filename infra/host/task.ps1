# The watchdog of the host daemon: a Task Scheduler task `ace-host` that runs `node infra/host/cli.mjs revive`
# at logon and every 5 minutes as the current user (no admin, no password, no window: wscript hidden.vbs).
# `revive` is a no-op while a daemon runs, so the task costs ~200 ms per tick and never touches the wanted set.
# Usage: powershell -File infra/host/task.ps1 install | uninstall | status   (bun run host:install | host:uninstall)
param([Parameter(Position = 0)][ValidateSet('install', 'uninstall', 'status')][string]$Command = 'status')
$ErrorActionPreference = 'Stop'
$Name = 'ace-host'

switch ($Command) {
  'install' {
    $node = (Get-Command node.exe).Source
    $cli = Join-Path $PSScriptRoot 'cli.mjs'
    $vbs = Join-Path $PSScriptRoot 'hidden.vbs'
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" `
      -Argument "//B //Nologo `"$vbs`" `"$node`" `"$cli`" revive" -WorkingDirectory $PSScriptRoot
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Repetition = $repeat.Repetition
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
      -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($logon, $repeat) -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $Name
    "task $Name registered: `"$node`" `"$cli`" revive at logon and every 5 min (as $env:USERNAME)"
  }
  'uninstall' {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    "task $Name removed"
  }
  'status' {
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) { "task $Name is not registered (bun run host:install)"; exit 1 }
    $info = Get-ScheduledTaskInfo -TaskName $Name
    "task ${Name}: $($task.State); last run $($info.LastRunTime) exit $($info.LastTaskResult); next run $($info.NextRunTime)"
  }
}
