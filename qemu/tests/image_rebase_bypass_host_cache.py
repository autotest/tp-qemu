import functools
import os

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def coroutine(func):
    """Start coroutine."""

    @functools.wraps(func)
    def start(*args, **kargs):
        cr = func(*args, **kargs)
        cr.send(None)
        return cr

    return start


def run(test, params, env):
    """
    check if qemu-img rebase could bypass host cache.
    1) create snapshot chain image1 -> sn1 -> sn2
    2) rebase sn2 to image1 and check the open syscall that no flag O_DIRECT
    3) create snapshot chain image1 -> sn1 -> sn2
    4) rebase sn2 to image1 with cache mode 'none' and check flag O_DIRECT
    is on.
    """

    def remove_snapshots():
        """Remove snapshots created."""
        while snapshots:
            snapshot = snapshots.pop()
            snapshot.remove()

    def parse_snapshot_chain(target):
        """Parse snapshot chain."""
        image_chain = params["image_chain"].split()
        for snapshot in image_chain[1:]:
            target.send(snapshot)

    @coroutine
    def create_snapshot(target):
        """Create snapshot."""
        while True:
            snapshot = yield
            test.log.debug("create image %s", snapshot)
            snapshot_params = params.object_params(snapshot)
            snapshot = qemu_storage.QemuImg(snapshot_params, root_dir, snapshot)
            fail_on((process.CmdError,))(snapshot.create)(snapshot.params)
            snapshots.append(snapshot)
            target.send(snapshot)

    @coroutine
    def save_file_to_snapshot():
        """Save temporary file to snapshot."""
        sync_bin = params.get("sync_bin", "sync")
        while True:
            snapshot = yield
            test.log.debug("boot vm from image %s", snapshot.tag)
            vm = img_utils.boot_vm_with_images(
                test,
                params,
                env,
                images=(snapshot.tag,),
                vm_name="VM_%s" % snapshot.tag,
            )
            guest_file = params["guest_tmp_filename"] % snapshot.tag
            test.log.debug("create tmp file %s in %s", guest_file, snapshot.tag)
            img_utils.save_random_file_to_vm(vm, guest_file, 2048, sync_bin)
            vm.destroy()

    img_utils.find_strace()
    base = params["image_chain"].split()[0]
    params["image_name_%s" % base] = params["image_name"]
    params["image_format_%s" % base] = params["image_format"]
    root_dir = data_dir.get_data_dir()
    base = qemu_storage.QemuImg(params.object_params(base), root_dir, base)
    trace_events = params["trace_event"].split()

    snapshots = []
    parse_snapshot_chain(create_snapshot(save_file_to_snapshot()))

    strace_log = os.path.join(test.debugdir, "rebase.log")
    top = snapshots[-1]
    test.log.debug("rebase snapshot %s to %s", top.tag, base.tag)
    with img_utils.strace(top, trace_events, strace_log):
        top.base_tag = base.tag
        fail_on((process.CmdError))(top.rebase)(params)

    fail_msg = "'O_DIRECT' is presented in %s with file %s"
    for image in [base] + snapshots:
        if img_utils.check_flag(strace_log, image.image_filename, "O_DIRECT"):
            test.fail(fail_msg % (trace_events, image.image_filename))

    remove_snapshots()
    parse_snapshot_chain(create_snapshot(save_file_to_snapshot()))

    strace_log = os.path.join(test.debugdir, "rebase_bypass.log")
    top = snapshots[-1]
    test.log.debug("rebase snapshot %s to %s in cache mode 'none'", top.tag, base.tag)
    with img_utils.strace(top, trace_events, strace_log):
        top.base_tag = base.tag
        fail_on((process.CmdError))(top.rebase)(
            params, cache_mode="none", source_cache_mode="none"
        )

    fail_msg = "'O_DIRECT' is missing in %s with file %s"
    for image in [base] + snapshots:
        if not img_utils.check_flag(strace_log, image.image_filename, "O_DIRECT"):
            test.fail(fail_msg % (trace_events, image.image_filename))

    remove_snapshots()
