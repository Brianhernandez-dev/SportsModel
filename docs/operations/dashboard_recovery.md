# Dashboard Boot and Recovery Runbook

## Reliability invariant

After Windows reboot/update, SportsModel Dashboard must return to HTTP 200
without an interactive user logon.

The dashboard is a read-only Streamlit process rooted at `D:\SportsModel`. Its
scheduled-task contract does not authorize database writes, provider calls, or
changes to any MLB or NFL pipeline task.

## Root causes addressed

The former task had only an `AtLogOn` trigger for `AI-BETO\Brian`. An S4U
principal, `StartWhenAvailable`, and restart-on-failure settings do not create a
boot event, so the dashboard remained offline after a reboot until Brian logged
on.

The former launcher invoked Python directly from PowerShell without an explicit
Windows process-lifetime boundary. Stopping the scheduled task could terminate
PowerShell while leaving a descendant Python/Streamlit listener alive. A later
task start could therefore report misleading state or continue serving stale
code.

These are separate defects: the first is missing reboot recovery; the second is
orphaned-child process ownership.

## Repository-managed task contract

`scripts/register_dashboard_task.ps1` deterministically replaces the single
task named `SportsModel - Dashboard` with this definition:

- one action: hidden Windows PowerShell running
  `D:\SportsModel\scripts\run_dashboard.ps1 -Port 8501` from
  `D:\SportsModel`;
- `AtStartup` trigger with a configurable 60-90 second delay (75 seconds by
  default);
- `AtLogOn` trigger for the same user by default, retained as a fallback if the
  startup attempt exhausts its retries;
- S4U, limited principal, so no interactive logon or stored password is needed;
- `IgnoreNew`, so the logon trigger cannot create a second instance while the
  startup-trigger instance is running;
- three one-minute restart attempts, `StartWhenAvailable`, unlimited execution
  time, and no battery stop restrictions.

S4U is appropriate because the dashboard uses the local repository, local
virtual environment, local configuration, and locally reachable database. S4U
does not provide normal access to remote network shares or other resources that
require delegated credentials. If such a dependency is introduced, stop and
review the principal design instead of silently changing credential behavior.

The registration script uses one fixed task name and `Register-ScheduledTask
-Force`, making the definition safe to reapply. It does not enumerate, update,
or remove other SportsModel tasks.

## Process ownership

`scripts/run_dashboard.ps1` starts Streamlit with `Start-Process -PassThru` and
assigns the exact child to a Windows Job Object configured with
`KILL_ON_JOB_CLOSE`. PowerShell retains the job handle while it waits. Normal
cleanup, an unexpected wrapper exit, and Task Scheduler termination all close
the handle, causing Windows to terminate the owned dashboard process tree.

The launcher never kills Python by image name. Its fallback cleanup targets only
the PID it created. Before starting, it checks port 8501. It will clean up an
existing listener only when the process is provably Python running Streamlit for
the exact dashboard app path and port. If ownership cannot be proved, startup
fails without terminating the process.

## Health and self-recovery contract

Task state `Running` is not sufficient. `scripts/check_dashboard_health.ps1`
defines a healthy dashboard as both:

1. a successful TCP connection to `127.0.0.1:8501`; and
2. HTTP 200 from `http://127.0.0.1:8501/_stcore/health`.

The launcher allows 60 seconds for startup, checks every five seconds, and fails
after three consecutive unhealthy checks outside the grace period. Failing the
wrapper closes the Job Object and returns a nonzero exit code, allowing Task
Scheduler's restart policy to run the exact task again.

## Failure and recovery matrix

| Scenario | Expected behavior |
| --- | --- |
| Streamlit exits | Wrapper returns a nonzero service-failure result; Task Scheduler retries up to three times at one-minute intervals. |
| PowerShell wrapper exits or is stopped | The Job Object handle closes and Windows terminates the owned Streamlit tree. A failure exit is retried by Task Scheduler; an operator stop remains stopped until a trigger or explicit start. |
| Port 8501 has a proven stale SportsModel dashboard | Launcher terminates only that proven listener tree, verifies the port is free, and starts its owned instance. |
| Port 8501 has an unknown or unverifiable owner | Launcher refuses to kill it, exits nonzero, and leaves the process untouched for investigation. |
| HTTP health fails while Python remains alive | After the grace period and three failures, the watchdog exits; Job Object cleanup terminates the owned tree and Task Scheduler retries. |
| Machine reboots | Startup trigger runs after the configured delay without waiting for user logon. |
| User never logs in | S4U startup execution continues normally because the dashboard uses only compatible local resources. |
| User logs in while startup instance is running | Logon fallback fires, but `IgnoreNew` suppresses a duplicate task instance and listener. |

## Review and dry validation

The task definition can be built without registration:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_dashboard_task.ps1 -UserId 'AI-BETO\Brian' -StartupDelaySeconds 75 -WhatIf
```

`-WhatIf` must report the one `SportsModel - Dashboard` target. It must not be
used as evidence that production has been updated.

## Controlled production update

Changing or restarting the production task requires explicit approval. After
approval, use this sequence from an elevated PowerShell session in
`D:\SportsModel`:

1. Capture `Get-ScheduledTask` and `Get-ScheduledTaskInfo` for
   `SportsModel - Dashboard`, the exact port-8501 listener PID and ancestry, and
   the current HTTP health result.
2. Run `Stop-ScheduledTask -TaskName 'SportsModel - Dashboard'`.
3. Wait for task state to leave `Running`, then check port 8501. If a listener
   remains, prove from its executable path, command line, app path, port, and
   captured ancestry that it is the old dashboard. Terminate only that exact PID
   tree. If identity cannot be proved, stop the deployment and investigate.
4. Apply the reviewed definition:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_dashboard_task.ps1 -UserId 'AI-BETO\Brian' -StartupDelaySeconds 75 -Confirm:$false
   ```

5. Run `Start-ScheduledTask -TaskName 'SportsModel - Dashboard'`.
6. Verify one and only one listener, its ancestry beneath the scheduled
   PowerShell wrapper, and real health:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_dashboard_health.ps1 -Port 8501
   ```

7. Re-read the task and confirm the startup and logon triggers, 75-second startup
   delay, S4U/limited principal, `IgnoreNew`, restart count/interval,
   `StartWhenAvailable`, unlimited execution time, action, and working directory.

## Reboot verification

A reboot test is a separate production operation and requires explicit approval.
After deployment, perform one controlled reboot and do not log on during the
startup window. After at least 75 seconds, verify remotely or from an authorized
non-interactive monitor that the task ran, exactly one process owns
`127.0.0.1:8501`, and the Streamlit health endpoint returns HTTP 200. Logging on
must not create a second listener.

## Unexpected port owner

Do not kill a process solely because it owns port 8501. Record its PID, executable
path, command line, owner, parent chain, and start time. Compare those values to
the scheduled action and exact dashboard app path. If it cannot be proved to be
the SportsModel dashboard, leave it running and escalate the conflict. If it is
proved to be an obsolete dashboard tree during an approved controlled restart,
terminate only its exact PID tree and recheck the port before starting the task.
