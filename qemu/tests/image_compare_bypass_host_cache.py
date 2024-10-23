import os

from avocado.utils import path, process
from virttest import data_dir, qemu_storage

from provider.qemu_img_utils import check_flag, strace


def run(test, params, env):
    """
    1. convert source image to target image.
    2. compare source image with target image.
    4. check strace output that `O_DIRECT` is off for `open`.
    6. compare with source cache mode `none`.
    7. check strace output that `O_DIRECT` is on.
    """

    def compare_images(source, target, source_cache_mode=None):
        ret = source.compare_to(target, source_cache_mode=source_cache_mode)
        if ret.exit_status == 0:
            test.log.debug("images are identical")
        elif ret.exit_status == 1:
            test.fail("images differ")
        else:
            test.log.error(ret.stdout_text)
            test.error("error in image comparison")

    test.log.debug("check if strace is available")
    try:
        path.find_command("strace")
    except path.CmdNotFoundError as detail:
        raise test.cancel(str(detail))

    root_dir = data_dir.get_data_dir()
    strace_events = params["strace_event"].split()
    source, target = params["images"].split()
    source_params = params.object_params(source)
    source = qemu_storage.QemuImg(source_params, root_dir, source)
    source.create(source_params)
    target_params = params.object_params(target)
    target = qemu_storage.QemuImg(target_params, root_dir, target)

    test.log.debug("Convert image from %s to %s", source.tag, target.tag)
    try:
        source.convert(source_params, root_dir)
    except process.CmdError as detail:
        test.cancel(str(detail))

    strace_output_file = os.path.join(test.debugdir, "compare.log")
    with strace(source, strace_events, strace_output_file):
        compare_images(source, target)
    fail_msg = "'O_DIRECT' is presented in system calls %s" % strace_events
    if check_flag(strace_output_file, source.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if check_flag(strace_output_file, target.image_filename, "O_DIRECT"):
        test.fail(fail_msg)

    strace_output_file = os.path.join(test.debugdir, "compare_bypass.log")
    with strace(source, strace_events, strace_output_file):
        compare_images(source, target, source_cache_mode="none")
    fail_msg = "'O_DIRECT' is not presented in system calls %s" % strace_events
    if not check_flag(strace_output_file, source.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if not check_flag(strace_output_file, target.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    params["remove_image"] = "yes"
