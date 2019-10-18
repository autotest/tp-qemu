import logging
import os

from avocado import fail_on
from avocado import TestCancel
from avocado.utils import path
from avocado.utils import process
from provider.qemu_img_utils import strace
from virttest import data_dir
from virttest import qemu_storage
from virttest import storage


def run(test, params, env):
    """
    1. convert image with both default cache mode.
    2. check strace output that `O_DIRECT` is off for `open`.
    3. convert image with cache mode `none` for both source and dest images.
    4. check strace output that `O_DIRECT` is on for `open`.
    """
    def check_flags(strace_output_file, filename, flag, negative=False):
        """Check flag is presented in calls related to filename."""
        logging.debug("Check strace output from file %s", strace_output_file)
        with open(strace_output_file) as fd:
            logging.debug("syscalls related to %s", filename)
            lines = [l for l in fd if filename in l]
            for line in lines:
                logging.debug(line.strip())
            if any(flag in line for line in lines) is negative:
                msg = "%s is%spresented." % \
                    (flag, " " if negative else " not ")
                test.fail(msg)

    logging.debug("Check if strace is available")
    try:
        path.find_command("strace")
    except path.CmdNotFoundError as detail:
        raise TestCancel(str(detail))

    root_dir = data_dir.get_data_dir()
    strace_events = params["strace_event"].split()
    image = params["images"]
    image_params = params.object_params(image)
    image = qemu_storage.QemuImg(image_params, root_dir, image)
    convert_target1, convert_target2 = params["convert_target"].split()

    strace_output_file = os.path.join(test.debugdir,
                                      "convert_to_%s.log" % convert_target1)
    image_params["convert_target"] = convert_target1
    logging.debug("Convert image from %s to %s, strace log: %s", image.tag,
                  convert_target1, strace_output_file)
    fail_on((process.CmdError,))(
        strace(trace_events=strace_events, output_file=strace_output_file)(
            image.convert))(image_params, root_dir)
    convert_target1_filename = storage.get_image_filename(
        params.object_params(convert_target1), root_dir)
    check_flags(strace_output_file, image.image_filename,
                "O_DIRECT", negative=True)
    check_flags(strace_output_file, convert_target1_filename,
                "O_DIRECT", negative=True)

    strace_output_file = os.path.join(test.debugdir,
                                      "convert_to_%s.log" % convert_target2)
    image_params["convert_target"] = convert_target2
    logging.debug(("Convert image from %s to %s with cache mode "
                   "'none', strace log: %s"), image.tag, convert_target2,
                  strace_output_file)
    fail_on((process.CmdError,))(
        strace(trace_events=strace_events, output_file=strace_output_file)(
            image.convert))(image_params, root_dir, cache_mode="none",
                            source_cache_mode="none")
    convert_target2_filename = storage.get_image_filename(
        params.object_params(convert_target2), root_dir)
    check_flags(strace_output_file, image.image_filename, "O_DIRECT")
    check_flags(strace_output_file, convert_target2_filename, "O_DIRECT")
    params["images"] += params["convert_target"]
