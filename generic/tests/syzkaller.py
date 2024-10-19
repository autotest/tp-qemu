import json
import os
import shutil
import time

from avocado.utils import process
from avocado.utils.software_manager import manager
from virttest import data_dir, ssh_key, storage, utils_misc


def run(test, params, env):
    """
    Setup and run syzkaller (https://github.com/google/syzkaller)
    1. Install/Setup syzkaller in host
    2. Setup Guest for passwordless ssh from host
    3. Prepare and compile Guest kernel
    4. Prepare syzkaller config with qemu params and guest params
    5. Start sykaller with above config and run for specified time(test_timeout)
    6. Test fails out incase of any host issues
    """
    start_time = time.time()
    #  Step 1: Install/Setup syzkaller in host
    sm = manager.SoftwareManager()
    if not sm.check_installed("go") and not sm.install("go"):
        test.cancel("golang package install failed")
    home = os.environ["HOME"]
    if not ("goroot/bin" in os.environ["PATH"] and "go/bin" in os.environ["PATH"]):
        process.run(
            'echo "PATH=%s/goroot/bin:%s/go/bin:$PATH" >> %s/.bashrc'
            % (home, home, home),
            shell=True,
        )
    process.run("source %s/.bashrc" % home, shell=True)
    process.run("go get -u -d github.com/google/syzkaller/...", shell=True)
    process.run("cd %s/go/src/github.com/google/syzkaller;make" % home, shell=True)
    syzkaller_path = "%s/go/src/github.com/google/syzkaller" % home

    # Step 2: Setup Guest for passwordless ssh from host
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    ssh_key.setup_ssh_key(
        vm.get_address(), params.get("username"), params.get("password")
    )
    session.close()
    vm.destroy()

    # Step 3: Prepare Guest kernel
    guest_kernel_repo = params.get("syz_kernel_repo")
    guest_kernel_branch = params.get("syz_kernel_branch")
    guest_kernel_config = params.get("syz_kernel_config")
    guest_kernel_build_path = utils_misc.get_path(test.debugdir, "linux")
    process.run(
        "git clone --depth 1 %s -b %s %s"
        % (guest_kernel_repo, guest_kernel_branch, guest_kernel_build_path),
        shell=True,
    )
    process.run(
        "cd %s;git log -1;make %s" % (guest_kernel_build_path, guest_kernel_config),
        shell=True,
    )
    process.run(
        'cd %s; echo "CONFIG_KCOV=y\nCONFIG_GCC_PLUGINS=y" >> '
        ".config; make olddefconfig" % guest_kernel_build_path,
        shell=True,
    )
    process.run("cd %s;make -j 40" % guest_kernel_build_path, shell=True)

    # Step 4: Prepare syzkaller config with qemu params and guest params
    syz_config_path = utils_misc.get_path(test.debugdir, "syzkaller_config")
    os.makedirs("%s/syzkaller" % test.debugdir)
    workdir = "%s/syzkaller" % test.debugdir
    sshkey = "%s/.ssh/id_rsa" % os.environ["HOME"]
    kernel_path = "%s/vmlinux" % guest_kernel_build_path

    vm_config = {
        "count": int(params.get("syz_count")),
        "cpu": int(params.get("smp")),
        "mem": int(params.get("mem")),
        "kernel": kernel_path,
        "cmdline": params.get("kernel_args"),
        "qemu_args": params.get("syz_qemu_args"),
    }

    syz_config = {
        "target": params.get("syz_target"),
        "workdir": workdir,
        "http": params.get("syz_http"),
        "image": storage.get_image_filename(params, data_dir.get_data_dir()),
        "syzkaller": syzkaller_path,
        "procs": int(params.get("syz_procs")),
        "type": "qemu",
        "sshkey": sshkey,
        "vm": vm_config,
    }
    try:
        with open(syz_config_path, "w") as fp:
            json.dump(syz_config, fp)
    except IOError as err:
        test.error("Unable to update syzkaller config: %s", err)
    end_time = time.time()
    # Step 5: Start sykaller config with specified time
    # Let's calculate the syzkaller timeout from
    # test timeout excluding current elapsed time + buffer
    testtimeout = int(params.get("test_timeout")) - (int(end_time - start_time) + 10)
    cmd = "%s/bin/syz-manager -config %s %s" % (
        syzkaller_path,
        syz_config_path,
        params.get("syz_cmd_params"),
    )
    process.run(cmd, timeout=testtimeout, ignore_status=True, shell=True)
    # Let's delete linux kernel folder from test-results as it would
    # consume lot of space and test log have all the information about
    # it incase to retrieve it back.
    if os.path.isdir(guest_kernel_build_path):
        shutil.rmtree(guest_kernel_build_path)
