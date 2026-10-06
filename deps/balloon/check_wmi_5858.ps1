# Check for WMI-Activity Event ID 5858 errors since blnsvr.exe started
# Exit codes:
#   0 - No WMI 5858 events found (NONE)
#   1 - WMI 5858 event found (HIT)
#   2 - Balloon service process not running (NO_PID)

$ErrorActionPreference = 'SilentlyContinue'
$log = 'Microsoft-Windows-WMI-Activity/Operational'

# Get the balloon service process
$p = Get-Process -Name blnsvr -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) {
    Write-Output 'NO_PID'
    exit 2
}

$blnPid = $p.Id
$start = $p.StartTime.ToUniversalTime()

# Query for WMI 5858 events since the process started
$events = Get-WinEvent -FilterHashtable @{
    LogName   = $log
    Id        = 5858
    StartTime = $start
} -MaxEvents 50 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Level -eq 2 -and
        $_.Message -match ('ClientProcessId = ' + $blnPid)
    }

$e = $events | Select-Object -First 1

if ($null -ne $e) {
    Write-Output 'HIT'
    ($e | Format-List -Property TimeCreated, Id, Message | Out-String).Trim() | Write-Output
    exit 1
} else {
    Write-Output 'NONE'
    exit 0
}
