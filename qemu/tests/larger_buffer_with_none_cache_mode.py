import os

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg

from provider.qemu_img_utils import strace


def run(test, params, env):
    """
    qemu-img uses larger output buffer for "none" cache mode.
    1. Create 100M source image with random data via 'dd'.
    2. Trace the system calls while converting the source image to the
       a qcow2 target image, and check the maxim result of pwrite/pwrite64
       should be 2M.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    src_image = params["images"]
    tgt_image = params["convert_target"]
    root_dir = data_dir.get_data_dir()
    source = QemuImg(params.object_params(src_image), root_dir, src_image)
    strace_event = params["strace_event"]
    strace_events = strace_event.split()
    strace_output_file = os.path.join(test.debugdir, "convert_with_none.log")
    src_filename = source.image_filename
    process.run("dd if=/dev/urandom of=%s bs=1M count=100" % src_filename)
    test.log.debug(
        "Convert from %s to %s with cache mode none, strace log: " "%s.",
        src_filename,
        tgt_image,
        strace_output_file,
    )
    with strace(source, strace_events, strace_output_file, trace_child=True):
        fail_on((process.CmdError,))(source.convert)(
            params.object_params(src_image), root_dir, cache_mode="none"
        )

    test.log.debug(
        "Check whether the max size of %s syscall is 2M in %s.",
        strace_event,
        strace_output_file,
    )
    with open(strace_output_file) as fd:
        for line in fd.readlines():
            if int(line.split()[-1]) == 2097152:
                break
        else:
            test.fail(
                "The max size of '%s' is not 2M, check '%s' please.",
                strace_event,
                strace_output_file,
            )

    params["images"] += " " + tgt_image
