param([String] $vhdx_path='C:\fedora.vhdx')
# Main script to get vhdx and start gen1/gen2 vm.

$PrivateSwitchName = "Private"

function CreatePrivateSwitches(){
    #
    # See if an Private switch named 'Private' already exists.
    # If not, create it
    #
    Write-Host "Info : Checking for Private vSwitch named '${PrivateSwitchName}'"
    $privateSwitch = Get-VMSwitch -Name "${privateSwitchName}" -ErrorAction SilentlyContinue
    if (-not $privateSwitch){
        New-VMSwitch -Name "${privateSwitchName}" -SwitchType Private
        if (-not $?){
            Throw "Error: Unable to create Private switch"
        }
        Write-Host "Info: Private vSwitch '${privateSwitchName}' is created"
    }
    else{
        Write-Host -f Yellow "Warning: the vSwitch '$privateSwitchName}' already exists"
    }
}

# Create internal switch if does not exist
CreatePrivateSwitches

$vhdx_name=[System.IO.Path]::GetFileNameWithoutExtension($vhdx_path)
$vhdx_folder=[System.IO.Path]::GetDirectoryName($vhdx_path)

# $vm_name_gen1="fedora-gen1"
# $vm_name_gen2="fedora-gen2"
$vm_name_gen1= $vhdx_name +"-gen1"
$vm_name_gen2= $vhdx_name +"-gen2"

# $vm_gen1_vhdx="C:\fedora-gen1.vhdx"
# $vm_gen2_vhdx="C:\fedora-gen2.vhdx"
$vm_vhdx_gen1=$vhdx_folder+$vm_name_gen1+".vhdx"
$vm_vhdx_gen2=$vhdx_folder+$vm_name_gen2+".vhdx"

# Remove old vm if have
powershell C:\nested-hyperv-on-kvm\hyperv_sets.ps1 -action del -vm_name $vm_name_gen1
powershell C:\nested-hyperv-on-kvm\hyperv_sets.ps1 -action del -vm_name $vm_name_gen2
start-sleep 2

if (-not (Test-Path $vhdx_path)){
    write-host "Error: the vhdx file $vhdx_path does not exist."
    exit 1
}

start-sleep 2
Copy-Item $vhdx_path $vm_vhdx_gen1
start-sleep 2
Copy-Item $vhdx_path $vm_vhdx_gen2
start-sleep 2
Remove-Item $vhdx_path

#Start new gen1 vm
powershell C:\nested-hyperv-on-kvm\hyperv_sets.ps1 -action clone -vm_name $vm_name_gen1 -vhd_path $vhdx_folder
if ($? -eq $false) {
    write-host "Error: fail to start vm $vm_name_gen1"
    exit 1
}
start-sleep 2
powershell C:\nested-hyperv-on-kvm\hyperv_sets.ps1 -action clone -vm_name $vm_name_gen2 -vhd_path $vhdx_folder -gen2
if ($? -eq $false) {
    write-host "Error: fail to start vm $vm_name_gen2"
    exit 1
}
exit 0
