import os
import random
import re

from avocado.core import exceptions
from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_numeric


@error_context.context_aware
def run(test, params, env):
    """
    The following testing scenarios are covered:
        1) boot_with_debug
        2) boot_with_local_image
        3) boot_with_remote_images
    Please refer to the specific case for details

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _get_data_disk(session):
        """Get the data disk."""
        extra_params = params["blk_extra_params_%s" % params["images"].split()[-1]]
        drive_id = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
        return utils_misc.get_linux_drive_path(session, drive_id)

    def _write_disk(session):
        disk_op_cmd = params["disk_op_cmd"]
        if disk_op_cmd:
            disk = _get_data_disk(session)
            session.cmd(disk_op_cmd.format(disk=disk))

    def _get_memory(pid):
        cmd = "ps -o vsz,rss -p %s | tail -n1" % pid
        out = process.system_output(cmd, shell=True).split()
        return [int(i) for i in out]

    def boot_with_debug():
        """
        Boot up a guest with debug level
            1. from 'debug_level_low' to 'debug_level_high'
            2. less than 'debug_level_low'
            3. greater than 'debug_level_high'
        VM can start up without any error
        """
        # valid debug levels
        low = int(params["debug_level_low"])
        high = int(params["debug_level_high"])
        levels = [i for i in range(low, high + 1)]

        # invalid debug levels: [low-100, low) and [high+1, high+100)
        levels.extend(
            [
                random.choice(range(low - 100, low)),
                random.choice(range(high + 1, high + 100)),
            ]
        )

        for level in levels:
            logfile = utils_misc.get_log_filename("debug.level%s" % level)
            params["gluster_debug"] = level
            params["gluster_logfile"] = logfile
            test.log.info("debug level: %d, log: %s", level, logfile)

            try:
                env_process.preprocess_vm(test, params, env, params["main_vm"])
                vm = env.get_vm(params["main_vm"])
                vm.verify_alive()
                if not os.path.exists(logfile):
                    raise exceptions.TestFail(
                        "Failed to generate log file %s" % logfile
                    )
                os.remove(logfile)
            finally:
                vm.destroy()

    def boot_with_local_image():
        """
        Boot up a guest with a remote storage system image
            as well as a local filesystem image
        VM can start up without any error
        """
        try:
            session = None
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()
            tm = float(params.get("login_timeout", 240))
            session = vm.wait_for_login(timeout=tm)

            _write_disk(session)
        finally:
            if session:
                session.close()
            vm.destroy()

    def boot_with_remote_images():
        """
        Boot up a guest with only one remote image,
            record memory consumption(vsz, rss)
        Boot up a guest with 4 remote images,
            record memory consumption(vsz, rss)
        The memory increased should not be greater than 'memory_diff'
        """
        try:
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()

            # get vsz, rss when booting with one remote image
            single_img_memory = _get_memory(vm.get_pid())
            if not single_img_memory:
                raise exceptions.TestError(
                    "Failed to get memory when " "booting with one remote image."
                )
            test.log.debug(
                "memory consumption(only one remote image): %s", single_img_memory
            )

            vm.destroy()

            for img in params["images"].split()[1:]:
                params["boot_drive_%s" % img] = "yes"
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()

            # get vsz, rss when booting with 4 remote image
            multi_img_memory = _get_memory(vm.get_pid())
            if not multi_img_memory:
                raise exceptions.TestError(
                    "Failed to get memory when booting" " with several remote images."
                )
            test.log.debug(
                "memory consumption(total 4 remote images): %s", multi_img_memory
            )

            diff = int(
                float(
                    utils_numeric.normalize_data_size(
                        params["memory_diff"], order_magnitude="K"
                    )
                )
            )
            mem_diffs = [i - j for i, j in zip(multi_img_memory, single_img_memory)]
            if mem_diffs[0] > diff:
                raise exceptions.TestFail(
                    "vsz increased '%s', which was more than '%s'"
                    % (mem_diffs[0], diff)
                )
            if mem_diffs[1] > diff:
                raise exceptions.TestFail(
                    "rss increased '%s', which was more than '%s'"
                    % (mem_diffs[1], diff)
                )
        finally:
            vm.destroy()

    tc = params["scenario"]
    fun = locals()[tc]
    fun()
