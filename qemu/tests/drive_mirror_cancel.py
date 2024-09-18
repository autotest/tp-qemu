from avocado.utils import process
from virttest import error_context, utils_misc

from qemu.tests import drive_mirror


@error_context.context_aware
def run_drive_mirror_cancel(test, params, env):
    """
    Test block mirroring functionality

    1). boot vm then mirror $source_image to nfs/iscsi target
    2). block nfs/iscsi serivce port via iptables rules
    3). cancel block job and check it not cancel immedicatly
    4). flush iptables chain then check job canceled in 10s

    """
    tag = params.get("source_image", "image1")
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    try:
        mirror_test.start()
        error_context.context("Block network connection with iptables", test.log.info)
        process.run(params["start_firewall_cmd"], shell=True)
        bg = utils_misc.InterruptedThread(mirror_test.cancel)
        bg.start()
        job = mirror_test.get_status()
        if job.get("type", "0") != "mirror":
            test.fail("Job cancel immediacatly")
        error_context.context("Cleanup rules in iptables", test.log.info)
        process.run(params["stop_firewall_cmd"], shell=True)
        bg.join(timeout=int(params["cancel_timeout"]))
    finally:
        mirror_test.vm.destroy()
        mirror_test.clean()
