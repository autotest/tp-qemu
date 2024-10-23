import os
import time

from avocado.utils import download, process
from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Nested Hyper-V on KVM:
    This case is used to test in L1 Windows VM, start L2 BIOS/UEFI Linux VM via Fedora image

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """  # noqa: E501

    def get_vhdx():
        test.log.info("start download fedora image")

        download_url = params.get("download_url")
        image_dir = params.get("images_base_dir", data_dir.get_data_dir())
        md5value = params.get("md5value")
        vhdx_dest = params.get("vhdx_dest")
        test.log.info(
            "Parameters: %s %s %s %s", download_url, image_dir, md5value, vhdx_dest
        )
        image_name = os.path.basename(download_url)
        image_path = os.path.join(image_dir, image_name)
        vhdx_name = image_name.replace("qcow2", "vhdx")
        vhdx_path = os.path.join(image_dir, vhdx_name)

        download.get_file(download_url, image_path, hash_expected=md5value)

        test.log.info("Covert fedora image to vhdx")
        cmd_covert = "qemu-img convert -O vhdx " + image_path + " " + vhdx_path

        status, output = process.getstatusoutput(cmd_covert, timeout)
        if status != 0:
            test.error(
                "qemu-img convert failed, status: %s, output: %s" % (status, output)
            )
        vm.copy_files_to(vhdx_path, vhdx_dest, timeout=300)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 600))
    session = vm.wait_for_login(timeout=timeout)

    test.log.info("Prepare vhdx file")
    get_vhdx()

    need_reboot = 0
    status = session.cmd_status(
        "powershell Get-VM \
        -ErrorAction SilentlyContinue",
        timeout=120,
        safe=True,
    )

    if status:
        need_reboot = 1
        test.log.info("Hyper-V powershell module does not install")
    else:
        test.log.info("Hyper-V powershell module has been installed")

    nested_dest = params.get("nested_dest")
    path_cmd = (
        r"powershell Remove-Item %s -recurse -force -ErrorAction SilentlyContinue"
        % nested_dest
    )

    try:
        session.cmd(path_cmd)
    except:
        test.log.info("catch error when remove folder, ignore it")

    time.sleep(10)

    # nested_dest=r"C:\nested-hyperv-on-kvm"
    # copy via deps
    hyperv_source = os.path.join(data_dir.get_deps_dir(), "nested_hyperv")
    vm.copy_files_to(hyperv_source, nested_dest)

    # set RemoteSigned policy mainly for windows 10/11, it is default for windows server
    session.cmd("powershell Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force")
    # powershell C:\nested-hyperv-on-kvm\hyperv_env.ps1
    status, output = session.cmd_status_output(
        r"powershell %s\hyperv_env.ps1" % nested_dest, timeout=1200
    )
    if status != 0:
        test.error("Setup Hyper-v enviroment error: %s", output)
    else:
        test.log.info("Setup Hyper-v enviroment pass: %s", output)

    if need_reboot:
        test.log.info(
            "VM will reboot to make Hyper-V powershell module installation work"
        )
        session = vm.reboot(session, timeout=360)

    time.sleep(5)
    # powershell C:\nested-hyperv-on-kvm\hyperv_run.ps1
    status, output = session.cmd_status_output(
        r"powershell %s\hyperv_run.ps1" % nested_dest, timeout=1800
    )
    if status != 0:
        test.fail("Test failed, script output is: %s", output)
    else:
        test.log.info("Test pass, script output is : %s", output)
    session.close()
