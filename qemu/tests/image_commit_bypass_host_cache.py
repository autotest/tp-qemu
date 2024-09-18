import os

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage, virt_vm

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    1. create snapshot base->sn
    2. write to snapshot sn
    3. commit sn to base with default cache mode.
    4. check strace output that `O_DIRECT` is off for `open`.
    5. write to snapshot sn
    6. commit sn to base with cache=none.
    7. check strace output that `O_DIRECT` is on.
    """
    img_utils.find_strace()

    root_dir = data_dir.get_data_dir()
    trace_events = params["trace_events"].split()
    sync_bin = params.get("sync_bin", "sync")
    images = params["images"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]

    base, sn = (
        qemu_storage.QemuImg(params.object_params(tag), root_dir, tag) for tag in images
    )
    try:
        sn.create(sn.params)
        vm = img_utils.boot_vm_with_images(test, params, env, (sn.tag,))
    except (process.CmdError, virt_vm.VMCreateError) as detail:
        test.fail(str(detail))

    guest_file = params["guest_tmp_filename"]
    test.log.debug("Create tmp file %s in image %s", guest_file, sn.image_filename)
    img_utils.save_random_file_to_vm(vm, guest_file, 2048 * 100, sync_bin)
    vm.destroy()

    strace_log = os.path.join(test.debugdir, "commit.log")
    test.log.debug("commit snapshot, strace log %s", strace_log)
    with img_utils.strace(sn, trace_events, strace_log):
        fail_on((process.CmdError,))(sn.commit)()
    fail_msg = "'O_DIRECT' is presented in system calls %s" % trace_events
    if img_utils.check_flag(strace_log, base.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if img_utils.check_flag(strace_log, sn.image_filename, "O_DIRECT"):
        test.fail(fail_msg)

    strace_log = os.path.join(test.debugdir, "commit_bypass.log")
    test.log.debug("commit snapshot with cache 'none', strace log: %s", strace_log)
    with img_utils.strace(sn, trace_events, strace_log):
        fail_on((process.CmdError,))(sn.commit)(cache_mode="none")
    fail_msg = "'O_DIRECT' is missing in system calls %s" % trace_events
    if not img_utils.check_flag(strace_log, base.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if not img_utils.check_flag(strace_log, sn.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
