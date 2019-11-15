"""qemu-img related functions."""
import avocado
import contextlib
import logging
import tempfile

from virttest import data_dir
from virttest import env_process
from virttest import qemu_storage
from virttest import utils_misc

from avocado.utils import process


def boot_vm_with_images(test, params, env, images=None, vm_name=None):
    """Boot VM with images specified."""
    params = params.copy()
    # limit to those specified in images
    if images:
        images = " ".join(images)
        params["images"] = images
    params["start_vm"] = "yes"
    vm_name = vm_name or params["main_vm"]
    logging.debug("Boot vm %s with images: %s", vm_name, params["images"])
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    return vm


def qemu_img_compare(params, image0, image1, strict=False, force_share=False):
    """qemu-img compare command wrapper function."""
    image0_params = params.object_params(image0)
    image1_params = params.object_params(image1)
    root_dir = data_dir.get_data_dir()
    image0 = qemu_storage.QemuImg(image0_params, root_dir, image0)
    image1 = qemu_storage.QemuImg(image1_params, root_dir, image1)
    compare_cmd = ["qemu-img compare"]
    secret_objects = image0._secret_objects + image1._secret_objects
    if secret_objects:
        compare_cmd.append(" ".join(secret_objects))
    if strict:
        compare_cmd.append("-s")
    if force_share:
        compare_cmd.append("-U")
    filename0, filename1 = image0.image_filename, image1.image_filename
    if image0.encryption_config.key_secret:
        filename0 = "'%s'" % qemu_storage.get_image_json(
            image0.tag, image0_params, root_dir)
    if image1.encryption_config.key_secret:
        filename1 = "'%s'" % qemu_storage.get_image_json(
            image1.tag, image1_params, root_dir)
    compare_cmd.extend((filename0, filename1))
    logging.debug("Compare %s with %s, strict: %s",
                  filename0, filename1, strict)
    result = process.run(" ".join(compare_cmd), ignore_status=True, shell=True)
    if result.exit_status == 0:
        logging.debug(result.stdout_text)
    else:
        logging.error(result.stdout_text)
        if result.exit_status == 1:
            raise avocado.TestFail(result.stdout_text)
        raise avocado.TestError(result.stdout_text)


def save_random_file_to_vm(vm, save_path, count, sync_bin, blocksize=512):
    """
    Save a random file to vm.

    :param vm: vm
    :param save_path: file path saved in vm
    :param count: block count
    :param sync_bin: sync binary path
    :param blocksize: block size, default 512
    """
    session = vm.wait_for_login(timeout=360)
    dd_cmd = "dd if=/dev/urandom of=%s bs=%s count=%s conv=fsync"
    with tempfile.NamedTemporaryFile() as f:
        dd_cmd = dd_cmd % (f.name, blocksize, count)
        process.run(dd_cmd, shell=True, timeout=360)
        vm.copy_files_to(f.name, save_path)
    sync_bin = utils_misc.set_winutils_letter(session, sync_bin)
    status, out = session.cmd_status_output(sync_bin, timeout=240)
    if status:
        raise EnvironmentError("Fail to execute %s: %s" % (sync_bin, out))
    session.close()


@avocado.fail_on(exceptions=(ValueError,))
def check_md5sum(filepath, md5sum_bin, session, md5_value_to_check=None):
    """Check md5sum value of the file specified."""
    md5cmd = "%s %s" % (md5sum_bin, filepath)
    status, out = session.cmd_status_output(md5cmd, timeout=240)
    if status:
        raise EnvironmentError("Fail to get md5 value of file: %s" % filepath)
    md5_value = out.split()[0]
    logging.debug("md5sum value of %s: %s", filepath, md5_value)
    if md5_value_to_check and md5_value != md5_value_to_check:
        raise ValueError("md5 values mismatch, got: %s, expected: %s" %
                         (md5_value, md5_value_to_check))
    return md5_value


@contextlib.contextmanager
def strace(image, trace_events=None, output_file=None, trace_child=False):
    """
    Add strace to trace image related operations.

    :param image: image object
    :param trace_events: events list to trace
    :param output_file: if presented, redirect the output to file
    :param trace_child: True to enable tracing child processes with -f
    """
    image_cmd = image.image_cmd
    strace_prefix = ["strace"]
    if trace_events:
        strace_prefix.extend(("-e", ",".join(trace_events)))
    if output_file:
        strace_prefix.extend(("-o", output_file))
    if trace_child:
        strace_prefix.append("-f")
    strace_prefix = " ".join(strace_prefix)
    image.image_cmd = strace_prefix + " " + image_cmd
    try:
        yield
    finally:
        image.image_cmd = image_cmd


def check_flag(strace_log, target_file, flag):
    """
    Check if flag is presented in the syscalls related to file.

    :param strace_log: strace log file
    :param target_file: syscall-related file
    :param flag: flag to check
    """
    logging.debug("Check strace output: %s", strace_log)
    with open(strace_log) as fd:
        logging.debug("syscalls related to %s", target_file)
        lines = [l for l in fd if target_file in l]
        for line in lines:
            logging.debug(line.strip())
        return any(flag in line for line in lines)
