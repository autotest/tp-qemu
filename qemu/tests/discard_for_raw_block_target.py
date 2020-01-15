import logging
import os

from provider.qemu_img_utils import strace

from avocado import fail_on
from avocado.utils import process

from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img supports 'discard' for raw block target images.

    1. Create source image via dd with all zero.
    2. Modprobe a 1G scsi_debug disk with writesame_16 mode.
    3. Trace the system calls while converting the zero image to the
       scsi_debug block device, then check whether 'fallocate' system call
       works in the log.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def check_output(strace_event, strace_output, match_str):
        """Check whether the value is good in the output file."""
        logging.debug("Check the output file '%s'." % strace_output)
        with open(strace_output) as fd:
            if match_str not in fd.read():
                test.fail("The system call of '%s' is not right, "
                          "check '%s' for more details."
                          % (strace_event, strace_output))

    src_image = params["images"]
    root_dir = data_dir.get_data_dir()
    source = QemuImg(params.object_params(src_image), root_dir, src_image)
    strace_event = params["strace_event"]
    strace_events = strace_event.split()
    strace_output_file = os.path.join(test.debugdir,
                                      "convert_to_block.log")

    source.create(source.params)
    # Generate the target scsi block file.
    tgt_disk = process.system_output("lsscsi | grep '%s' | awk '{print $NF}'"
                                     % params["scsi_mod"], shell=True).decode()
    params["image_name_target"] = tgt_disk

    logging.debug("Convert from %s to %s with cache mode none, strace log: %s."
                  % (source.image_filename, tgt_disk, strace_output_file))
    with strace(source, strace_events, strace_output_file, trace_child=True):
        fail_on((process.CmdError,))(source.convert)(
            params.object_params(src_image), root_dir, cache_mode="none")

    check_output(strace_event, strace_output_file,
                 "FALLOC_FL_PUNCH_HOLE, 0, 1073741824")
