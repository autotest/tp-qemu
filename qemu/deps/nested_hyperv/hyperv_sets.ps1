param (
    [CmdletBinding()]
    [String] $action,
    [String] $vm_name,
    [Parameter(Mandatory=$false)][String] $vhd_path,
    [Parameter(Mandatory=$false)][Switch] $gen2,
    [Parameter(Mandatory=$false)][String] $isoPath,
    [Parameter(Mandatory=$false)][String] $isoKSPath
)

function VMStop([String] $vmName){
    $vm = get-vm $vmName
    if ( $vm.State -eq "Off"){
        write-host "Info: $vmName is stopped"
        return $true
    }

    stop-vm $vmName -force
    if ( $? -ne $true ){
        write-host "Error: stop-VM $vm failed"
        return $false
    }

    $timeout = 100
    while ($timeout -gt 0){
        $vm = get-vm $vmName
        if ($vm.state -eq "Off"){
            write-host "Info: $vmName state is Off now"
            break
        }
        else{
            write-host "Info: $vmName state is not Off, waiting..."
            start-sleep -seconds 1
            $timeout -= 1
        }
    }
    if ( $timeout -eq 0 -and $vm.state -ne "Off"){
        write-host "Error: Stop $vm failed (timeout=$timeout)"
        return $false
    }

    return $true
}

function VMRemove([String]$vmName){
    # Check the vm, if exists, then delete
    Get-VM -Name $vmName -ErrorAction "SilentlyContinue" | out-null
    if ( $? ){
        # check vm is not Running
        if ( $(Get-VM -Name $vmName).State -eq "Running"){
            VMStop($vmName)
        }
        write-host "Info: Remove $vmName"
        # Get latest snapshot
        Get-VMSnapshot -VMName $vmName | Remove-VMSnapshot
        start-sleep -s 2
        $vhdpath = (get-vm -vmName $vmName | Select-Object vmid | get-vhd ).ParentPath
        if ( -not $vhdpath ) {
            $vhdpath = (get-vm -vmName $vmName | Select-Object vmid | get-vhd ).Path
        }

        Remove-VM -Name $vmName  -Confirm:$false -Force
        start-sleep -s 2
        remove-item -Path $vhdpath -force

        if ($?){
            write-output "Info: Remove VM succussfully"
        }
        else{
            Write-Output "Error: Remove VM failed"
        }
    }
}

function GetIPv4ViaKVP([String] $vmName){
    $vmObj = Get-WmiObject -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$vmName`'"
    if (-not $vmObj){
        write-error -Message "GetIPv4ViaKVP: Unable to create Msvm_ComputerSystem object" -Category ObjectNotFound -ErrorAction SilentlyContinue
        return $null
    }

    $kvp = Get-WmiObject -Namespace root\virtualization\v2 -Query "Associators of {$vmObj} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvp){
        write-error -Message "GetIPv4ViaKVP: Unable to create KVP exchange component" -Category ObjectNotFound -ErrorAction SilentlyContinue
        return $null
    }

    $rawData = $Kvp.GuestIntrinsicExchangeItems
    if (-not $rawData){
        write-error -Message "GetIPv4ViaKVP: No KVP Intrinsic data returned" -Category ReadError -ErrorAction SilentlyContinue
        return $null
    }

    $addresses = $null

    foreach ($dataItem in $rawData){
        $found = 0
        $xmlData = [Xml] $dataItem
        foreach ($p in $xmlData.INSTANCE.PROPERTY){
            if ($p.Name -eq "Name" -and $p.Value -eq "NetworkAddressIPv4"){
                $found += 1
            }

            if ($p.Name -eq "Data"){
                $addresses = $p.Value
                $found += 1
            }

            if ($found -eq 2){
                $addrs = $addresses.Split(";")
                foreach ($addr in $addrs){
                    if ($addr.StartsWith("127.")){
                        Continue
                    }
                    return $addr
                }
            }
        }
    }

    write-error -Message "GetIPv4ViaKVP: No IPv4 address found for VM ${vmName}" -Category ObjectNotFound -ErrorAction SilentlyContinue
    return $null
}

function WaitForVMToStartKVP([String] $vmName, [int] $timeout){
    $waitTimeOut = $timeout
    while ($waitTimeOut -gt 0){
        $ipv4 = GetIPv4ViaKVP $vmName
        if ($ipv4){
            return $true
        }

        $waitTimeOut -= 10
        Start-Sleep -s 10
    }

    write-error -Message "WaitForVMToStartKVP: VM ${vmName} did not start KVP within timeout period ($timeout)" -Category OperationTimeout -ErrorAction SilentlyContinue
    return $false
}

function NewCheckpoint([String] $vmName, [String] $snapshotName){
    write-host "Info: Stop $vmName before make snapshot"
    VMStop $vmName

    write-host "Info: make checkpoint of $vmName, checkpoint name is $snapshotName"
    Checkpoint-VM -Name $vmName -SnapshotName $snapshotName

    if ( $snapshotName -eq $(Get-VMSnapshot $vmName).Name){
        write-host "Info: $snapshotName for $vmName is created successfully"
        return $true
    }
    else{
        return $false
    }
}

function SetFirmwareProcessor([Switch]$gen2, [String]$vmName, [Int64]$cpuCount){
    # If gen 2 vm, set vmfirmware secure boot disabled
    if ($gen2){
        # disable secure boot
        Set-VMFirmware $vmName -EnableSecureBoot Off

        if (-not $?){
            write-host "Info: Set-VMFirmware $vmName secureboot failed"
            return $false
        }

        write-host "Info: Set-VMFirmware $vmName secureboot successfully"
    }

    # set processor to 2, default is 1
    Set-VMProcessor -vmName $vmName -Count $cpuCount

    if (! $?){
        write-host "Error: Set-VMProcessor $vmName  to $cpuCount failed"
        return $false
    }

    if ((Get-VMProcessor -vmName $vmName).Count -eq $cpuCount){
        write-host "Info: Set-VMProcessor $vmName to $cpuCount"
    }
}

function NewVMFromVHDX([String]$vmPath, [Switch]$gen2, [String]$switchName, [String]$vmName, [Int64]$cpuCount, [Int64]$mem){
    write-host "Info: Creating $vmName with $cpuCount CPU and ${mem}G memory."
    # Convert GB to bytes because parameter -MemoryStartupByptes requires bytes
    [Int64]$memory = 1GB * $mem

    if ($gen2){
        New-VM -Name "$vmName" -Generation 2 -BootDevice "VHD" -MemoryStartupBytes $memory -VHDPath $vmPath -SwitchName $switchName | Out-Null
    }
    else {
        New-VM -Name "$vmName" -BootDevice "IDE" -MemoryStartupBytes $memory -VHDPath $vmPath -SwitchName $switchName | Out-Null
    }

    if (-not $?){
        write-host "New-VM $vmName failed"
        # rm new created disk
        If (Test-Path $vmPath){
            Remove-Item $vmPath
        }
        return $false
    }
    write-host "Info: New-VM $vmName successfully"

    if ($gen2){
        SetFirmwareProcessor -gen2 -vmName $vmName -cpuCount $cpuCount
    }
    else{
            SetFirmwareProcessor -vmName $vmName -cpuCount $cpuCount
        }
    if (-not $?){
        write-host "Error: fail to set the firmware and processor for VM $vmName"
        return $false
    }
    return $true
}

function VMStart([String]$vmPath, [String]$vmName, [Bool]$gen2, [String]$switchName, [Int64]$cpuCount, [Int64]$mem){
    write-host "Info: vmName is $vmName"

    # Create vm based on new vhdx file
    if ($gen2){
        NewVMFromVHDX -vmPath "${vmPath}\${vmName}.vhdx" -gen2 $true -switchName $switchName -vmName $vmName -cpuCount $cpuCount -mem $mem
    }
    else{
        NewVMFromVHDX -vmPath "${vmPath}\${vmName}.vhdx" -switchName $switchName -vmName $vmName -cpuCount $cpuCount -mem $mem
    }
    # Now Start the VM
    write-host "Info: Starting VM $vmName."
    Start-VM -Name $vmName
    start-sleep -seconds 60

    $timeout = 0
    while ($timeout -lt 180) {
    # Check the VMs heartbeat
    $hb = Get-VMIntegrationService -VMName $VMName -Name "Heartbeat"
    $vm = Get-VM $vmName
    if ($($hb.Enabled) -eq "True" -and $($vm.Heartbeat) -eq "OkApplicationsUnknown") {
        write-host "Info: Heartbeat detected for $vmName"
        return $true
    }
    else {
        start-sleep -seconds 10
        $timeout = $timeout + 10
    }
    }

    write-host "Test Failed: VM heartbeat not detected after wait for 4 mintus!"
    write-host "Heartbeat not detected while the Heartbeat service is enabled, Heartbeat - $($vm.Heartbeat)"
    return $false
}

function VMPowerOn([String]$vmName){
    write-host "Info: vmName is $vmName"

    # Now Start the VM
    write-host "Info: Starting VM $vmName."
    $timeout = 300
    Start-VM -Name $vmName | out-null
    WaitForVMToStartKVP -vmName $vmName -timeout $timeout
    $vmIP = GetIPv4ViaKVP $vmName

    if ($vmIP){
        #Write-Output y | plink -l root -i ssh\3rd_id_rsa.ppk $vmIP "exit 0"
        write-host "Info: Get $vmName IP = $vmIP"
        return $vmIP
    }
    else{
        ###############################################################
        # Update for bug 2016 and 2012R2 Gen2 vm cannot install sometimes.
        # 2019 host verison is 17763
        ###############################################################

        [int]$BuildNumber = (Get-CimInstance Win32_OperatingSystem).BuildNumber
        write-host "INFO: current build number is $BuildNumber`n----------"
        [int]$gen = (Get-VM -Name $vmName).Generation
        if ( $gen -eq 2 -and  $BuildNumber -lt 17763 ) {
            for ($count=1; $count -le 5; $count++){

                write-host "Info: start to sleep 150 to check $vmName is really running or not"
                start-sleep -seconds 150
                $vmIP = GetIPv4ViaKVP $vmName
                if ($vmIP) {
                    return $vmIP
                }
                ##########################################################
                # if $duration 0, try to start vm again, change for bug
                ########################################################
                else {
                    write-host "Info : $vmName is being started again for bug - cannot enter kernel entry， retry $count"
                    Start-VM -name $vmName | out-null
                }
            }
            return $false
        } # end of if gen2 vm
    }
    return $false
}

function VMInstall([String]$vmPath, [String]$vmName, [Bool]$gen2, [String]$switchName, [Int64]$cpuCount, [Int64]$mem, [String]$isopath, [String]$isoKsPath){
    write-host "Info: Prepare to install vm, vmName is $vmName"
    $startDTM = (Get-Date)

    # Create vm based on new vhdx file by installing iso
    if ($gen2){
        NewVMFromISO -vmPath "${vmPath}\${vmName}.vhdx" -gen2 -switchName $switchName -vmName $vmName -cpuCount $cpuCount -mem $mem -isoPath $isopath -isoKsPath $isoKsPath
    }
    else{
        NewVMFromISO -vmPath "${vmPath}\${vmName}.vhdx" -switchName $switchName -vmName $vmName -cpuCount $cpuCount -mem $mem -isoPath $isopath -isoKsPath $isoKsPath
    }
    # Now Start the VM
    write-host "Info: Installing VM $vmName is started "

    $timeout = 6000
    Start-VM -Name $vmName
    WaitForVMToStartKVP -vmName $vmName -timeout $timeout
    $vmIP = GetIPv4ViaKVP $vmName

    $endDTM = (Get-Date)

    write-host "Summary: The installation executed $(($endDTM-$startDTM).TotalMinutes) minutes"
    $vmVhdxPath= (get-vm -vmName $vmName | Select-Object vmid | get-vhd ).path

    write-host "vmVhdxPath is $vmVhdxPath"
    # VMStop -vmName $vmName

    if ($vmIP){
        #Write-Output y | plink -l root -i ssh\3rd_id_rsa.ppk $vmIP "exit 0"
        write-host "Info: Get $vmName IP = $vmIP"
        return $vmIP
    }
    else{
        write-host "ERROR: Unable to get VM IP" -ErrorAction SilentlyContinue
        #VMRemove -vmName $vmName
        return $false
    }
}

function NewVMFromISO([String]$vmPath, [switch]$gen2, [String]$switchName, [String]$vmName, [Int64]$cpuCount, [Int64]$mem, [String]$isoPath, [String]$isoKsPath){
    write-host "Info: Creating $vmName with $cpuCount CPU and ${mem}G memory."
    # Convert GB to bytes because parameter -MemoryStartupByptes requires bytes
    [Int64]$memory = 1GB * $mem

    # gen2 need specify -Generation
    if ($gen2){
        write-host "Info: New-VM -Name $vmName -MemoryStartupBytes $memory -Generation 2 -NewVHDSizeBytes 30GB -SwitchName $switchName -NewVHDPath $vmPath"

        New-VM -Name $vmName -MemoryStartupBytes $memory -Generation 2 -NewVHDSizeBytes 30GB -SwitchName $switchName -NewVHDPath $vmPath
    }
    else
    {
        write-host "Info: New-VM -Name $vmName -MemoryStartupBytes $memory -NewVHDSizeBytes 30GB -SwitchName $switchName -NewVHDPath $vmPath -BootDevice IDE"

        New-VM -Name $vmName -MemoryStartupBytes $memory -NewVHDSizeBytes 30GB -SwitchName $switchName -NewVHDPath $vmPath -BootDevice "IDE"
    }

    if (-not $?){
        write-host "New-VM $vmName failed"
        # rm new created disk
        If (Test-Path $vmPath){
            Remove-Item $vmPath
        }
        return $false
    }
    write-host "Info: New-VM $vmName successfully"

    if ($gen2) {
        SetFirmwareProcessor -gen2 -vmName $vmName -cpuCount $cpuCount
    }
    else{
            SetFirmwareProcessor -vmName $vmName -cpuCount $cpuCount
        }
    if (-not $?){
        write-host "Error: fail to set the firmware and processor for VM $vmName"
        return $false
    }
    Get-VMDvdDrive -VMName $vmName -ControllerNumber 1 | Remove-VMDvdDrive
    if (! $gen2) {
        # put the two isos file in the same controller, to make the iso inject
        Add-VMDvdDrive -VMName $vmName -Path $isoPath -ControllerNumber 1 -ControllerLocation 0 -Confirm:$False
	    start-sleep -s 1
        Add-VMDvdDrive -VMName $vmName -Path $isoKsPath -ControllerNumber 1 -ControllerLocation 1 -Confirm:$False
    } else {
        Add-VMDvdDrive -VMName $vmName -Path $isoPath -ControllerNumber 0 -ControllerLocation 1 -Confirm:$False
	    start-sleep -s 1
        Add-VMDvdDrive -VMName $vmName -Path $isoKsPath -ControllerNumber 0 -ControllerLocation 2 -Confirm:$False
    }

    if ( ! $? ){
        write-host "Error: Set dvd drive to vm $vmName failed"
        return $false
    } else{
        write-host "Info: Add dvd to vm $vmName $isoPath and $isoKsPath"
    }

    return $true
}

# Test command
#.\hyperv_set.ps1 -action install -vm_name test_install -vhd_path .\vhdpath\
#  -isopath C:\test.iso -isokspath C:\Temp\ks.iso
#.\hyperv_set.ps1 -action clone -vm_name testvm -vhd_path C:\ -gen2
# note: -vhd_path is folder path

$DebugPreference = "Continue"

#Set-Variable -Name switchName -Value "External" -Option constant -Scope Script
Set-Variable -Name switchName -Value "Private" -Option constant -Scope Script
Set-Variable -Name arch -Value "x86_64" -Option constant -Scope Script
Set-Variable -Name snapshotName -Value "ICABase" -Option constant -Scope Script

switch ($action){
    "del"{
        VMRemove $vm_name
    }
    "clone"{   # create 2 vcpu and 1G memory
        $ret = VMStart $vhd_path $vm_name $gen2 $switchName 2 1
        write-host "Infor: return value of VMStart for $vm_name is $ret"
    }
    "snapshot"{
        NewCheckpoint -vmName $vm_name -snapshotName $snapshotName
    }
    "install"{
        # return $ret
        $ret = VMInstall $vhd_path $vm_name $gen2 $switchName 2 2 $isopath $isoKSPath
        $ret = "$($ret[-1])".trim()
        #write-host "$($ret[-1])"
        return $ret
    }
    "poweron"{
        # poweron
        $ret = VMPowerOn $vm_name
        return "$($ret[-1])".trim()
    }
}
