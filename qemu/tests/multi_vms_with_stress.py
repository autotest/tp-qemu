import os
import re
import shutil

from avocado.utils import cpu, process
from virttest import data_dir, env_process, error_context, qemu_storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test multiple VMs during host is under high stress.
    Steps:
        1. Run a stress test on host.
        2. Start multiple VMs on host and check if all can start
           successfully.
        3. Shutdown all VMs.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def unpack_stress_pkg():
        """Unpack the stress package."""
        process.system("tar -xzvf %s -C %s" % (archive_path, stress_inst_dir))

    def install_stress_pkg():
        """Install the stress package."""
        cmd_configure = "cd {0} && ./configure --prefix={0}".format(
            os.path.join(stress_inst_dir, params["stress_ver"])
        )
        cmd_make = "make && make install"
        process.system(" && ".join((cmd_configure, cmd_make)), shell=True)

    def run_stress_background():
        """Run stress in background."""
        process.system(params["stress_cmd"], shell=True, ignore_bg_processes=True)

    def is_stress_alive():
        """Whether the stress process is alive."""
        cmd = "pgrep -xl stress"
        if not utils_misc.wait_for(
            lambda: re.search(
                r"\d+\s+stress", process.system_output(cmd, ignore_status=True).decode()
            ),
            10,
        ):
            test.error("The stress process is not alive.")

    def copy_base_vm_image():
        """Copy the base vm image for VMs."""
        src_img = qemu_storage.QemuImg(
            params, data_dir.get_data_dir(), params["images"]
        )
        src_filename = src_img.image_filename
        src_format = src_img.image_format
        dst_dir = os.path.dirname(src_filename)
        for vm_name in vms_list:
            dst_filename = os.path.join(dst_dir, "%s.%s" % (vm_name, src_format))
            test.log.info("Copying %s to %s.", src_filename, dst_filename)
            shutil.copy(src_filename, dst_filename)

    def configure_images_copied():
        """Configure the images copied for VMs."""
        for vm_name in vms_list:
            params["images_%s" % vm_name] = vm_name
            image_name = "image_name_{0}_{0}".format(vm_name)
            params[image_name] = "images/%s" % vm_name
            params["remove_image_%s" % vm_name] = "yes"

    def wait_for_login_all_vms():
        """Wait all VMs to login."""
        return [vm.wait_for_login() for vm in vms]

    def wait_for_shutdown_all_vms(vms, sessions):
        """Wait all VMs to shutdown."""
        for vm, session in zip(vms, sessions):
            test.log.info("Shutting down %s.", vm.name)
            session.sendline(params["shutdown_command"])
            if not vm.wait_for_shutdown():
                test.fail("Failed to shutdown %s." % vm.name)

    vms_list = params["vms"].split()[1:]
    copy_base_vm_image()
    configure_images_copied()

    stress_inst_dir = params["stress_inst_dir"]
    stress_deps_dir = data_dir.get_deps_dir("stress")
    archive_path = os.path.join(stress_deps_dir, params["stress_pkg_name"])

    unpack_stress_pkg()
    install_stress_pkg()
    run_stress_background()
    is_stress_alive()

    if params.get_boolean("set_maxcpus"):
        num_vms = int(len(params.objects("vms")))
        online_cpu = cpu.online_count() * 2 // num_vms
        if (online_cpu % 2) != 0:
            online_cpu += 1
        params["smp"] = online_cpu
        params["vcpu_maxcpus"] = params["smp"]

    params["start_vm"] = "yes"
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()
    wait_for_shutdown_all_vms(vms, wait_for_login_all_vms())
