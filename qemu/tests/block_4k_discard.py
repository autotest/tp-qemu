"""Attach the host 4k disk but QEMU is exposing a 512 to the Guest.
Test the unaligned discard operation on the disk."""

import re

from avocado.utils import process
from virttest import env_process, error_context
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Qemu send unaligned discard test:
    1) Load scsi_debug module with sector_size=4096
    2) Boot guest with scsi_debug emulated disk as extra data disk
    3) Login the guest and execute blkdiscard commands on the data disk
    4) The unaligned discard command succeeds on the virtio or scsi-hd disk
       Fails on the pass-through device

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _execute_io_in_guest(serial):
        drive = get_linux_drive_path(session, serial)
        if not drive:
            test.fail("Can not find disk by {}".format(serial))

        io_cmd_num = params.get_numeric("guest_io_cmd_number")
        results_raw = params.get(
            "expected_results", params.get("expected_resultes", "")
        ).split()
        if len(results_raw) != io_cmd_num:
            test.cancel(
                "Mismatch: io_cmd_number={} but expected_results has {} items".format(
                    io_cmd_num, len(results_raw)
                )
            )
        for i in range(io_cmd_num):
            cmd = params["guest_io_cmd{}".format(i)].format(drive)
            try:
                expected = int(results_raw[i])
            except ValueError:
                test.fail(
                    "Non-integer expected_results[{}]={!r}".format(i, results_raw[i])
                )
            rc, out = session.cmd_status_output(cmd)
            logger.debug(
                "guest_io_cmd%d: rc=%s, cmd=%r, out=%s", i, rc, cmd, out.strip()
            )
            if rc != expected:
                test.fail(
                    "Unexpected rc=%s:%s, cmd=%r, out=%s"
                    % (rc, expected, cmd, out.strip())
                )

    def _get_scsi_debug_disk():
        cmd = "lsscsi -g -w -s | grep scsi_debug || true"
        out = (
            process.system_output(cmd, shell=True, ignore_status=True).decode().strip()
        )
        logger.info("Host cmd output '%s'", out)
        if not out:
            test.log.warning("Can not find scsi_debug disk")
            return
        disk_info = []
        for line in out.splitlines():
            tokens = line.split()
            path = next((t for t in tokens if t.startswith("/dev/sd")), None)
            sg = next((t for t in tokens if t.startswith("/dev/sg")), None)
            size = next(
                (t for t in tokens if re.search(r"(?i)\d+(?:\.\d+)?[KMGTPE]B$", t)),
                None,
            )
            wwn_tok = next((t for t in tokens if t.startswith("0x")), None)
            wwn = wwn_tok.split("0x", 1)[1]
            if not (path and sg):
                logger.warning("Unable to parse scsi_debug line: %s", line)
                continue
            disk_info.append(
                {"path": path, "sg": sg, "wwn": wwn, "size": size, "all": line}
            )
        if not disk_info:
            test.fail("Parsed no scsi_debug devices from lsscsi output")
        return disk_info

    logger = test.log
    vm = None
    disk_wwn = None
    if params.get("get_scsi_device") == "yes":
        scsi_debug_devs = _get_scsi_debug_disk()
        if scsi_debug_devs:
            dev = scsi_debug_devs[0]
            disk_wwn = dev["wwn"]
            if params["drive_format_stg1"] == "scsi-generic":
                params["image_name_stg1"] = dev["sg"]
            else:
                params["image_name_stg1"] = dev["path"]
        else:
            test.fail("Can not find scsi_debug devices")
    try:
        if params.get("not_preprocess", "no") == "yes":
            logger.debug("Ready boot VM : %s", params["images"])
            env_process.process(
                test,
                params,
                env,
                env_process.preprocess_image,
                env_process.preprocess_vm,
            )

        logger.info("Get the main VM")
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        timeout = params.get_numeric("timeout", 300)
        session = vm.wait_for_login(timeout=timeout)
        serial = params.get("serial_stg1")
        identifier = serial or disk_wwn
        if not identifier:
            test.fail("Missing serial and no WWN parsed; cannot locate drive in guest")
        _execute_io_in_guest(identifier)

        logger.info("Ready to destroy vm")
        vm.destroy()
    finally:
        if vm and vm.is_alive():
            vm.destroy(gracefully=False)
