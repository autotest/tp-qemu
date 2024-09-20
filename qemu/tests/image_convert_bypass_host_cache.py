import os

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage, storage

from provider.qemu_img_utils import check_flag, find_strace, strace


def run(test, params, env):
    """
    1. convert image with both default cache mode.
    2. check strace output that `O_DIRECT` is off for `open`.
    3. convert image with cache mode `none` for both source and dest images.
    4. check strace output that `O_DIRECT` is on for `open`.
    """

    find_strace()

    root_dir = data_dir.get_data_dir()
    strace_events = params["strace_event"].split()
    image = params["images"]
    image_params = params.object_params(image)
    image = qemu_storage.QemuImg(image_params, root_dir, image)
    convert_target1, convert_target2 = params["convert_target"].split()

    strace_output_file = os.path.join(
        test.debugdir, "convert_to_%s.log" % convert_target1
    )
    image_params["convert_target"] = convert_target1
    test.log.debug(
        "Convert image from %s to %s, strace log: %s",
        image.tag,
        convert_target1,
        strace_output_file,
    )

    with strace(image, strace_events, strace_output_file):
        fail_on((process.CmdError,))(image.convert)(image_params, root_dir)

    convert_target1_filename = storage.get_image_filename(
        params.object_params(convert_target1), root_dir
    )
    fail_msg = "'O_DIRECT' is presented in system calls %s" % strace_events
    if check_flag(strace_output_file, image.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if check_flag(strace_output_file, convert_target1_filename, "O_DIRECT"):
        test.fail(fail_msg)

    strace_output_file = os.path.join(
        test.debugdir, "convert_to_%s.log" % convert_target2
    )
    image_params["convert_target"] = convert_target2
    test.log.debug(
        ("Convert image from %s to %s with cache mode " "'none', strace log: %s"),
        image.tag,
        convert_target2,
        strace_output_file,
    )

    with strace(image, strace_events, strace_output_file):
        fail_on((process.CmdError,))(image.convert)(
            image_params, root_dir, cache_mode="none", source_cache_mode="none"
        )

    convert_target2_filename = storage.get_image_filename(
        params.object_params(convert_target2), root_dir
    )
    fail_msg = "'O_DIRECT' is not presented in system calls %s" % strace_events
    if not check_flag(strace_output_file, image.image_filename, "O_DIRECT"):
        test.fail(fail_msg)
    if not check_flag(strace_output_file, convert_target2_filename, "O_DIRECT"):
        test.fail(fail_msg)
    params["images"] += params["convert_target"]
