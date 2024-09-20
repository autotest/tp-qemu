import random
import re
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test failover path on SCSI passthrough with underlying DM-multipath device.

    Step:
     1. Build multipath device on host.
     2. Boot a guest with passthrough path.
     3. Access guest then do io on the data disk.
     4. Check vm status.
     5. Alternately close a path every 10 seconds on host
     6. Check vm status
     7. Offline two path and check status
     8. Online one path and check status


    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 240))
    get_id_cmd = params.get("get_id_cmd")
    get_mpath_cmd = params.get("get_mpath_cmd")
    get_mdev_cmd = params.get("get_mdev_cmd")
    get_tdev_cmd = params.get("get_tdev_cmd")
    set_path_cmd = params.get("set_path_cmd")
    cmd_dd = params.get("cmd_dd")
    params.get("post_cmd")
    repeat_time = params.get_numeric("repeat_time")
    id = process.getoutput(get_id_cmd).strip()
    get_mpath_cmd = get_mpath_cmd % (id, id)
    mpath = process.getoutput(get_mpath_cmd).strip()
    params["image_name_stg0"] = "/dev/mapper/%s" % mpath
    params["start_vm"] = "yes"
    time.sleep(5)
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    session = vm.wait_for_login(timeout=timeout)
    out = session.cmd_output(get_tdev_cmd)
    cmd_dd = cmd_dd % out
    error_context.context("Do dd writing test on the data disk.", test.log.info)
    session.sendline(cmd_dd)
    if not vm.monitor.verify_status("running"):
        test.fail("Guest did not run after dd")
    get_mdev_cmd = get_mdev_cmd % id
    o = process.getoutput(get_mdev_cmd)
    mdev = re.findall(r"sd.", o, re.M)
    error_context.context("Alternately close a path every 10 seconds on host")
    for dev in mdev:
        process.getoutput(set_path_cmd % ("running", dev))
    for i in range(repeat_time):
        for dev in mdev:
            process.getoutput(set_path_cmd % ("offline", dev))
            time.sleep(5)
            process.getoutput("multipath -l")
            time.sleep(10)
            process.getoutput(set_path_cmd % ("running", dev))
            time.sleep(5)
            process.getoutput("multipath -l")
            time.sleep(1)
        time.sleep(1)
    for dev in mdev:
        process.getoutput(set_path_cmd % ("running", dev))
    if not utils_misc.wait_for(lambda: vm.monitor.verify_status("running"), timeout=20):
        test.fail("Guest did not run after change path")
    for dev in mdev:
        process.getoutput(set_path_cmd % ("offline", dev))
    if not utils_misc.wait_for(lambda: vm.monitor.verify_status("paused"), timeout=20):
        test.fail("Guest did not pause after offline")
    dev = random.choice(mdev)
    process.getoutput(set_path_cmd % ("running", dev))
    if vm.monitor.verify_status("paused"):
        vm.monitor.send_args_cmd("c")
    if not utils_misc.wait_for(lambda: vm.monitor.verify_status("running"), timeout=20):
        test.fail("Guest did not run after online")
    session.close()
    vm.destroy(gracefully=True)
