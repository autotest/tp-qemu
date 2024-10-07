import logging
import time

from virttest import data_dir, error_context, qemu_monitor, utils_test
from virttest.vt_vmm.api import vmm

LOG = logging.getLogger("avocado." + __name__)


@error_context.context_aware
def run(test, params, env):
    """
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    timeout = float(params.get("login_timeout", 240))
    vms = env.get_all_vms()
    for vm in vms:
        # error_context.context("Try to log into guest '%s'." % vm.name,
        #                       test.log.info)
        # session = vm.wait_for_serial_login(timeout=timeout, status_check=False)
        # vm_ver = session.cmd_output("cat /proc/version")
        # LOG.info("Version of %s: %s", vm.name, vm_ver)
        # cpus_info = vm.monitor.info("cpus", debug=False)
        # LOG.info("CPU info of %s: %s", vm.name, cpus_info)
        #
        # if params.get("reboot") == "yes":
        #     reboot_method = params.get("reboot_method", "shell")
        #     session = vm.reboot(session, reboot_method, 0, timeout, True)
        #     vm_info = session.cmd_output("uname -a")
        #     LOG.info("Info %s: %s", vm.name, vm_info)
        #     # blocks_info = vm.monitor.info('block') # ERROR: int exceeds XML-RPC limits
        #     # LOG.info("Block info of %s: %s", vm.name, blocks_info)
        #     vm.pause()
        #     vm.resume()
        #     session.close()

        vm_params = params.object_params(vm.name)
        src_node = vm_params.get("vm_node")
        dst_node = vm_params.get("mig_dest_node")
        if dst_node:
            error_context.context(
                f"Migrating the guest {vm.name} from {src_node} to {dst_node}",
                test.log.info,
            )
            vm.migrate(
                timeout=3600,
                protocol="tcp",
                cancel_delay=None,
                offline=False,
                stable_check=False,
                clean=True,
                save_path=data_dir.get_tmp_dir(),
                dest_host=dst_node,
                remote_port=None,
                not_wait_for_migration=False,
                fd_src=None,
                fd_dst=None,
                migration_exec_cmd_src=None,
                migration_exec_cmd_dst=None,
                env=None,
                migrate_capabilities=None,
                mig_inner_funcs=None,
                migrate_parameters=(None, None),
            )

            error_context.context(
                "Try to log into guest '%s'." % vm.name, test.log.info
            )
            session = vm.wait_for_serial_login(timeout=timeout, status_check=False)
            vm_ver = session.cmd_output("cat /proc/version")
            LOG.info("Version of %s: %s", vm.name, vm_ver)

            cpus_info = vm.monitor.info("cpus", debug=False)
            LOG.info("CPU info of %s: %s", vm.name, cpus_info)
