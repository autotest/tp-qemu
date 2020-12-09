<#
.SYNOPSIS
  toolsHLK: Powershell wrapper for HLK Studio API.
.DESCRIPTION
  A script tool set for HLK automation powered by HLK API provided with the Microsoft's Windows HLK Studio.
#>

# server switch to inform the script is to run as a server
[CmdletBinding()]
param([Switch]$server, [Int]$port = 4000, [Int]$timeout = 60, [Int]$polling = 10)

if ($env:WTTSTDIO -like "*\Hardware Lab Kit\*") {
    $Studio = "hlk"
    if ($env:PROCESSOR_ARCHITECTURE -ne "x86") {

        if (-Not $json) {
            Write-Warning "hlk script should be run under a 32bit PowerShell"
            Write-Host "Redirecting ..."
        }

        $PowerShell = [System.IO.Path]::Combine($PSHOME.tolower().replace("system32","sysWOW64"), "powershell.exe")

        $Params = [String]::Empty

        if ($server) {
            $Params += "-server -port $port -timeout $timeout -polling $polling"
        }

        $Invocation = "$PSCommandPath $Params"

        Invoke-Expression "Invoke-Command -ScriptBlock { $PowerShell -File $Invocation }"

        exit $LASTEXITCODE
    }
} else {
    $Studio = "hlk"
}

##
$Version = "0.0.1"
$MaxJsonDepth = 6
##

#
# Loadinf HLK libraries
[System.Reflection.Assembly]::LoadFrom($env:WTTSTDIO + "\microsoft.windows.kits.hardware.filterengine.dll") | Out-Null
[System.Reflection.Assembly]::LoadFrom($env:WTTSTDIO + "\microsoft.windows.kits.hardware.objectmodel.dll") | Out-Null
[System.Reflection.Assembly]::LoadFrom($env:WTTSTDIO + "\microsoft.windows.kits.hardware.objectmodel.dbconnection.dll") | Out-Null
[System.Reflection.Assembly]::LoadFrom($env:WTTSTDIO + "\microsoft.windows.kits.hardware.objectmodel.submission.dll") | Out-Null
[System.Reflection.Assembly]::LoadFrom($env:WTTSTDIO + "\microsoft.windows.kits.hardware.objectmodel.submission.package.dll") | Out-Null

#
# Task
function New-Task($name, $stage, $status, $taskerrormessage, $tasktype, $childtasks) {
    $task = New-Object PSObject
    $task | Add-Member -type NoteProperty -Name name -Value $name
    $task | Add-Member -type NoteProperty -Name stage -Value $stage
    $task | Add-Member -type NoteProperty -Name status -Value $status
    $task | Add-Member -type NoteProperty -Name taskerrormessage -Value $taskerrormessage
    $task | Add-Member -type NoteProperty -Name tasktype -Value $tasktype
    $task | Add-Member -type NoteProperty -Name childtasks -Value $childtasks
    return $task
}

#
# PackageProgressInfo
function New-PackageProgressInfo($current, $maximum, $message) {
    $packageprogressinfo = New-Object PSObject
    $packageprogressinfo | Add-Member -type NoteProperty -Name current -Value $current
    $packageprogressinfo | Add-Member -type NoteProperty -Name maximum -Value $maximum
    $packageprogressinfo | Add-Member -type NoteProperty -Name message -Value $message
    return $packageprogressinfo
}

#
# ProjectPackage
function New-ProjectPackage($name, $projectpackagepath) {
    $projectpackage = New-Object PSObject
    $projectpackage | Add-Member -type NoteProperty -Name name -Value $name
    $projectpackage | Add-Member -type NoteProperty -Name projectpackagepath -Value $projectpackagepath
    return $projectpackage
}

#
# TestResultLogsZip
function New-TestResultLogsZip($testname, $testid,$status, $logszippath) {
    $testresultlogszip = New-Object PSObject
    $testresultlogszip | Add-Member -type NoteProperty -Name testname -Value $testname
    $testresultlogszip | Add-Member -type NoteProperty -Name testid -Value $testid
    $testresultlogszip | Add-Member -type NoteProperty -Name status -Value $status
    $testresultlogszip | Add-Member -type NoteProperty -Name logszippath -Value $logszippath
    return $testresultlogszip
}

#
# TestResult
function New-TestResult($name, $completiontime, $scheduletime, $starttime, $status, $arefiltersapplied, $target, $tasks) {
    $testresult = New-Object PSObject
    $testresult | Add-Member -type NoteProperty -Name name -Value $name
    $testresult | Add-Member -type NoteProperty -Name completiontime -Value $completiontime
    $testresult | Add-Member -type NoteProperty -Name scheduletime -Value $scheduletime
    $testresult | Add-Member -type NoteProperty -Name starttime -Value $starttime
    $testresult | Add-Member -type NoteProperty -Name status -Value $status
    $testresult | Add-Member -type NoteProperty -Name arefiltersapplied -Value $arefiltersapplied
    $testresult | Add-Member -type NoteProperty -Name target -Value $target
    $testresult | Add-Member -type NoteProperty -Name tasks -Value $tasks
    return $testresult
}

#
# FilterResult
function New-FilterResult($appliedfilterson) {
    $filterresult = New-Object PSObject
    $filterresult | Add-Member -type NoteProperty -Name appliedfilterson -Value $appliedfilterson
    return $filterresult
}

#
# Test
function New-Test($name, $id, $testtype, $estimatedruntime, $requiresspecialconfiguration, $requiressupplementalcontent, $scheduleoptions, $status, $executionstate) {
    $test = New-Object PSObject
    $test | Add-Member -type NoteProperty -Name name -Value $name
    $test | Add-Member -type NoteProperty -Name id -Value $id
    $test | Add-Member -type NoteProperty -Name testtype -Value $testtype
    $test | Add-Member -type NoteProperty -Name estimatedruntime -Value $estimatedruntime
    $test | Add-Member -type NoteProperty -Name requiresspecialconfiguration -Value $requiresspecialconfiguration
    $test | Add-Member -type NoteProperty -Name requiressupplementalcontent -Value $requiressupplementalcontent
    $test | Add-Member -type NoteProperty -Name scheduleoptions -Value $scheduleoptions
    $test | Add-Member -type NoteProperty -Name status -Value $status
    $test | Add-Member -type NoteProperty -Name executionstate -Value $executionstate
    return $test
}

#
# ProductInstanceTarget
function New-ProductInstanceTarget($name, $key, $machine) {
    $productinstancetarget = New-Object PSObject
    $productinstancetarget | Add-Member -type NoteProperty -Name name -Value $name
    $productinstancetarget | Add-Member -type NoteProperty -Name key -Value $key
    $productinstancetarget | Add-Member -type NoteProperty -Name machine -Value $machine
    return $productinstancetarget
}

#
# ProductInstance
function New-ProductInstance($name, $osplatform, $targetedpool, $targets) {
    $productinstance = New-Object PSObject
    $productinstance | Add-Member -type NoteProperty -Name name -Value $name
    $productinstance | Add-Member -type NoteProperty -Name osplatform -Value $osplatform
    $productinstance | Add-Member -type NoteProperty -Name targetedpool -Value $targetedpool
    $productinstance | Add-Member -type NoteProperty -Name targets -Value $targets
    return $productinstance
}

#
# Project
function New-Project($name, $creationtime, $modifiedtime, $status, $productinstances) {
    $project = New-Object PSObject
    $project | Add-Member -type NoteProperty -Name name -Value $name
    $project | Add-Member -type NoteProperty -Name creationtime -Value $creationtime
    $project | Add-Member -type NoteProperty -Name modifiedtime -Value $modifiedtime
    $project | Add-Member -type NoteProperty -Name status -Value $status
    $project | Add-Member -type NoteProperty -Name productinstances -Value $productinstances
    return $project
}

#
# Target
function New-Target($name, $key, $type) {
    $target = New-Object PSObject
    $target | Add-Member -type NoteProperty -Name name -Value $name
    $target | Add-Member -type NoteProperty -Name key -Value $key
    $target | Add-Member -type NoteProperty -Name type -value $type
    return $target
}

#
# Machine
function New-Machine($name, $state, $lastheartbeat) {
    $machine = New-Object PSObject
    $machine | Add-Member -type NoteProperty -Name name -Value $name
    $machine | Add-Member -type NoteProperty -Name state -Value $state
    $machine | Add-Member -type NoteProperty -Name lastheartbeat -Value $lastheartbeat
    return $machine
}

#
# Pool
function New-Pool($name, $machines) {
    $pool = New-Object PSObject
    $pool | Add-Member -type NoteProperty -Name name -Value $name
    $pool | Add-Member -type NoteProperty -Name machines -Value $machines
    return $pool
}

#
# ActionResult
function New-ActionResult($content, $exception = $nil) {
    $actionresult = New-Object PSObject
    if ([String]::IsNullOrEmpty($exception)) {
        $actionresult | Add-Member -type NoteProperty -Name result -Value "Success"
        if (-Not [String]::IsNullOrEmpty($content)) {
            $jsoncontent = (ConvertFrom-Json $content)
            if ($jsoncontent -is [System.Object[]]) {
                $actionresult | Add-Member -type NoteProperty -Name content -Value $jsoncontent.SyncRoot
            } else {
                $actionresult | Add-Member -type NoteProperty -Name content -Value $jsoncontent
            }
        }
    } else {
        $actionresult | Add-Member -type NoteProperty -Name result -Value "Failure"
        if ([String]::IsNullOrEmpty($exception.InnerException)) {
            $actionresult | Add-Member -type NoteProperty -Name message -Value $exception.Message
        } else {
            $actionresult | Add-Member -type NoteProperty -Name message -Value $exception.InnerException.Message
        }
    }
    return $actionresult
}

# ------------------------------------------------------------ #
# Functions, one for each action the script is able to perform #
# ------------------------------------------------------------ #
# ListPools
function listpools {
    [CmdletBinding()]
    param([Switch]$help)

    function Usage {
        Write-Output "listpools:"
        Write-Output ""
        Write-Output "A script that lists the pools info."
        Write-Output "and last heart beat."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "listpools [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output " help = Shows this message."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if (-Not $json) {
        foreach ($Pool in $RootPool.GetChildPools()) {
            $Machines = $Pool.GetMachines()

            if ($Machines.Count -lt 1) {
                Write-Output "{""pool"": ""$($Pool.Name)""}"
            } else {
                foreach ($Machine in $Machines) {
                    Write-Output "{""pool"": ""$($Pool.Name)"", ""machine"": {""name"": ""$($Machine.Name)"", ""state"": ""$($Machine.Status)"", ""last_heart_beat"": ""$($Machine.LastHeartBeat)""}}"
                }
            }
        }
    } else {
        $poolslist = New-Object System.Collections.ArrayList
        foreach ($Pool in $RootPool.GetChildPools()) {
            $machineslist = New-Object System.Collections.ArrayList
            $Machines = $Pool.GetMachines()
            foreach ($Machine in $Machines) {
                $machineslist.Add((New-Machine $Machine.Name $Machine.Status.ToString() $Machine.LastHeartBeat.ToString())) | Out-Null
            }
            $poolslist.Add((New-Pool $Pool.Name $machineslist)) | Out-Null
        }
        ConvertTo-Json @($poolslist) -Depth 3 -Compress
    }
}
#
# GetPool
function getpool {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$pool)

    function Usage {
        Write-Output "getpool:"
        Write-Output ""
        Write-Output "A script that get the pools info."
        Write-Output "and last heart beat."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "getpool <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output " help = Shows this message."
        Write-Output " poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not $json) {
        foreach ($Pool in $RootPool.GetChildPools()) {
            $Machines = $Pool.GetMachines()
            if ($Pool.Name -eq $pool) {
                foreach ($Machine in $Machines) {
                    Write-Output "{""machine_name"": ""$($Machine.Name)"", ""machine_state"": ""$($Machine.Status)"", ""machine_last_heart_beat"": ""$($Machine.LastHeartBeat)""}"
                }
            }
        }
    } else {
        $poolslist = New-Object System.Collections.ArrayList
        foreach ($Pool in $RootPool.GetChildPools()) {
            $machineslist = New-Object System.Collections.ArrayList
            $Machines = $Pool.GetMachines()
            foreach ($Machine in $Machines) {
                $machineslist.Add((New-Machine $Machine.Name $Machine.Status.ToString() $Machine.LastHeartBeat.ToString())) | Out-Null
            }
            $poolslist.Add((New-Pool $Pool.Name $machineslist)) | Out-Null
        }
        ConvertTo-Json @($poolslist) -Depth 3 -Compress
    }
}
#
# GetDefaultPool
function getdefaultpool {
    [CmdletBinding()]
    param([Switch]$help)

    function Usage {
        Write-Output "getdefaultpool:"
        Write-Output ""
        Write-Output "A script that get the default pool info."
        Write-Output "and last heart beat."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "getdefaultpool [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output " help = Shows this message."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }
    $DefaultPool = $RootPool.DefaultPool
    $Machines = $DefaultPool.GetMachines()
    foreach ($Machine in $Machines) {
        Write-Output "{""machine_name"": ""$($Machine.Name)"", ""machine_state"": ""$($Machine.Status)"", ""machine_last_heart_beat"": ""$($Machine.LastHeartBeat)""}"
    }
}
#
# CreatePool
function createpool {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$pool)

    function Usage {
        Write-Output "createpool:"
        Write-Output ""
        Write-Output "A script that creates a pool."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "createpool <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output " poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not $json) { Write-Output "Creating pool $pool in Root pool." }
    $RootPool.CreateChildPool($pool) | Out-Null
}
#
# DeletePool
function deletepool {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$pool)

    function Usage {
        Write-Output "deletepool:"
        Write-Output ""
        Write-Output "A script that deletes a pool."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "deletepool <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output " poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Provided pool's name is not valid, aborting..."}

    if (-Not $json) { Write-Output "Deleting pool $pool in Root pool." }
    $RootPool.DeleteChildPool($WntdPool)
}
#
# MoveMachineFromDefaultPool
function movemachinefromdefaultpool {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$machine, [Parameter(Position=2)][String]$to)

    function Usage {
        Write-Output "movemachinefromdefaultpool:"
        Write-Output ""
        Write-Output "A script that moves a machine from default pool to another."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "movemachine <machine> <topool> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output "  machine = The name of the machine as registered with the HLK controller."
        Write-Output ""
        Write-Output "   topool = The name of the destination pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($to)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a destination pool's name."
            Usage; return
        } else {
            throw "Please provide a destination pool's name."
        }
    }

    $WntdFromPool = $RootPool.DefaultPool
    if (-Not ($WntdToPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $to })) { throw "Provided destination pool's name is not valid, aborting..." }
    if (-Not ($WntdMachine = $WntdFromPool.GetMachines() | Where-Object { $_.Name -eq $machine })) { throw "Provided machines's name is not valid, aborting..." }

    if (-Not $json) { Write-Output "Moving machine $($WntdMachine.Name) from $($WntdFromPool.Name) to $($WntdToPool.Name) pool." }
    $WntdFromPool.MoveMachineTo($WntdMachine, $WntdToPool)
}
#
# MoveMachine
function movemachine {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$machine, [Parameter(Position=2)][String]$from, [Parameter(Position=3)][String]$to)

    function Usage {
        Write-Output "movemachine:"
        Write-Output ""
        Write-Output "A script that moves a machine from one pool to another."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "movemachine <machine> <frompool> <topool> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output "  machine = The name of the machine as registered with the HLK controller."
        Write-Output ""
        Write-Output " frompool = The name of the source pool."
        Write-Output ""
        Write-Output "   topool = The name of the destination pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($from)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a source pool's name."
            Usage; return
        } else {
            throw "Please provide a source pool's name."
        }
    }
    if ([String]::IsNullOrEmpty($to)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a destination pool's name."
            Usage; return
        } else {
            throw "Please provide a destination pool's name."
        }
    }

    if (-Not ($WntdFromPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $from })) { throw "Provided source pool's name is not valid, aborting..." }
    if (-Not ($WntdToPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $to })) { throw "Provided destination pool's name is not valid, aborting..." }
    if (-Not ($WntdMachine = $WntdFromPool.GetMachines() | Where-Object { $_.Name -eq $machine })) { throw "Provided machines's name is not valid, aborting..." }

    if (-Not $json) { Write-Output "Moving machine $($WntdMachine.Name) from $($WntdFromPool.Name) to $($WntdToPool.Name) pool." }
    $WntdFromPool.MoveMachineTo($WntdMachine, $WntdToPool)
}
#
# SetMachineState
function setmachinestate {
    [CmdletBinding()]
    param([Switch]$help, [Int]$timeout = -1, [Parameter(Position=1)][String]$machine, [Parameter(Position=2)][String]$pool, [Parameter(Position=3)][String]$state)

    function Usage {
        Write-Output "setmachinestate:"
        Write-Output ""
        Write-Output "A script that sets the state of a machine to Ready or NotReady."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "setmachinestate <machine> <poolname> <state> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output "  machine = The name of the machine as registered with the HLK controller."
        Write-Output ""
        Write-Output " poolname = The name of the pool."
        Write-Output ""
        Write-Output "    state = The state, Ready or NotReady."
        Write-Output ""
        Write-Output "  timeout = The operation's timeout in seconds, disabled by default."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }
    if ([String]::IsNullOrEmpty($state)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a state."
            Usage; return
        } else {
            throw "Please provide a state."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Provided pool's name is not valid, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines() | Where-Object { $_.Name -eq $machine })) { throw "Provided machines's name is not valid, aborting..." }
    if (-Not ($timeout -eq -1)) { $timeout = $timeout * 1000 }

    if (-Not $json) { Write-Output "Setting machine $($WntdMachine.Name) to $state state..." }
    switch ($state) {
        "Ready" {
            if (-Not $WntdMachine.SetMachineStatus([Microsoft.Windows.Kits.Hardware.ObjectModel.MachineStatus]::Ready, $timeout)) { throw "Unable to change machine state, timed out." }
        }
        "NotReady" {
            if (-Not $WntdMachine.SetMachineStatus([Microsoft.Windows.Kits.Hardware.ObjectModel.MachineStatus]::NotReady, $timeout))  { throw "Unable to change machine state, timed out." }
        }
        default {
            throw "Provided desired machines's sate is not valid, aborting..."
        }
    }
}
#
# DeleteMachine
function deletemachine {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$machine, [Parameter(Position=2)][String]$pool)

    function Usage {
        Write-Output "deletemachine:"
        Write-Output ""
        Write-Output "A script that deletes a machine."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "deletemachine <machine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "     help = Shows this message."
        Write-Output ""
        Write-Output "  machine = The name of the machine as registered with the HLK controller."
        Write-Output ""
        Write-Output " poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Provided pool's name is not valid, aborting..." }

    if (-Not $json) { Write-Output "Deleting machine $machine..." }
    $WntdPool.DeleteMachine($machine)
}
#
# ListMachineTargets
function listmachinetargets {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$machine, [Parameter(Position=2)][String]$pool)

    function Usage {
        Write-Output "listmachinetargets:"
        Write-Output ""
        Write-Output "A script that lists the target devices of a machine that are available to be tested."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "listmachientargets <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "   poolname  = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }

    if (-Not $json) {
        foreach ($TestTarget in $WntdMachine.GetTestTargets()) {
            Write-Output "$($TestTarget.Name),$($TestTarget.Key),$($TestTarget.TargetType)"
        }
    } else {
        $targetslist = New-Object System.Collections.ArrayList
        foreach ($TestTarget in $WntdMachine.GetTestTargets()) {
            $targetslist.Add((New-Target $TestTarget.Name $TestTarget.Key $TestTarget.TargetType)) | Out-Null
        }
        ConvertTo-Json @($targetslist) -Compress
    }
}
#
# ListProjects
function listprojects {
    [CmdletBinding()]
    param([Switch]$help)

    function Usage {
        Write-Output "listprojects:"
        Write-Output ""
        Write-Output "A script that lists the projects info."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "listprojects [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "      help = Shows this message."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if (-Not $json) {
        foreach ($ProjectName in $Manager.GetProjectNames()) {
            $Project = $Manager.GetProject($ProjectName)
             Write-Output "{""project_name"": ""$($Project.Name)"", ""creation_time"": ""$($Project.CreationTime)"", ""modified_time"": ""$($Project.ModifiedTime)"", ""status"": ""$($Project.Info.Status)""}"
        }
    } else {
        $projectslist = New-Object System.Collections.ArrayList
        foreach ($ProjectName in $Manager.GetProjectNames()) {
            $Project = $Manager.GetProject($ProjectName)
            $ProductInstances = $Project.GetProductInstances()
            $productinstanceslist = New-Object System.Collections.ArrayList
            foreach ($Pi in $ProductInstances) {
                $targetslist = New-Object System.Collections.ArrayList
                foreach ($Target in $Pi.GetTargets()) {
                    $targetslist.Add((New-ProductInstanceTarget $Target.Name $Target.Key $Target.Machine.Name)) | Out-Null
                }
                $productinstanceslist.Add((New-ProductInstance $Pi.Name $Pi.OSPlatform.Name $Pi.MachinePool.Name $targetslist)) | Out-Null
            }
            $projectslist.Add((New-Project $Project.Name $Project.CreationTime.ToString() $Project.ModifiedTime.ToString() $Project.Info.Status.ToString() $productinstanceslist)) | Out-Null
        }
        ConvertTo-Json @($projectslist) -Depth 5 -Compress
    }
}
#
# CreateProject
function createproject {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$project)

    function Usage {
        Write-Output "createproject:"
        Write-Output ""
        Write-Output "A script that creates a project."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "createproject <projectname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "               help = Shows this message."
        Write-Output ""
        Write-Output "        projectname = The name of the project."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }

    if ($Manager.GetProjectNames().Contains($project)) {
        throw "A project with the name $($project) already exists, aborting..."
    } else {
        if (-Not $json) { Write-Output "Creating a new project named $($project)." }
        $WntdProject = $Manager.CreateProject($project)
    }
}
#
# DeleteProject
function deleteproject {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$project)

    function Usage {
        Write-Output "deleteproject:"
        Write-Output ""
        Write-Output "A script that deletes a project."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "deleteproject <projectname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "               help = Shows this message."
        Write-Output ""
        Write-Output "        projectname = The name of the project."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }

    if (-Not $json) { Write-Output "Deleting project $project..." }
    $Manager.DeleteProject($project)
}
#
# CreateProjectTarget
function createprojecttarget {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$target, [Parameter(Position=2)][String]$project, [Parameter(Position=3)][String]$machine, [Parameter(Position=4)][String]$pool)

    function Usage {
        Write-Output "createprojecttarget:"
        Write-Output ""
        Write-Output "A script that creates a project's target."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "createprojecttarget <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    $CreatedPI = $false
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) {
        if (-Not $WntdProject.CanCreateProductInstance($WntdMachine.OSPlatform.Description, $WntdPool, $WntdMachine.OSPlatform)) {
            throw "Can't create the project's product instance, it may be due to the project having another product instance that matches the wanted machine's pool or platform."
        } else {
            $WntdPI = $WntdProject.CreateProductInstance($WntdMachine.OSPlatform.Description, $WntdPool, $WntdMachine.OSPlatform)
            $CreatedPI = $true
        }
    }

    try {
        $WntdPITargets = $WntdPI.GetTargets()
        if (($WntdTarget.TargetType -eq "System") -and ($WntdPITargets | Where-Object { $_.TargetType -ne "System" })) { throw "The project already has non-system targets, can't mix system and non-system targets, aborting..." }
        if (($WntdTarget.TargetType -ne "System") -and ($WntdPITargets | Where-Object { $_.TargetType -eq "System" })) { throw "The project already has system targets, can't mix system and non-system targets, aborting..." }
        else {
            $WntdtoTarget = New-Object System.Collections.ArrayList
            if ($WntdTarget.TargetType -eq "TargetCollection") {
                foreach ($toTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
                    if ($toTarget.Machine.Equals($WntdMachine)){
                        $WntdtoTarget.Add($toTarget) | Out-Null
                    }
                }
            } else {
                $WntdtoTarget.Add($WntdTarget) | Out-Null
            }
            if ($WntdtoTarget.Count -lt 1) { throw "No targets to create were found, aborting..." }
            foreach ($toTarget in $WntdtoTarget) {
                if ($WntdPITargets | Where-Object { ($_.Key -eq $toTarget.Key) -and $_.Machine.Equals($toTarget.Machine) }) { continue }

                switch ($toTarget.TargetType) {
                    "Filter" { [String[]]$HardwareIds = $toTarget.Key }
                    "System" { [String[]]$HardwareIds = "[SYSTEM]" }
                    default { [String[]]$HardwareIds = $toTarget.HardwareId }
                }
                if (-Not ($WntdDeviceFamily = $Manager.GetDeviceFamilies() | Where-Object { $_.Name -eq $HardwareIds[0] })) {
                    $WntdDeviceFamily = $Manager.CreateDeviceFamily($HardwareIds[0], $HardwareIds)
                }

                if ($WntdPITargets | Where-Object { ($_.Key -eq $toTarget.Key) }) {
                    $WntdTargetFamily = ($WntdPITargets | Where-Object { ($_.Key -eq $toTarget.Key) })[0].TargetFamily
                } else {
                    $WntdTargetFamily = $WntdPI.CreateTargetFamily($WntdDeviceFamily)
                }

                if (-Not $json) { Write-Output "Creating a new project's target from $($toTarget.Name)." }

                $WntdTargetFamily.CreateTarget($toTarget) | Out-Null
            }
        }
    } catch {
        if ($CreatedPI) { $WntdProject.DeleteProductInstance($WntdMachine.OSPlatform.Description) }
        throw
    }
}
#
# DeleteProjectTarget
function deleteprojecttarget {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$target, [Parameter(Position=2)][String]$project, [Parameter(Position=3)][String]$machine, [Parameter(Position=4)][String]$pool)

    function Usage {
        Write-Output "deleteprojecttarget:"
        Write-Output ""
        Write-Output "A script that deletes a project's target."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "deleteprojecttarget <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdtoDelete = New-Object System.Collections.ArrayList
    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($toDelete in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $toDelete.Key) -and ($_.Machine.Equals($toDelete.Machine)) } | foreach { $WntdtoDelete.Add($_) | Out-Null }
        }
    } else {
        $WntdtoDelete.Add($WntdTarget) | Out-Null
    }
    foreach ($toDelete in $WntdtoDelete) {
        if (-Not $json) { Write-Output "Deleting a new project's target from $($toDelete.Name)." }
        $WntdPI.DeleteTarget($toDelete.Key, $toDelete.Machine)
    }

    if ($WntdPI.GetTargets().Count -lt 1) { $WntdProject.DeleteProductInstance($WntdPI.Name) }
}

function parsescheduleoptions {
    [CmdletBinding()]
    param([Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption] $scheduleoptions)

    $ParsedScheduleOptions = New-Object System.Collections.ArrayList

    if (($scheduleoptions -band [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::RequiresMultipleMachines) -eq [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::RequiresMultipleMachines) { $ParsedScheduleOptions.Add([Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::RequiresMultipleMachines.ToString()) | Out-Null }
    if (($scheduleoptions -band [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAllTargets) -eq [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAllTargets) { $ParsedScheduleOptions.Add([Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAllTargets.ToString()) | Out-Null }
    if (($scheduleoptions -band [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAnyTarget) -eq [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAnyTarget) { $ParsedScheduleOptions.Add([Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ScheduleOnAnyTarget.ToString()) | Out-Null }
    if (($scheduleoptions -band [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ConsolidateScheduleAcrossTargets) -eq [Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ConsolidateScheduleAcrossTargets) { $ParsedScheduleOptions.Add([Microsoft.Windows.Kits.Hardware.ObjectModel.DistributionOption]::ConsolidateScheduleAcrossTargets.ToString()) | Out-Null }

    return ,$ParsedScheduleOptions
}

#
# ListTests
function listtests {
    [CmdletBinding()]
    param([Switch]$help, [Switch]$manual, [Switch]$auto, [Switch]$failed, [Switch]$inqueue, [Switch]$notrun, [Switch]$passed, [Switch]$running, [String]$playlist, [Parameter(Position=1)][String]$target, [Parameter(Position=2)][String]$project, [Parameter(Position=3)][String]$machine, [Parameter(Position=4)][String]$pool)

    function Usage {
        Write-Output "listtests:"
        Write-Output ""
        Write-Output "A script that lists a project target's tests."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "listtests <targetkey> <projectname> <testmachine> <poolname> [-manual]"
        Write-Output "                           [-auto] [-failed] [-inqueue] [-notrun] [-passed] [-running]"
        Write-Output "                               [-playlist] [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "    playlist = List only the tests that matches the given playlist, (by path)."
        Write-Output ""
        Write-Output "      manual = List only the manual run tests."
        Write-Output ""
        Write-Output "        auto = List only the auto run tests."
        Write-Output ""
        Write-Output "      failed = List only the failed tests."
        Write-Output ""
        Write-Output "     inqueue = List only the tests that are in the run queue."
        Write-Output ""
        Write-Output "      notrun = List only the tests that haven't been run."
        Write-Output ""
        Write-Output "      passed = List only the passed tests."
        Write-Output ""
        Write-Output "     running = List only the running tests."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }
    if ((-Not [String]::IsNullOrEmpty($playlist)) -and $Studio -ne "hlk") {
        if (-Not $json) {
            Write-Output "WARNING: Playlist provided but HLK doesn't support playlists, aborting..."
            Usage; return
        } else {
            throw "Playlist provided but HLK doesn't support playlists, aborting..."
        }
    }

    if (-Not ($manual -or $auto)) {
        $manual = $true
        $auto = $true
    }
    if (-Not ($notrun -or $failed -or $passed -or $running -or $inqueue)) {
        $notrun = $true
        $failed = $true
        $passed = $true
        $running = $true
        $inqueue = $true
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList

    if (-Not [String]::IsNullOrEmpty($playlist)) {
        $PlaylistManager = New-Object Microsoft.Windows.Kits.Hardware.ObjectModel.PlaylistManager $WntdProject
        $WntdPlaylist = [Microsoft.Windows.Kits.Hardware.ObjectModel.PlaylistManager]::DeserializePlaylist($playlist)
        foreach ($tTest in $PlaylistManager.GetTestsFromProjectThatMatchPlaylist($WntdPlaylist)) {
            if ($tTest.GetTestTargets() | Where-Object { $WntdPITargets.Contains($_) }) { $WntdTests.Add($tTest) | Out-Null }
        }
    } else {
        $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }
    }

    if (-Not $json) {
        foreach ($tTest in $WntdTests) {
            if (-Not (($manual -and ($tTest.TestType -eq "Manual")) -or ($auto -and ($tTest.TestType -eq "Automated")))) {
                continue
            } elseif (-Not (($notrun -and ($tTest.Status -eq "NotRun")) -or ($failed -and ($tTest.Status -eq "Failed")) -or ($passed -and ($tTest.Status -eq "Passed")) -or ($running -and ($tTest.ExecutionState -eq "Running")) -or ($inqueue -and ($tTest.ExecutionState -eq "InQueue")))) {
                continue
            }
            Write-Output "{""test_name"": ""$($tTest.Name)"", ""test_id"": ""$($tTest.Id)"", ""test_type"": ""$($tTest.TestType)"", ""estimated_runtime"": ""$($tTest.EstimatedRuntime)"", ""requires_special_configuration"": ""$($tTest.RequiresSpecialConfiguration)"", ""requires_supplemental_content"": ""$($tTest.RequiresSupplementalContent)"", ""test_status"": ""$($tTest.Status)"", ""execution_state"": ""$($tTest.ExecutionState)""}"
        }
    } else {
        $testslist = New-Object System.Collections.ArrayList
        foreach ($tTest in $WntdTests) {
            if (-Not (($manual -and ($tTest.TestType -eq "Manual")) -or ($auto -and ($tTest.TestType -eq "Automated")))) {
                continue
            } elseif (-Not (($notrun -and ($tTest.Status -eq "NotRun")) -or ($failed -and ($tTest.Status -eq "Failed")) -or ($passed -and ($tTest.Status -eq "Passed")) -or ($running -and ($tTest.ExecutionState -eq "Running")) -or ($inqueue -and ($tTest.ExecutionState -eq "InQueue")))) {
                continue
            }
            $testslist.Add((New-Test $tTest.Name $tTest.Id $tTest.TestType.ToString() $tTest.EstimatedRuntime.ToString() $tTest.RequiresSpecialConfiguration.ToString() $tTest.RequiresSupplementalContent.ToString() (parsescheduleoptions($tTest.ScheduleOptions)) $tTest.Status.ToString() $tTest.ExecutionState.ToString())) | Out-Null
        }
        ConvertTo-Json @($testslist) -Compress
    }
}
#
# GetTestInfo
function gettestinfo {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$test, [Parameter(Position=2)][String]$target, [Parameter(Position=3)][String]$project, [Parameter(Position=4)][String]$machine, [Parameter(Position=5)][String]$pool)

    function Usage {
        Write-Output "gettestinfo:"
        Write-Output ""
        Write-Output "A script that gets a project target's test info."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "gettestinfo <testid> <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "      testid = The id of the test, use listtests action to get it."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($test)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test's id."
            Usage; return
        } else {
            throw "Please provide a test's id."
        }
    }
    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList
    $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }

    if (-Not ($WntdTest = $WntdTests | Where-Object { $_.Id -eq $test })) { throw "Didn't find a test with the id given." }

    if (-Not $json) {
        Write-Output "{""test_name"": ""$($WntdTest.Name)"", ""test_id"": ""$($WntdTest.Id)"", ""test_type"": ""$($WntdTest.TestType)"", ""estimated_runtime"": ""$($WntdTest.EstimatedRuntime)"", ""requires_special_configuration"": ""$($WntdTest.RequiresSpecialConfiguration)"", ""requires_supplemental_content"": ""$($WntdTest.RequiresSupplementalContent)"", ""test_status"": ""$($WntdTest.Status)"", ""execution_state"": ""$($WntdTest.ExecutionState)""}"
    } else {
        @((New-Test $WntdTest.Name $WntdTest.Id $WntdTest.TestType.ToString() $WntdTest.EstimatedRuntime.ToString() $WntdTest.RequiresSpecialConfiguration.ToString() $WntdTest.RequiresSupplementalContent.ToString() (parsescheduleoptions($tTest.ScheduleOptions)) $WntdTest.Status.ToString() $WntdTest.ExecutionState.ToString())) | ConvertTo-Json -Compress
    }
}
#
# QueueTest
function queuetest {
    [CmdletBinding()]
    param([Switch]$help, [String]$sup, [String]$IPv6, [Parameter(Position=1)][String]$test, [Parameter(Position=2)][String]$target, [Parameter(Position=3)][String]$project, [Parameter(Position=4)][String]$machine, [Parameter(Position=5)][String]$pool)

    function Usage {
        Write-Output "queuetest:"
        Write-Output ""
        Write-Output "A script that queues a test, use listtestresults action to get the results."
        Write-Output "(if the test needs two machines to run use -sup flag)"
        Write-Output "(if the test needs the IPv6 address of the support machine use -IPv6 flag)"
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "queuetest <testid> <targetkey> <projectname> <testmachine> <poolname> [-sup <name>]"
        Write-Output "              [-IPv6 <address>] [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "      testid = The id of the test, use listtests action to get it."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "        IPv6 = The support machines's ""SupportDevice0"" IPv6 address."
        Write-Output ""
        Write-Output "         sup = The support machine's name as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($test)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test's id."
            Usage; return
        } else {
            throw "Please provide a test's id."
        }
    }
    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList
    $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }

    if (-Not ($WntdTest = $WntdTests | Where-Object { $_.Id -eq $test })) { throw "Didn't find a test with the id given." }

    if (-Not $json) { Write-Output "Queueing test $($WntdTest.Name)..." }

    if (-Not [String]::IsNullOrEmpty($IPv6)) {
        $WntdTest.SetParameter("WDTFREMOTESYSTEM", $IPv6, [Microsoft.Windows.Kits.Hardware.ObjectModel.ParameterSetAsDefault]::DoNotSetAsDefault) | Out-Null
    }

    if (-Not [String]::IsNullOrEmpty($sup)) {
        if (-Not ($WntdSMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $sup })) { throw "The support machine was not found, aborting..." }
        $MachineSet = $WntdTest.GetMachineRole()
        $RoleMachines = New-Object System.Collections.ArrayList
        foreach ($Role in $MachineSet.Roles) {
            $RoleMachines.AddRange($Role.GetMachines())
            $RoleMachines | foreach { $Role.RemoveMachine($_) }
            $RoleMachines.Clear()
            if ($Role.Name -eq "Client") {
                $Role.AddMachine($WntdMachine)
            }
            if ($Role.Name -eq "Support") {
                $Role.AddMachine($WntdSMachine)
            }
        }
        $MachineSet.ApplyMachineDimensions()
        $WntdTest.QueueTest($MachineSet) | Out-Null
    } else {
        $WntdTest.QueueTest() | Out-Null
    }
}
#
# ApplyProjectFilters
function applyprojectfilters {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$project)

    function Usage {
        Write-Output "applyprojectfilters:"
        Write-Output ""
        Write-Output "A script that applies the filters on a project's test results."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "applyprojectfilters <projectname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }

    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }

    if (-Not $json) { Write-Output "Applying filters on project $($WntdProject.Name)..." }

    $WntdFilterEngine = New-Object Microsoft.Windows.Kits.Hardware.FilterEngine.DatabaseFilterEngine $Manager
    $WntdFilterResultDictionary = $WntdFilterEngine.Filter($WntdProject)
    $Count = 0
    foreach ($tFilterResultCollection in $WntdFilterResultDictionary.Values) {
        $Count += $tFilterResultCollection.Count
    }

    if (-Not $json) {
        Write-Output "Applied filters on $Count tasks."
    } else {
        @(New-FilterResult $Count) | ConvertTo-Json -Compress
    }
}
#
# ApplyTestResultsFilters
function applytestresultfilters {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$result, [Parameter(Position=2)][String]$test, [Parameter(Position=3)][String]$target, [Parameter(Position=4)][String]$project, [Parameter(Position=5)][String]$machine, [Parameter(Position=6)][String]$pool)

    function Usage {
        Write-Output "applytestresultfilters:"
        Write-Output ""
        Write-Output "A script that applies filters on a test result."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "applytestresultfilters <resultindex> <testid> <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output " resultindex = The index of the test result, use listtestresults action to get it."
        Write-Output ""
        Write-Output "      testid = The id of the test, use listtests action to get it."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($result)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test result's index."
            Usage; return
        } else {
            throw "Please provide a test result's index."
        }
    }
    if ([String]::IsNullOrEmpty($test)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test's id."
            Usage; return
        } else {
            throw "Please provide a test's id."
        }
    }
    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList
    $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }

    if (-Not ($WntdTest = $WntdTests | Where-Object { $_.Id -eq $test })) { throw "Didn't find a test with the id given." }

    if (-Not ($WntdTest.GetTestResults().Count -ge 1)) { throw "The test hasen't been queued, can't find test results." } else { $WntdResult = $WntdTest.GetTestResults()[$result] }

    if (-Not $json) { Write-Output "Applying filters on test result..." }

    $WntdFilterEngine = New-Object Microsoft.Windows.Kits.Hardware.FilterEngine.DatabaseFilterEngine $Manager
    $WntdFilterResultCollection = $WntdFilterEngine.Filter($WntdResult)

    if (-Not $json) {
        Write-Output "Applied filters on $($WntdFilterResultCollection.Count) tasks."
    } else {
        @(New-FilterResult $WntdFilterResultCollection.Count) | ConvertTo-Json -Compress
    }
}
#
# ListTestResults
function listtestresults {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$test, [Parameter(Position=2)][String]$target, [Parameter(Position=3)][String]$project, [Parameter(Position=4)][String]$machine, [Parameter(Position=5)][String]$pool)

    function Usage {
        Write-Output "listtestresults:"
        Write-Output ""
        Write-Output "A script that lists all of the test results and lists them and their info."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "listtestresults <testid> <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output "      testid = The id of the test, use listtests action to get it."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($test)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test's id."
            Usage; return
        } else {
            throw "Please provide a test's id."
        }
    }
    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList
    $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }

    if (-Not ($WntdTest = $WntdTests | Where-Object { $_.Id -eq $test })) { throw "Didn't find a test with the id given." }

    if (-Not ($WntdTest.GetTestResults().Count -ge 1)) { throw "The test hasen't been queued, can't find test results." } else { $WntdResults = $WntdTest.GetTestResults() }

    if (-Not $json) {
        Write-Output ""
        Write-Output "The requested project test's results:"
        Write-Output ""

        foreach ($tTestResult in $WntdResults) {
            $tTestResult.Refresh()
            Write-Output "============================================="
            Write-Output "Test result index : $($WntdResults.IndexOf($tTestResult))"
            Write-Output ""
            Write-Output "    Test name           : $($tTestResult.Test.Name)"
            Write-Output "    Completion time     : $($tTestResult.CompletionTime)"
            Write-Output "    Schedule time       : $($tTestResult.ScheduleTime)"
            Write-Output "    Start time          : $($tTestResult.StartTime)"
            Write-Output "    Status              : $($tTestResult.Status)"
            Write-Output "    Are filters applied : $($tTestResult.AreFiltersApplied)"
            Write-Output "    Target name         : $($tTestResult.Target.Name)"
            Write-Output "    Tasks               :"
            foreach ($tTask in $tTestResult.GetTasks()) {
                Write-Output "        $($tTask.Name):"
                Write-Output "            Stage              : $($tTask.Stage)"
                Write-Output "            Status             : $($tTask.Status)"
                if (-Not [String]::IsNullOrEmpty($tTask.TaskErrorMessage)) {
                    Write-Output "            Task error message : Test name: $($tTestResult.Test.Name), Task name: $($tTask.Name), $($tTask.TaskErrorMessage)"
                }
                Write-Output "            Task type          : $($tTask.TaskType)"
                if ($tTask.GetChildTasks()) {
                    Write-Output "            Sub tasks          :"

                    foreach ($subtTask in $tTask.GetChildTasks()) {
                        Write-Output "                $($subtTask.Name):"
                        Write-Output "                    Stage              : $($subtTask.Stage)"
                        Write-Output "                    Status             : $($subtTask.Status)"
                        if (-Not [String]::IsNullOrEmpty($subtTask.TaskErrorMessage)) {
                            Write-Output "                    Task error message : Test name: $($tTestResult.Test.Name), Task name: $($tTask.Name), Sub Task name: $($subtTask.Name), $($subtTask.TaskErrorMessage)"
                        }
                        Write-Output "                    Task type          : $($subtTask.TaskType)"
                        if (-Not ($subtTask -eq $tTask.GetChildTasks()[-1])) {
                            Write-Output ""
                        }
                    }
                }
                Write-Output ""
            }
            Write-Output "============================================="
        }
    } else {
        $testresultlist = New-Object System.Collections.ArrayList

        foreach ($tTestResult in $WntdResults) {
            $tTestResult.Refresh()
            $taskslist = New-Object System.Collections.ArrayList

            foreach ($tTask in $tTestResult.GetTasks()) {
                $subtaskslist = New-Object System.Collections.ArrayList

                if ($tTask.GetChildTasks()) {
                    foreach ($subtTask in $tTask.GetChildTasks()) {
                        $subtasktype = (New-Task $subtTask.Name $subtTask.Stage $subtTask.Status.ToString() $subtTask.TaskErrorMessage $subtTask.TaskType (New-Object System.Collections.ArrayList))
                        $subtaskslist.Add($subtasktype) | Out-Null
                    }
                }
                $tasktype = (New-Task $tTask.Name $tTask.Stage $tTask.Status.ToString() $tTask.TaskErrorMessage $tTask.TaskType $subtaskslist)
                $taskslist.Add($tasktype) | Out-Null
            }

            $testresultlist.Add((New-TestResult $tTestResult.Test.Name $tTestResult.CompletionTime.ToString() $tTestResult.ScheduleTime.ToString() $tTestResult.StartTime.ToString() $tTestResult.Status.ToString() $tTestResult.AreFiltersApplied.ToString() $tTestResult.Target.Name $taskslist)) | Out-Null
        }

        ConvertTo-Json @($testresultlist) -Depth $MaxJsonDepth -Compress
    }
}
#
# ZipTestResultLogs
function ziptestresultlogs {
    [CmdletBinding()]
    param([Switch]$help, [Parameter(Position=1)][String]$result, [Parameter(Position=2)][String]$test, [Parameter(Position=3)][String]$target, [Parameter(Position=4)][String]$project, [Parameter(Position=5)][String]$machine, [Parameter(Position=6)][String]$pool)

    function Usage {
        Write-Output "ziptestresultlogs:"
        Write-Output ""
        Write-Output "A script that zips a test result's logs to the returned zip file path."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "ziptestresultlogs <resultindex> <testid> <targetkey> <projectname> <testmachine> <poolname> [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output " resultindex = The index of the test result, use listtestresults action to get it."
        Write-Output ""
        Write-Output "      testid = The id of the test, use listtests action to get it."
        Write-Output ""
        Write-Output "    tagetkey = The key of the target, use listmachinetargets to get it."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output " testmachine = The name of the machine as registered with the HLK controller."
        Write-Output "               NOTE: test machine should be in a READY state."
        Write-Output ""
        Write-Output "    poolname = The name of the pool."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($result)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test result's index."
            Usage; return
        } else {
            throw "Please provide a test result's index."
        }
    }
    if ([String]::IsNullOrEmpty($test)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a test's id."
            Usage; return
        } else {
            throw "Please provide a test's id."
        }
    }
    if ([String]::IsNullOrEmpty($target)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a target's key."
            Usage; return
        } else {
            throw "Please provide a target's key."
        }
    }
    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }
    if ([String]::IsNullOrEmpty($machine)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a machine's name."
            Usage; return
        } else {
            throw "Please provide a machine's name."
        }
    }
    if ([String]::IsNullOrEmpty($pool)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a pool's name."
            Usage; return
        } else {
            throw "Please provide a pool's name."
        }
    }

    if (-Not ($WntdPool = $RootPool.GetChildPools() | Where-Object { $_.Name -eq $pool })) { throw "Did not find pool $pool in Root pool, aborting..." }
    if (-Not ($WntdMachine = $WntdPool.GetMachines()| Where-Object { $_.Name -eq $machine })) { throw "The test machine was not found, aborting..." }
    if (-Not ($WntdTarget = $WntdMachine.GetTestTargets() | Where-Object { $_.Key -eq $target })) { throw "A target that matches the target's key given was not found in the specified machine, aborting..." }
    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }
    if (-Not ($WntdPI = $WntdProject.GetProductInstances() | Where-Object { $_.OSPlatform -eq $WntdMachine.OSPlatform })) { throw "Machine pool not targeted in the project." }

    $WntdPITargets = New-Object System.Collections.ArrayList

    if ($WntdTarget.TargetType -eq "TargetCollection") {
        foreach ($tTarget in $WntdPI.FindTargetFromContainer($WntdTarget.ContainerId)) {
            $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $tTarget.Key) -and ($_.Machine.Equals($tTarget.Machine)) } | foreach { $WntdPITargets.Add($_) | Out-Null }
        }
        if ($WntdPITargets.Count -lt 1) { throw "The target is not being targeted by the project." }
    } else {
        if (-Not ($WntdPITarget = $WntdPI.GetTargets() | Where-Object { ($_.Key -eq $WntdTarget.Key) -and ($_.Machine.Equals($WntdMachine)) })) { throw "The target is not being targeted by the project." }
        $WntdPITargets.Add($WntdPITarget) | Out-Null
    }

    $WntdTests = New-Object System.Collections.ArrayList
    $WntdPITargets | foreach { $WntdTests.AddRange($_.GetTests()) }

    if (-Not ($WntdTest = $WntdTests | Where-Object { $_.Id -eq $test })) { throw "Didn't find a test with the id given." }

    if (-Not ($WntdResult = $WntdTest.GetTestResults()[$result])) { throw "Invalid test result index, can't find the test result." } else { $WntdLogs = $WntdResult.GetLogs() }
    if (-Not ($WntdLogs.Count -ge 1)) { throw "There are no logs to be zipped in the test result." }

    $DayStamp = $(get-date).ToString("dd-MM-yyyy")
    $TimeStamp = $(get-date).ToString("hh_mm_ss")

    $LogsDir = $env:TEMP + "\hlk_test_logs\$DayStamp\[$TimeStamp]" + $WntdTest.Id
    $ZipPath = $env:TEMP + "\hlk_test_logs\$DayStamp\$DayStamp" + "_" + $TimeStamp + "_" + $WntdTest.Id + ".zip"

    if (-Not $json) {
        Write-Output "The test has $($WntdResult.Status)!."
        Write-Output "Logs zipped to:"
        Write-Output "$ZipPath"
    }
    foreach ($Log in $WntdLogs) {
        $Log.WriteLogTo([System.IO.Path]::Combine($LogsDir, $Log.LogType, $Log.Name))
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($LogsDir, $ZipPath)
    if ($json) {
        @(New-TestResultLogsZip $WntdTest.Name $WntdTest.Id $WntdResult.Status.ToString() $ZipPath) | ConvertTo-Json -Compress
    }
}
#
# CreateProjectPackage
function createprojectpackage {
    [CmdletBinding()]
    param([Switch]$help, [Switch]$rph, [Parameter(Position=1)][String]$project, [Parameter(Position=2)][String]$package)

    function Usage {
        Write-Output "createprojectpackage:"
        Write-Output ""
        Write-Output "A script that creates a project's package and saves it to a file at <package> if used,"
        Write-Output "if not to %TEMP%\prometheus_packages\..."
        Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
        Write-Output ""
        Write-Output "Usage:"
        Write-Output ""
        Write-Output "createprojectpackage <projectname> [<package>] [-help]"
        Write-Output ""
        Write-Output "Any parameter in [] is optional."
        Write-Output ""
        Write-Output "        help = Shows this message."
        Write-Output ""
        Write-Output " projectname = The name of the project."
        Write-Output ""
        Write-Output "     package = The path to the output package file."
        Write-Output ""
        Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
    }

    if ($help) {
        if (-Not $json) { Usage; return } else { throw "Help requested, ignoring..." }
    }

    if ([String]::IsNullOrEmpty($project)) {
        if (-Not $json) {
            Write-Output "WARNING: Please provide a project's name."
            Usage; return
        } else {
            throw "Please provide a project's name."
        }
    }

    if (-Not ($Manager.GetProjectNames().Contains($project))) { throw "No project with the given name was found, aborting..." } else { $WntdProject = $Manager.GetProject($project) }

    [Int]$global:Steps = 1
    if ($server) {
        $global:StepsArray = New-Object System.Collections.ArrayList
    }

    [Action[Microsoft.Windows.Kits.Hardware.ObjectModel.Submission.PackageProgressInfo]]$action = {
        param([Microsoft.Windows.Kits.Hardware.ObjectModel.Submission.PackageProgressInfo]$progressinfo)

        if (($progressinfo.Current -eq 0) -and ($progressinfo.Maximum -eq 0)) {
            $jsonprogressinfo = @(New-PackageProgressInfo $progressinfo.Current $progressinfo.Maximum $progressinfo.Message) | ConvertTo-Json -Compress
            if ($server) {
                $global:StepsArray.Add($jsonprogressinfo) | Out-Null
            }
            Write-Host $jsonprogressinfo
        } else {
            if ($global:Steps -lt $progressinfo.Current) {
                if ($server) {
                    $JoinedSteps = $global:StepsArray -join [Environment]::NewLine
                    $global:StepsArray.Clear()
                    sendtcpsocket($JoinedSteps)
                    [Int]$global:Steps = receivetcpsocket
                } else {
                    Write-Host -NoNewline "toolsHLK@$($ControllerName):createprojectpackage($project)> "
                    [Int]$global:Steps = Read-Host
                }
            }
            $jsonprogressinfo = @(New-PackageProgressInfo $progressinfo.Current $progressinfo.Maximum $progressinfo.Message) | ConvertTo-Json -Compress
            if ($server) {
                $global:StepsArray.Add($jsonprogressinfo) | Out-Null
            }
            Write-Host $jsonprogressinfo
        }
    }

    if (-Not [String]::IsNullOrEmpty($package)) {
        $PackagePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($package)
    } else {
        if (-Not (Test-Path ($env:TEMP + "\prometheus_packages\"))) { New-Item ($env:TEMP + "\prometheus_packages\") -ItemType Directory | Out-Null }
        $PackagePath = $env:TEMP + "\prometheus_packages\" + $(get-date).ToString("dd-MM-yyyy") + "_" + $(get-date).ToString("hh_mm_ss") + "_" + $WntdProject.Name + "." + $Studio + "x"
    }
    $PackageWriter = New-Object Microsoft.Windows.Kits.Hardware.ObjectModel.Submission.PackageWriter $WntdProject
    if ($rph) { $PackageWriter.SetProgressActionHandler($action) }
    $PackageWriter.Save($PackagePath)
    $PackageWriter.Dispose()
    if (-Not $json) {
        Write-Output "Packaged to $($PackagePath)..."
    } else {
        @(New-ProjectPackage $WntdProject.Name $PackagePath) | ConvertTo-Json -Compress
    }
}
#
# GetTimeStamp
function gettimestamp {
    $DayStamp = $(get-date).ToString("dd-MM-yyyy")
    $TimeStamp = $(get-date).ToString("hh_mm_ss")
    return "[$DayStamp`_$TimeStamp]"
}
#
# SendTCPSocket
function sendtcpsocket {
    [CmdletBinding()]
    param([String]$data)

    $LengthString = "$($data.Length.ToString())$([Environment]::NewLine)"
    $TCPStream.Write([System.Text.Encoding]::Ascii.GetBytes($LengthString), 0, $LengthString.Length)
    $TCPStream.Write([System.Text.Encoding]::Ascii.GetBytes($data), 0, $data.Length)
}
#
# ReceiveTCPSocket
function receivetcpsocket {
    while (-Not $TCPStream.DataAvailable) { Start-Sleep -Milliseconds $PollingSleep }
    $TCPStreamReader.ReadLine().TrimEnd()
}
#
# Usage
function Usage {
    Write-Output "A shell-like tool set for HLK with various purposes which covers several actions as"
    Write-Output "explained in the usage section below."
    Write-Output "These tasks are done by using the HLK API provided with the Windows HLK Studio."
    Write-Output ""
    Write-Output "Usage:"
    Write-Output ""
    Write-Output "Command: <action> <actionsparameters> [json]"
    Write-Output ""
    Write-Output "Any parameter in [] is optional."
    Write-Output ""
    Write-Output "              json = Output in JSON format."
    Write-Output ""
    Write-Output "            action = The action you want to execute."
    Write-Output ""
    Write-Output " actionsparameters = The action's parameters as explained in the action's usage."
    Write-Output "                     NOTE: use -help to show action's usage."
    Write-Output ""
    Write-Output "Actions list:"
    Write-Output ""
    Write-Output "                   help : Shows the help message."
    Write-Output ""
    Write-Output "              listpools : Lists the pools info."
    Write-Output ""
    Write-Output "              getpool : Gets the pool info."
    Write-Output ""
    Write-Output "              getdefaultpool : Gets the default pool info."
    Write-Output ""
    Write-Output "             createpool : Creates a pool."
    Write-Output ""
    Write-Output "             deletepool : Deletes a pool."
    Write-Output ""
    Write-Output "            movemachinefromdefaultpool : Moves a machine from default pool to another."
    Write-Output ""
    Write-Output "            movemachine : Moves a machine from one pool to another."
    Write-Output ""
    Write-Output "        setmachinestate : Sets the state of a machine to Ready or NotReady."
    Write-Output ""
    Write-Output "          deletemachine : Deletes a machine"
    Write-Output ""
    Write-Output "     listmachinetargets : Lists the target devices of a machine that are available to be tested."
    Write-Output ""
    Write-Output "           listprojects : Lists the projects info."
    Write-Output ""
    Write-Output "          createproject : Creates a project."
    Write-Output ""
    Write-Output "          deleteproject : Deletes a project."
    Write-Output ""
    Write-Output "    createprojecttarget : Creates a project's target."
    Write-Output ""
    Write-Output "    deleteprojecttarget : Delete a project's target."
    Write-Output ""
    Write-Output "              listtests : Lists a project target's tests."
    Write-Output ""
    Write-Output "            gettestinfo : Gets a project target's test info."
    Write-Output ""
    Write-Output "              queuetest : Queue's a test, use listtestresults to get the results."
    Write-Output ""
    Write-Output "    applyprojectfilters : Applies the filters on a project's test results."
    Write-Output ""
    Write-Output " applytestresultfilters : Applies the filters on a test result."
    Write-Output ""
    Write-Output "        listtestresults : Lists a test's results info."
    Write-Output ""
    Write-Output "      ziptestresultlogs : Zips a test result's logs."
    Write-Output ""
    Write-Output "   createprojectpackage : Creates a project's package."
    Write-Output ""
    Write-Output "NOTE: For more infromation about every action use action's -help parameter!"
    Write-Output "NOTE: Windows HLK Studio should be installed on the machine running the script!"
}

# ----------------------------------------------------------------- #
# Choosing which action to perform by parsing the called parameters #
# ----------------------------------------------------------------- #
$toolsHLKlist = New-Object System.Collections.ArrayList
$toolsHLKlist.AddRange( ("listpools",
                         "getpool",
                         "getdefaultpool",
                         "createpool",
                         "deletepool",
                         "movemachinefromdefaultpool",
                         "movemachine",
                         "setmachinestate",
                         "deletemachine",
                         "listmachinetargets",
                         "listprojects",
                         "createproject",
                         "deleteproject",
                         "createprojecttarget",
                         "deleteprojecttarget",
                         "listtests",
                         "gettestinfo",
                         "queuetest",
                         "applyprojectfilters",
                         "applytestresultfilters",
                         "listtestresults",
                         "ziptestresultlogs",
                         "createprojectpackage") )

# -------------------------------------- #
# Trying to perform the requested action #
# -------------------------------------- #
$ConnectFileName = $env:WTTSTDIO + "connect.xml"
Write-Output "Opening connection file $ConnectFileName"
$ConnectFile = [xml](Get-Content $ConnectFileName)

$ControllerName = $ConnectFile.Connection.GetAttribute("Server")
$DatabaseName = $connectFile.Connection.GetAttribute("Source")

Write-Output "Connecting to $ControllerName..."
$Manager = New-Object Microsoft.Windows.Kits.Hardware.ObjectModel.DBConnection.DatabaseProjectManager -Args $ControllerName, $DatabaseName
if ($Manager -eq $null) {
    Write-Output "Connecting to $ControllerName failed"
    exit -1
}


$RootPool = $Manager.GetRootMachinePool()
$DefaultPool = $RootPool.DefaultPool

if ($server) {
    Write-Output "Initializing server's TCP listener"
    try {
    $TCPListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse('0.0.0.0'), $port)
    $TCPListener.Start()
    } catch [System.Net.Sockets.SocketException] {
        Write-Output "Starting TCP listener failed due to: $_.Exception.Message"
        exit -1
    }

    Write-Output "Waiting for a TCP client connection on port $port..."
    $TCPClientTask = $TCPListener.AcceptTcpClientAsync()
    if ($TCPClientTask.Wait($timeout*1000)) {
        Write-Output "TCP client is connected"
        $TCPClient = $TCPClientTask.Result
    } else {
        Write-Output "Waiting for a TCP client connection has timed out after $timeout seconds"
        $TCPListener.Stop()
        exit -1
    }

    $TCPStream = $TCPClient.GetStream()
    $TCPStreamReader = New-Object System.IO.StreamReader $TCPStream, System.Text.ASCIIEncoding
    $PollingSleep = [Math]::Ceiling(1000 / $polling)

    Write-Host (gettimestamp) "sending START"
    sendtcpsocket("START")
}

while($true) {
    if ($server) {
        $cmdline = receivetcpsocket
        Write-Host (gettimestamp) "received ($cmdline), processing..."
    } else {
        Write-Host -NoNewline "toolsHLK@$ControllerName> "
        $cmdline = Read-Host
    }

    [System.Collections.ArrayList]$cmdlinelist = $cmdline.Split(" ")
    $json = $false
    if ($cmdlinelist.Contains("json")) {
        $json = $true
        $cmdlinelist.Remove("json")
    }

    $cmd = $cmdlinelist[0]
    $cmdlinelist.RemoveAt(0)
    $cmdargs = $cmdlinelist -join " "

    if ([String]::IsNullOrEmpty($cmd) -or $cmd -eq "help") {
        $output = Usage
    } elseif ($cmd -eq "version") {
        $output = "toolsHLK Version: $Version"
    } elseif ($cmd -eq "exit") {
        if ($server) {
            Write-Host (gettimestamp) "sending END"
            sendtcpsocket("END")
        }
        break;
    } elseif ($cmd -eq "ping") {
        $output = "pong"
    } elseif ($toolsHLKlist.Contains($cmd)) {
        try {
            $actionoutput = Invoke-Expression "$cmd $cmdargs"
            if (-Not $json) {
                $output = $actionoutput
            } else {
                $output = @(New-ActionResult $actionoutput) | ConvertTo-Json -Depth $MaxJsonDepth -Compress
            }
        } catch {
            if (-Not $json) {
                if ([String]::IsNullOrEmpty($_.Exception.InnerException)) {
                    $output = "WARNING: $($_.Exception.Message)"
                } else {
                    $output = "WARNING: $($_.Exception.InnerException.Message)"
                }
            } else {
                $output = New-ActionResult $nil $_.Exception | ConvertTo-Json -Compress
            }
        }
    } else {
        $output = "No such action name, type help."
    }

    $JoinedOutput = $output -join [Environment]::NewLine

    if ($server) {
        Write-Host (gettimestamp) "sending result for ($cmdline):"
        Write-Host $JoinedOutput
        sendtcpsocket($JoinedOutput)
    } else {
        Write-Host $JoinedOutput
    }
}

if ($server) {
    $TCPStreamReader.Close()
    $TCPStream.Close()
    $TCPClient.Close()
    $TCPListener.Stop()
}
