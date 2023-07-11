#######################################################################
#
#    Initialize, or provision Windows Server as follows:
#  - The Hyper-V feature is installed.
#  - The required Hyper-V vSwitche is created, e.g. Internal switch.
#######################################################################

Write-Host "Info: Start to build up enviroment for Hyper-V"

$internalSwitchName = "Internal"
$externalSwitchName = "External"

function TestCommandExists ([String]$command){
    try {
        if(Get-Command $command -ErrorAction SilentlyContinue){
            Write-Host "Info: $command exists";
            return $true
        }
    }
    Catch {
        Write-Host "Info: $command does not exist";
        return $false
    }
}

function InstallHyperVPowershell(){
    # Need to restart windows to take effect, restart action will be out of this script
    if (TestCommandExists Get-WindowsFeature) {
        $powershellFeature = Get-WindowsFeature -Name "Hyper-v-powershell"
        if (-not $powershellFeature.Installed){
            Install-windowsFeature -Name Hyper-v-powershell
            if (-not $?){
                Throw "Error: Unable to install Hyper-v module"
            }
            else{
                Write-Host "Info: Have executed Install-windowsfeature successfully";
            }
        }
    }
}

function CreateExternalSwitch()
{
    #
    # We will only create an external switch if:
    #  - The host only has a single physical NIC, and an external switch
    #    does not already exist.
    #  - The host has multiple physical NICs, but only one is connected,
    #    and an external switch does not already exist.
    #

    Write-Host "Info: Checking for External vSwitch named '${externalSwitchName}'"
    $externalSwitch = Get-VMSwitch -Name "${externalSwitchName}" -ErrorAction SilentlyContinue
    if ($externalSwitch){
        # A vSwitch named external already exists
        Write-Host -f Yellow "Warning: The external vSwitch '${externalSwitchName}' already exists"
        return
    }

    $adapters = Get-NetAdapter
    $numPotentialNICs = 0
    $potentialNIC = $null

    foreach ($nic in $adapters){
        # Make sure NIC is connected (MediaConnectState = 1)
        # and the NIC is up (InterfaceOperationalStatus = 1)

        if ($nic.InterfaceOperationalStatus -eq 1 -and $nic.MediaConnectState -eq 1){
            $numPotentialNICs += 1
            $potentialNIC = $nic.InterfaceDescription
            Write-Host "Info: Potential NIC for external vSwitch = '${potentialNIC}'"
        }
    }

    if ($numPotentialNICs -eq 0){
        Write-Host -f Yellow "Warning: No potential NICs found to create an External vSwitch"
        Write-Host -f Yellow "         You will need to manually create the external vSwitch"
        exit 1
    }
    elseif ($numPotentialNICs -gt 1){
        Write-Host -f Yellow "Warning: There are more than one physical NICs that could be used"
        Write-Host -f Yellow "         with an external vSwitch.  You will need to manually"
        Write-Host -f Yellow "         create the external vSwitch"
        exit 1
    }

    #
    # Create an External NIC using the one potential physical NIC
    #
    New-VMSwitch -Name "${externalSwitchName}" -NetAdapterInterfaceDescription "${potentialNIC}"
    if (-not $?){
        Write-Host "Error: Unable to create external vSwitch using NIC '${potentialNIC}'"
        exit 1
    }
    Write-Host "Info: External vSwitch '${externalSwitchName}' was created, using NIC"
    Write-Host "      ${potentialNIC}"
}

function CreateInternalSwitch(){
    #
    # See if an internal switch named 'Internal' already exists.
    # If not, create it
    #
    Write-Host "Info: Checking for Internal vSwitch named '${internalSwitchName}'"
    $internalSwitch = Get-VMSwitch -Name "${internalSwitchName}" -ErrorAction SilentlyContinue
    if (-not $internalSwitch){
        New-VMSwitch -Name "${internalSwitchName}"  -SwitchType Internal
        if (-not $?){
            Throw "Error: Unable to create Internal switch"
        }

        Get-NetAdapter -Name "${internalSwitchName}" | New-NetIPAddress -AddressFamily ipv4 -IPAddress 192.168.0.1 -PrefixLength 24
        Write-Host "Info: Internal vSwitch '${internalSwitchName}' was created with IP range 192.168.0.1/24"
    }
    else{
        Write-Host -f Yellow "Warning: The Internal vSwitch '${internalSwitchName}' already exists"
    }
}

function InstallRolesAndFeatures(){
    if ( TestCommandExists Get-WindowsFeature){
        $hypervFeature = Get-WindowsFeature -Name "Hyper-V"
        if (-not $hypervFeature.Installed){
            $feature = Install-WindowsFeature -Name "Hyper-V" -IncludeAllSubfeature -IncludeManagementTools
            if (-not $feature.Success){
                Throw "Error: Unable to install the Hyper-V roles"
            }else{
                Write-Host "Info: Have executed Install-WindowsFeature successfully"
            }
        }
    }
    else{
        # For windows 10 and 11
        $hypervFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
        if (-not $hypervFeature.Enalbed){
            $feature=Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart
            if (-not $feature.Online){
                Throw "Error: Unable to enable the Hyper-V roles }"
            }
            else{
                Write-Host "Info: Have executed Enable-WindowsOptionalFeature successfully"
            }
        }
    }
}

#######################################################################
#
# Main script body
#
#######################################################################

try {
    # Install any roles and features
    Write-Host "Info: Start to install for Hyper-V Powershell"
    InstallHyperVPowershell

    Write-Host "Info: Start to install Hyper-V role"
    InstallRolesAndFeatures
    #CreateExternalSwitch
    #CreateInternalSwitch
}
catch {
    $msg = $_.Exception.Message
    Write-Host -f Red "Error: Unable to provision the host"
    Write-Host -f Red "${msg}"
    exit 1
}

exit 0
