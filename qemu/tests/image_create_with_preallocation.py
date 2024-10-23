import json
import os

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Check parameter preallocation when creating an image.
    1. Create a qcow2 image with preallocation=off, full, falloc, metadata.
    2. Create a raw image with preallocation=off, full, falloc.
    3. Create a luks image with preallocation=off, full, falloc.
    4. check points:
    4.1 preallocation=off
    Image create successfully, the actual_size is less than specified size.
    4.2 preallocation=full
    Image create successfully, the actual_size is greater than or equal to
    specified size.
    (It's normal because of the temporary predictive preallocation of XFS.)
    4.3 preallocation=falloc
    Image create successfully, invoked fallocate system call,
    the actual_size is greater than or equal to specified size.
    (It's normal because of the temporary predictive preallocation of XFS.)
    4.4 preallocation=metadata
    Image create successfully, the actual_size is less than specified size.

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def check_fallocate_syscall(trace_event):
        """
        check whether invoke fallocate system call
        when creating an image with preallocation=falloc
        """
        strace_log = os.path.join(test.debugdir, "fallocate.log")
        with img_utils.strace(img_stg, trace_event.split(), strace_log, True):
            fail_on((process.CmdError,))(img_stg.create)(image_stg_params)
        with open(strace_log) as fd:
            if trace_event not in fd.read():
                test.fail(
                    "Not invoked fallocate system call when "
                    "creating an image with preallocation=falloc"
                )

    def check_actual_size_field():
        """
        check whether 'actual-size' field from qemu-img info is as expected.
        """
        cmd_result = img_stg.info(output="json")
        actual_size = int(params["actual_size"])
        info = json.loads(cmd_result)
        if params["preallocated_stg"] in ["full", "falloc"]:
            if info["actual-size"] < actual_size:
                test.fail(
                    "The 'actual-size' field from qemu-img info "
                    "is not greater than or equal to %s. "
                    "The actual output is %s" % (actual_size, cmd_result)
                )
        elif params["preallocated_stg"] in ["off", "metadata"]:
            if info["actual-size"] >= actual_size:
                test.fail(
                    "The 'actual-size' field from qemu-img info "
                    "is not less than %s. The actual output is %s"
                    % (actual_size, cmd_result)
                )

    trace_event = params.get("trace_event")
    image_stg = params["images"]
    root_dir = data_dir.get_data_dir()
    image_stg_params = params.object_params(image_stg)
    img_stg = qemu_storage.QemuImg(image_stg_params, root_dir, image_stg)
    if trace_event:
        check_fallocate_syscall(trace_event)
    else:
        img_stg.create(image_stg_params)
    check_actual_size_field()
