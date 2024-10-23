"""
Configurable on-guest dd test.

:author: Lukas Doktor <ldoktor@redhat.com>
:copyright: 2012 Red Hat, Inc.
"""

import os
import re

import aexpect
from virttest import error_context, utils_disk, utils_misc, utils_numeric

try:
    from itertools import zip_longest as zip_longest
except Exception:
    from itertools import izip_longest as zip_longest


@error_context.context_aware
def run(test, params, env):
    """
    Executes dd with defined parameters and checks the return number and output

    Test steps:
    1). wait guest boot up
    2). run dd command in guest with special params(eg. oflag, bs and so on)
    3). check command exit stauts and output
    """

    def _get_file(filename, select, test=test):
        """Picks the actual file based on select value"""
        if filename == "NULL":
            return "/dev/null"
        elif filename == "ZERO":
            return "/dev/zero"
        elif filename == "RANDOM":
            return "/dev/random"
        elif filename == "URANDOM":
            return "/dev/urandom"
        elif filename in params.objects("images"):
            drive_id = params["blk_extra_params_%s" % filename].split("=")[1]
            drive_path = utils_misc.get_linux_drive_path(session, drive_id)
            if drive_path:
                return drive_path
            test.error("Failed to get '%s' drive path" % filename)
        else:
            # get all matching filenames
            try:
                disks = sorted(session.cmd("ls -1d %s" % filename).split("\n"))
            except aexpect.ShellCmdError:  # No matching file (creating new?)
                disks = [filename]
            if disks[-1] == "":
                disks = disks[:-1]
            try:
                return disks[select]
            except IndexError:
                err = (
                    "Incorrect cfg: dd_select out of the range (disks=%s,"
                    " select=%s)" % (disks, select)
                )
                test.log.error(err)
                test.error(err)

    def _check_disk_partitions_number():
        """Check the data disk partitions number."""
        del partitions[:]  # pylint: disable=E0606
        partitions.extend(
            re.findall(
                r"%s\d+" % dev_id, " ".join(utils_disk.get_linux_disks(session, True))
            )
        )
        return len(partitions) == bs_count

    vm = env.get_vm(params["main_vm"])
    timeout = int(params.get("login_timeout", 360))

    error_context.context("Wait guest boot up", test.log.info)
    session = vm.wait_for_login(timeout=timeout)

    dd_keys = [
        "dd_if",
        "dd_of",
        "dd_bs",
        "dd_count",
        "dd_iflag",
        "dd_oflag",
        "dd_skip",
        "dd_seek",
    ]

    dd_params = {key: params.get(key, None) for key in dd_keys}
    if dd_params["dd_bs"] is None:
        dd_params["dd_bs"] = "512"
    dd_params["dd_bs"] = dd_params["dd_bs"].split()
    bs_count = len(dd_params["dd_bs"])

    dd_timeout = int(params.get("dd_timeout", 180))
    dd_output = params.get("dd_output", "")
    dd_stat = int(params.get("dd_stat", 0))

    dev_partitioned = []
    for arg in ["dd_if", "dd_of"]:
        filename = dd_params[arg]
        path = _get_file(filename, int(params.get("%s_select" % arg, "-1")))
        if bs_count > 1 and filename in params.objects("images"):
            psize = float(
                utils_numeric.normalize_data_size(params.get("partition_size", "2G"))
            )
            start = 0.0
            dev_id = os.path.split(path)[-1]
            dev_partitioned.append(dev_id)

            utils_disk.create_partition_table_linux(session, dev_id, "gpt")
            for i in range(bs_count):
                utils_disk.create_partition_linux(
                    session, dev_id, "%fM" % psize, "%fM" % start
                )
                start += psize

            partitions = []
            if not utils_misc.wait_for(_check_disk_partitions_number, 30, step=3.0):
                test.error("Failed to get %d partitions on %s." % (bs_count, dev_id))
            partitions.sort()
            dd_params[arg] = [path.replace(dev_id, part) for part in partitions]
        else:
            dd_params[arg] = [path]

    if bs_count > 1 and not dev_partitioned:
        test.error(
            "with multiple bs, either dd_if or \
                   dd_of must be a block device"
        )

    dd_cmd = ["dd"]
    for key in dd_keys:
        value = dd_params[key]
        if value is None:
            continue
        arg = key.split("_")[-1]
        if key in ["dd_if", "dd_of", "dd_bs"]:
            part = "%s=%s" % (arg, "{}")
        else:
            part = "%s=%s" % (arg, value)
        dd_cmd.append(part)
    dd_cmd = " ".join(dd_cmd)

    remaining = [dd_params[key] for key in ["dd_if", "dd_of", "dd_bs"]]
    if len(dd_params["dd_if"]) != bs_count:
        fillvalue = dd_params["dd_if"][-1]
    else:
        fillvalue = dd_params["dd_of"][-1]
    cmd = [dd_cmd.format(*t) for t in zip_longest(*remaining, fillvalue=fillvalue)]
    cmd = " & ".join(cmd)
    test.log.info("Using '%s' cmd", cmd)

    try:
        error_context.context("Execute dd in guest", test.log.info)
        try:
            (stat, out) = session.cmd_status_output(cmd, timeout=dd_timeout)
        except aexpect.ShellTimeoutError:
            err = "dd command timed-out (cmd='%s', timeout=%d)" % (cmd, dd_timeout)
            test.fail(err)
        except aexpect.ShellCmdError as details:
            stat = details.status
            out = details.output

        error_context.context("Check command exit status and output", test.log.info)
        test.log.debug("Returned dd_status: %s\nReturned output:\n%s", stat, out)
        if stat != dd_stat:
            err = (
                "Return code doesn't match (expected=%s, actual=%s)\n"
                "Output:\n%s" % (dd_stat, stat, out)
            )
            test.fail(err)
        if dd_output not in out:
            err = "Output doesn't match:\nExpected:\n%s\nActual:\n%s" % (dd_output, out)
            test.fail(err)
        test.log.info("dd test succeeded.")
    finally:
        # login again in case the previous session expired
        session = vm.wait_for_login(timeout=timeout)
        for dev_id in dev_partitioned:
            utils_disk.clean_partition_linux(session, dev_id)
        session.close()
