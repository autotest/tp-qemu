import os
import pickle
import random
import re
import sys
import time
import traceback
from xml.parsers import expat

import aexpect
from avocado.utils import process
from virttest import cpu, data_dir, qemu_migration, qemu_vm, utils_misc, virt_vm
from virttest.utils_test.qemu import migration


def run(test, params, env):
    """
    Boot guest with different cpu flags and check if guest works correctly.

    :param test: kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    cpu.Flag.aliases = cpu.kvm_map_flags_aliases
    qemu_binary = utils_misc.get_qemu_binary(params)

    cpuflags_src = os.path.join(data_dir.get_deps_dir("cpu_flags"), "src")
    cpuflags_def = os.path.join(data_dir.get_deps_dir("cpu_flags"), "cpu_map.xml")
    smp = int(params.get("smp", 1))

    all_host_supported_flags = params.get("all_host_supported_flags", "no")

    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_speed = params.get("mig_speed", "1G")

    cpu_model_black_list = params.get("cpu_model_blacklist", "").split(" ")

    multi_host_migration = params.get("multi_host_migration", "no")

    class HgFlags(object):
        def __init__(self, cpu_model, extra_flags=set([])):
            virtual_flags = set(
                map(cpu.Flag, params.get("guest_spec_flags", "").split())
            )
            self.hw_flags = set(
                map(utils_misc.Flag, params.get("host_spec_flags", "").split())
            )
            self.qemu_support_flags = get_all_qemu_flags()
            self.host_support_flags = set(map(cpu.Flag, cpu.get_cpu_flags()))
            self.quest_cpu_model_flags = (
                get_guest_host_cpuflags(cpu_model) - virtual_flags
            )

            self.supported_flags = self.qemu_support_flags & self.host_support_flags
            self.cpumodel_unsupport_flags = (
                self.supported_flags - self.quest_cpu_model_flags
            )

            self.host_unsupported_flags = (
                self.quest_cpu_model_flags - self.host_support_flags
            )

            self.all_possible_guest_flags = (
                self.quest_cpu_model_flags - self.host_unsupported_flags
            )
            self.all_possible_guest_flags |= self.cpumodel_unsupport_flags

            self.guest_flags = self.quest_cpu_model_flags - self.host_unsupported_flags
            self.guest_flags |= extra_flags

            self.host_all_unsupported_flags = set([])
            self.host_all_unsupported_flags |= self.qemu_support_flags
            self.host_all_unsupported_flags -= self.host_support_flags | virtual_flags

    def start_guest_with_cpuflags(cpuflags, smp=None, migration=False, wait=True):
        """
        Try to boot guest with special cpu flags and try login in to them.
        """
        params_b = params.copy()
        params_b["cpu_model"] = cpuflags
        if smp is not None:
            params_b["smp"] = smp

        vm_name = "vm1-cpuflags"
        vm = qemu_vm.VM(vm_name, params_b, test.bindir, env["address_cache"])
        env.register_vm(vm_name, vm)
        if migration is True:
            vm.create(migration_mode=mig_protocol)
        else:
            vm.create()

        session = None
        try:
            vm.verify_alive()

            if wait:
                session = vm.wait_for_login()
        except qemu_vm.ImageUnbootableError:
            vm.destroy(gracefully=False)
            raise

        return (vm, session)

    def get_guest_system_cpuflags(vm_session):
        """
        Get guest system cpuflags.

        :param vm_session: session to checked vm.
        :return: [corespond flags]
        """
        flags_re = re.compile(r"^flags\s*:(.*)$", re.MULTILINE)
        out = vm_session.cmd_output("cat /proc/cpuinfo")

        flags = flags_re.search(out).groups()[0].split()
        return set(map(cpu.Flag, flags))

    def get_guest_host_cpuflags_legacy(cpumodel):
        """
        Get cpu flags correspond with cpumodel parameters.

        :param cpumodel: Cpumodel parameter sended to <qemu-kvm-cmd>.
        :return: [corespond flags]
        """
        cmd = qemu_binary + " -cpu ?dump"
        output = process.run(cmd).stdout
        re.escape(cpumodel)
        pattern = (
            r".+%s.*\n.*\n +feature_edx .+ \((.*)\)\n +feature_"
            r"ecx .+ \((.*)\)\n +extfeature_edx .+ \((.*)\)\n +"
            r"extfeature_ecx .+ \((.*)\)\n" % (cpumodel)
        )
        flags = []
        model = re.search(pattern, output)
        if model is None:
            test.fail("Cannot find %s cpu model." % (cpumodel))
        for flag_group in model.groups():
            flags += flag_group.split()
        return set(map(cpu.Flag, flags))

    class ParseCpuFlags(object):
        def __init__(self, encoding=None):
            self.cpus = {}
            self.parser = expat.ParserCreate(encoding)
            self.parser.StartElementHandler = self.start_element
            self.parser.EndElementHandler = self.end_element
            self.last_arch = None
            self.last_model = None
            self.sub_model = False
            self.all_flags = []

        def start_element(self, name, attrs):
            if name == "cpus":
                self.cpus = {}
            elif name == "arch":
                self.last_arch = self.cpus[attrs["name"]] = {}
            elif name == "model":
                if self.last_model is None:
                    self.last_model = self.last_arch[attrs["name"]] = []
                else:
                    self.last_model += self.last_arch[attrs["name"]]
                    self.sub_model = True
            elif name == "feature":
                if self.last_model is not None:
                    self.last_model.append(attrs["name"])
                else:
                    self.all_flags.append(attrs["name"])

        def end_element(self, name):
            if name == "arch":
                self.last_arch = None
            elif name == "model":
                if self.sub_model is False:
                    self.last_model = None
                else:
                    self.sub_model = False

        def parse_file(self, file_path):
            self.parser.ParseFile(open(file_path, "r"))
            return self.cpus

    def get_guest_host_cpuflags_1350(cpumodel):
        """
        Get cpu flags correspond with cpumodel parameters.

        :param cpumodel: Cpumodel parameter sended to <qemu-kvm-cmd>.
        :return: [corespond flags]
        """
        p = ParseCpuFlags()
        cpus = p.parse_file(cpuflags_def)
        flags = []
        for arch in cpus.values():
            if cpumodel in arch.keys():
                flags = arch[cpumodel]
        return set(map(cpu.Flag, flags))

    get_guest_host_cpuflags_BAD = get_guest_host_cpuflags_1350

    def get_all_qemu_flags_legacy():
        cmd = qemu_binary + " -cpu ?cpuid"
        output = process.run(cmd).stdout

        flags_re = re.compile(
            r".*\n.*f_edx:(.*)\n.*f_ecx:(.*)\n" ".*extf_edx:(.*)\n.*extf_ecx:(.*)"
        )
        m = flags_re.search(output)
        flags = []
        for a in m.groups():
            flags += a.split()

        return set(map(cpu.Flag, flags))

    def get_all_qemu_flags_1350():
        cmd = qemu_binary + " -cpu ?"
        output = process.run(cmd).stdout

        flags_re = re.compile(r".*Recognized CPUID flags:\n(.*)", re.DOTALL)
        m = flags_re.search(output)
        flags = []
        for a in m.groups():
            flags += a.split()

        return set(map(cpu.Flag, flags))

    def get_all_qemu_flags_BAD():
        """
        Get cpu flags correspond with cpumodel parameters.

        :param cpumodel: Cpumodel parameter sended to <qemu-kvm-cmd>.
        :return: [corespond flags]
        """
        p = ParseCpuFlags()
        p.parse_file(cpuflags_def)
        return set(map(cpu.Flag, p.all_flags))

    def get_cpu_models_legacy():
        """
        Get all cpu models from qemu.

        :return: cpu models.
        """
        cmd = qemu_binary + " -cpu ?"
        output = process.run(cmd).stdout

        cpu_re = re.compile(r"\w+\s+\[?(\w+)\]?")
        return cpu_re.findall(output)

    def get_cpu_models_1350():
        """
        Get all cpu models from qemu.

        :return: cpu models.
        """
        cmd = qemu_binary + " -cpu ?"
        output = process.run(cmd).stdout

        cpu_re = re.compile(r"x86\s+\[?(\w+)\]?")
        return cpu_re.findall(output)

    get_cpu_models_BAD = get_cpu_models_1350

    def get_qemu_cpu_cmd_version():
        cmd = qemu_binary + " -cpu ?cpuid"
        try:
            process.run(cmd).stdout
            return "legacy"
        except:
            cmd = qemu_binary + " -cpu ?"
            output = process.run(cmd).stdout
            if "CPUID" in output:
                return "1350"
            else:
                return "BAD"

    qcver = get_qemu_cpu_cmd_version()

    get_guest_host_cpuflags = locals()["get_guest_host_cpuflags_%s" % qcver]
    get_all_qemu_flags = locals()["get_all_qemu_flags_%s" % qcver]
    get_cpu_models = locals()["get_cpu_models_%s" % qcver]

    def get_flags_full_name(cpu_flag):
        """
        Get all name of Flag.

        :param cpu_flag: Flag
        :return: all name of Flag.
        """
        cpu_flag = cpu.Flag(cpu_flag)
        for f in get_all_qemu_flags():
            if f == cpu_flag:
                return cpu.Flag(f)
        return []

    def parse_qemu_cpucommand(cpumodel):
        """
        Parse qemu cpu params.

        :param cpumodel: Cpu model command.
        :return: All flags which guest must have.
        """
        flags = cpumodel.split(",")
        cpumodel = flags[0]

        qemu_model_flag = get_guest_host_cpuflags(cpumodel)
        host_support_flag = set(map(cpu.Flag, cpu.get_cpu_flags()))
        real_flags = qemu_model_flag & host_support_flag

        for f in flags[1:]:
            if f[0].startswith("+"):
                real_flags |= set([get_flags_full_name(f[1:])])
            if f[0].startswith("-"):
                real_flags -= set([get_flags_full_name(f[1:])])

        return real_flags

    def check_cpuflags(cpumodel, vm_session):
        """
        Check if vm flags are same like flags select by cpumodel.

        :param cpumodel: params for -cpu param in qemu-kvm
        :param vm_session: session to vm to check flags.

        :return: ([excess], [missing]) flags
        """
        gf = get_guest_system_cpuflags(vm_session)
        rf = parse_qemu_cpucommand(cpumodel)

        test.log.debug("Guest flags: %s", gf)
        test.log.debug("Host flags: %s", rf)
        test.log.debug("Flags on guest not defined by host: %s", (gf - rf))
        return rf - gf

    def get_cpu_models_supported_by_host():
        """
        Get all cpumodels which set of flags is subset of hosts flags.

        :return: [cpumodels]
        """
        cpumodels = []
        for cpumodel in get_cpu_models():
            flags = HgFlags(cpumodel)
            if flags.host_unsupported_flags == set([]):
                cpumodels.append(cpumodel)
        return cpumodels

    def disable_cpu(vm_session, cpu, disable=True):
        """
        Disable cpu in guest system.

        :param cpu: CPU id to disable.
        :param disable: if True disable cpu else enable cpu.
        """
        system_cpu_dir = "/sys/devices/system/cpu/"
        cpu_online = system_cpu_dir + "cpu%d/online" % (cpu)
        cpu_state = vm_session.cmd_output("cat %s" % cpu_online).strip()
        if disable and cpu_state == "1":
            vm_session.cmd("echo 0 > %s" % cpu_online)
            test.log.debug("Guest cpu %d is disabled.", cpu)
        elif cpu_state == "0":
            vm_session.cmd("echo 1 > %s" % cpu_online)
            test.log.debug("Guest cpu %d is enabled.", cpu)

    def check_online_cpus(vm_session, smp, disabled_cpu):
        """
        Disable cpu in guest system.

        :param smp: Count of cpu core in system.
        :param disable_cpu: List of disabled cpu.

        :return: List of CPUs that are still enabled after disable procedure.
        """
        online = [0]
        for cpuid in range(1, smp):
            system_cpu_dir = "/sys/devices/system/cpu/"
            cpu_online = system_cpu_dir + "cpu%d/online" % (cpuid)
            cpu_state = vm_session.cmd_output("cat %s" % cpu_online).strip()
            if cpu_state == "1":
                online.append(cpuid)
        cpu_proc = vm_session.cmd_output("cat /proc/cpuinfo")
        cpu_state_proc = map(
            lambda x: int(x), re.findall(r"processor\s+:\s*(\d+)\n", cpu_proc)
        )
        if set(online) != set(cpu_state_proc):
            test.error(
                "Some cpus are disabled but %s are still "
                "visible like online in /proc/cpuinfo."
                % (set(cpu_state_proc) - set(online))
            )

        return set(online) - set(disabled_cpu)

    def install_cpuflags_test_on_vm(vm, dst_dir):
        """
        Install stress to vm.

        :param vm: virtual machine.
        :param dst_dir: Installation path.
        """
        session = vm.wait_for_login()
        vm.copy_files_to(cpuflags_src, dst_dir)
        session.cmd("sync")
        session.cmd("cd %s; make EXTRA_FLAGS='';" % os.path.join(dst_dir, "src"))
        session.cmd("sync")
        session.close()

    def check_cpuflags_work(vm, path, flags):
        """
        Check which flags work.

        :param vm: Virtual machine.
        :param path: Path of cpuflags_test
        :param flags: Flags to test.
        :return: Tuple (Working, not working, not tested) flags.
        """
        pass_Flags = []
        not_tested = []
        not_working = []
        session = vm.wait_for_login()
        for f in flags:
            try:
                for tc in cpu.kvm_map_flags_to_test[f]:
                    session.cmd(
                        "%s/cpuflags-test --%s" % (os.path.join(path, "src"), tc)
                    )
                pass_Flags.append(f)
            except aexpect.ShellCmdError:
                not_working.append(f)
            except KeyError:
                not_tested.append(f)
        return (
            set(map(cpu.Flag, pass_Flags)),
            set(map(cpu.Flag, not_working)),
            set(map(cpu.Flag, not_tested)),
        )

    def run_stress(vm, timeout, guest_flags):
        """
        Run stress on vm for timeout time.
        """
        ret = False
        install_path = "/tmp"
        install_cpuflags_test_on_vm(vm, install_path)
        flags = check_cpuflags_work(vm, install_path, guest_flags)
        dd_session = vm.wait_for_login()
        stress_session = vm.wait_for_login()
        dd_session.sendline(
            "dd if=/dev/[svh]da of=/tmp/stressblock bs=10MB count=100 &"
        )
        try:
            stress_session.cmd(
                "%s/cpuflags-test --stress %s%s"
                % (
                    os.path.join(install_path, "src"),
                    smp,
                    cpu.kvm_flags_to_stresstests(flags[0]),
                ),
                timeout=timeout,
            )
        except aexpect.ShellTimeoutError:
            ret = True
        stress_session.close()
        dd_session.close()
        return ret

    def separe_cpu_model(cpu_model):
        try:
            (cpu_model, _) = cpu_model.split(":")
        except ValueError:
            cpu_model = cpu_model
        return cpu_model

    def parse_cpu_model():
        """
        Parse cpu_models from config file.

        :return: [(cpumodel, extra_flags)]
        """
        cpu_model = params.get("cpu_model", "")
        test.log.debug("CPU model found: %s", str(cpu_model))

        try:
            (cpu_model, extra_flags) = cpu_model.split(":")
            extra_flags = set(map(cpu.Flag, extra_flags.split(",")))
        except ValueError:
            cpu_model = cpu_model
            extra_flags = set([])
        return (cpu_model, extra_flags)

    class MiniSubtest(object):
        def __new__(cls, *args, **kargs):
            self = super(MiniSubtest, cls).__new__(cls)
            ret = None
            if args is None:
                args = []
            try:
                ret = self.test(*args, **kargs)
            finally:
                if hasattr(self, "clean"):
                    self.clean()
            return ret

    def print_exception(called_object):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        test.log.error("In function (%s):", called_object.__name__)
        test.log.error("Call from:\n%s", traceback.format_stack()[-2][:-1])
        test.log.error(
            "Exception from:\n%s",
            "".join(
                traceback.format_exception(exc_type, exc_value, exc_traceback.tb_next)
            ),
        )

    class Test_temp(MiniSubtest):
        def clean(self):
            test.log.info("cleanup")
            vm = getattr(self, "vm", None)
            if vm:
                vm.destroy(gracefully=False)
            clone = getattr(self, "clone", None)
            if clone:
                clone.destroy(gracefully=False)

    # 1) <qemu-kvm-cmd> -cpu ?model
    class test_qemu_cpu_model(MiniSubtest):
        def test(self):
            if qcver == "legacy":
                cpu_models = params.get("cpu_models", "core2duo").split()
                cmd = qemu_binary + " -cpu ?model"
                result = process.run(cmd)
                missing = []
                cpu_models = map(separe_cpu_model, cpu_models)
                for cpu_model in cpu_models:
                    if cpu_model not in result.stdout:
                        missing.append(cpu_model)
                if missing:
                    test.fail(
                        "CPU models %s are not in output "
                        "'%s' of command \n%s" % (missing, cmd, result.stdout)
                    )
            else:
                test.cancel("New qemu does not support -cpu ?model. (%s)" % qcver)

    # 2) <qemu-kvm-cmd> -cpu ?dump
    class test_qemu_dump(MiniSubtest):
        def test(self):
            if qcver == "legacy":
                cpu_models = params.get("cpu_models", "core2duo").split()
                cmd = qemu_binary + " -cpu ?dump"
                result = process.run(cmd)
                cpu_models = map(separe_cpu_model, cpu_models)
                missing = []
                for cpu_model in cpu_models:
                    if cpu_model not in result.stdout:
                        missing.append(cpu_model)
                if missing:
                    test.fail(
                        "CPU models %s are not in output "
                        "'%s' of command \n%s" % (missing, cmd, result.stdout)
                    )
            else:
                test.cancel("New qemu does not support -cpu ?dump. (%s)" % qcver)

    # 3) <qemu-kvm-cmd> -cpu ?cpuid
    class test_qemu_cpuid(MiniSubtest):
        def test(self):
            if qcver == "legacy":
                cmd = qemu_binary + " -cpu ?cpuid"
                result = process.run(cmd)
                if result.stdout == "":
                    test.fail(
                        "There aren't any cpu Flag in output"
                        " '%s' of command \n%s" % (cmd, result.stdout)
                    )
            else:
                test.cancel("New qemu does not support -cpu ?cpuid. (%s)" % qcver)

    # 1) boot with cpu_model
    class test_boot_cpu_model(Test_temp):
        def test(self):
            cpu_model, _ = parse_cpu_model()
            test.log.debug("Run tests with cpu model %s", cpu_model)
            flags = HgFlags(cpu_model)
            (self.vm, session) = start_guest_with_cpuflags(cpu_model)
            not_enable_flags = check_cpuflags(cpu_model, session) - flags.hw_flags
            if not_enable_flags != set([]):
                test.fail(
                    "Flags defined on host but not found "
                    "on guest: %s" % (not_enable_flags)
                )

    # 2) success boot with supported flags
    class test_boot_cpu_model_and_additional_flags(Test_temp):
        def test(self):
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            test.log.debug("Cpu mode flags %s.", str(flags.quest_cpu_model_flags))
            cpuf_model = cpu_model

            if all_host_supported_flags == "yes":
                for fadd in flags.cpumodel_unsupport_flags:
                    cpuf_model += ",+" + str(fadd)
            else:
                for fadd in extra_flags:
                    cpuf_model += ",+" + str(fadd)

            for fdel in flags.host_unsupported_flags:
                cpuf_model += ",-" + str(fdel)

            if all_host_supported_flags == "yes":
                guest_flags = flags.all_possible_guest_flags
            else:
                guest_flags = flags.guest_flags

            (self.vm, session) = start_guest_with_cpuflags(cpuf_model)

            not_enable_flags = check_cpuflags(cpuf_model, session) - flags.hw_flags
            if not_enable_flags != set([]):
                test.log.info(
                    "Model unsupported flags: %s", str(flags.cpumodel_unsupport_flags)
                )
                test.log.error(
                    "Flags defined on host but not on found on guest: %s",
                    str(not_enable_flags),
                )
            test.log.info("Check main instruction sets.")

            install_path = "/tmp"
            install_cpuflags_test_on_vm(self.vm, install_path)

            Flags = check_cpuflags_work(
                self.vm, install_path, flags.all_possible_guest_flags
            )
            test.log.info("Woking CPU flags: %s", str(Flags[0]))
            test.log.info("Not working CPU flags: %s", str(Flags[1]))
            test.log.warning(
                "Flags works even if not defined on guest cpu flags: %s",
                str(Flags[0] - guest_flags),
            )
            test.log.warning("Not tested CPU flags: %s", str(Flags[2]))

            if Flags[1] & guest_flags:
                test.fail("Some flags do not work: %s" % (str(Flags[1])))

    # 3) fail boot unsupported flags
    class test_boot_warn_with_host_unsupported_flags(MiniSubtest):
        def test(self):
            # This is virtual cpu flags which are supported by
            # qemu but no with host cpu.
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            test.log.debug(
                "Unsupported flags %s.", str(flags.host_all_unsupported_flags)
            )
            cpuf_model = cpu_model + ",check"

            # Add unsupported flags.
            for fadd in flags.host_all_unsupported_flags:
                cpuf_model += ",+" + str(fadd)

            vnc_port = utils_misc.find_free_port(5900, 6100) - 5900
            cmd = "%s -cpu %s -vnc :%d -enable-kvm" % (
                qemu_binary,
                cpuf_model,
                vnc_port,
            )
            out = None

            try:
                try:
                    out = process.run(cmd, timeout=5, ignore_status=True).stderr
                    test.fail("Guest not boot with unsupported flags.")
                except process.CmdError as e:
                    out = e.result.stderr
            finally:
                uns_re = re.compile(r"^warning:.*flag '(.+)'", re.MULTILINE)
                nf_re = re.compile(r"^CPU feature (.+) not found", re.MULTILINE)
                warn_flags = set([cpu.Flag(x) for x in uns_re.findall(out)])
                not_found = set([cpu.Flag(x) for x in nf_re.findall(out)])
                fwarn_flags = flags.host_all_unsupported_flags - warn_flags
                fwarn_flags -= not_found
                if fwarn_flags:
                    test.fail(
                        "Qemu did not warn the use of flags %s" % str(fwarn_flags)
                    )

    # 3) fail boot unsupported flags
    class test_fail_boot_with_host_unsupported_flags(MiniSubtest):
        def test(self):
            # This is virtual cpu flags which are supported by
            # qemu but no with host cpu.
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)
            cpuf_model = cpu_model + ",enforce"

            test.log.debug(
                "Unsupported flags %s.", str(flags.host_all_unsupported_flags)
            )

            # Add unsupported flags.
            for fadd in flags.host_all_unsupported_flags:
                cpuf_model += ",+" + str(fadd)

            vnc_port = utils_misc.find_free_port(5900, 6100) - 5900
            cmd = "%s -cpu %s -vnc :%d -enable-kvm" % (
                qemu_binary,
                cpuf_model,
                vnc_port,
            )
            out = None
            try:
                try:
                    out = process.run(cmd, timeout=5, ignore_status=True).stderr
                except process.CmdError:
                    test.log.error("Host boot with unsupported flag")
            finally:
                uns_re = re.compile(r"^warning:.*flag '(.+)'", re.MULTILINE)
                nf_re = re.compile(r"^CPU feature (.+) not found", re.MULTILINE)
                warn_flags = set([cpu.Flag(x) for x in uns_re.findall(out)])
                not_found = set([cpu.Flag(x) for x in nf_re.findall(out)])
                fwarn_flags = flags.host_all_unsupported_flags - warn_flags
                fwarn_flags -= not_found
                if fwarn_flags:
                    test.fail(
                        "Qemu did not warn the use of flags %s" % str(fwarn_flags)
                    )

    # 4) check guest flags under load cpu, stress and system (dd)
    class test_boot_guest_and_try_flags_under_load(Test_temp):
        def test(self):
            test.log.info(
                "Check guest working cpuflags under load cpu and stress and system (dd)"
            )
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            cpuf_model = cpu_model

            test.log.debug("Cpu mode flags %s.", str(flags.quest_cpu_model_flags))

            if all_host_supported_flags == "yes":
                test.log.debug("Added flags %s.", str(flags.cpumodel_unsupport_flags))

                # Add unsupported flags.
                for fadd in flags.cpumodel_unsupport_flags:
                    cpuf_model += ",+" + str(fadd)

                for fdel in flags.host_unsupported_flags:
                    cpuf_model += ",-" + str(fdel)

            (self.vm, _) = start_guest_with_cpuflags(cpuf_model, smp)

            if not run_stress(self.vm, 60, flags.guest_flags):
                test.fail("Stress test ended before end of test.")

    # 5) Online/offline CPU
    class test_online_offline_guest_CPUs(Test_temp):
        def test(self):
            cpu_model, extra_flags = parse_cpu_model()

            test.log.debug("Run tests with cpu model %s.", (cpu_model))
            flags = HgFlags(cpu_model, extra_flags)

            (self.vm, session) = start_guest_with_cpuflags(cpu_model, smp)

            def encap(timeout):
                random.seed()
                begin = time.time()
                end = begin
                if smp > 1:
                    while end - begin < 60:
                        cpu = random.randint(1, smp - 1)
                        if random.randint(0, 1):
                            disable_cpu(session, cpu, True)
                        else:
                            disable_cpu(session, cpu, False)
                        end = time.time()
                    return True
                else:
                    test.log.warning("For this test is necessary smp > 1.")
                    return False

            timeout = 60

            test_flags = flags.guest_flags
            if all_host_supported_flags == "yes":
                test_flags = flags.all_possible_guest_flags

            result = utils_misc.parallel(
                [(encap, [timeout]), (run_stress, [self.vm, timeout, test_flags])]
            )
            if not (result[0] and result[1]):
                test.fail("Stress tests failed before end of testing.")

    # 6) migration test
    class test_migration_with_additional_flags(Test_temp):
        def test(self):
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            test.log.debug("Cpu mode flags %s.", str(flags.quest_cpu_model_flags))
            test.log.debug("Added flags %s.", str(flags.cpumodel_unsupport_flags))
            cpuf_model = cpu_model

            # Add unsupported flags.
            for fadd in flags.cpumodel_unsupport_flags:
                cpuf_model += ",+" + str(fadd)

            for fdel in flags.host_unsupported_flags:
                cpuf_model += ",-" + str(fdel)

            (self.vm, _) = start_guest_with_cpuflags(cpuf_model, smp)

            install_path = "/tmp"
            install_cpuflags_test_on_vm(self.vm, install_path)
            flags = check_cpuflags_work(self.vm, install_path, flags.guest_flags)
            test.assertTrue(flags[0], "No cpuflags passed the check: %s" % str(flags))
            test.assertFalse(
                flags[1], "Some cpuflags failed the check: %s" % str(flags)
            )
            dd_session = self.vm.wait_for_login()
            stress_session = self.vm.wait_for_login()

            dd_session.sendline(
                "nohup dd if=$(echo /dev/[svh]da) of=/tmp/"
                "stressblock bs=10MB count=100 &"
            )
            cmd = "nohup %s/cpuflags-test --stress  %s%s &" % (
                os.path.join(install_path, "src"),
                smp,
                cpu.kvm_flags_to_stresstests(flags[0]),
            )
            stress_session.sendline(cmd)

            time.sleep(5)

            qemu_migration.set_speed(self.vm, mig_speed)
            self.clone = self.vm.migrate(
                mig_timeout, mig_protocol, offline=False, not_wait_for_migration=True
            )

            time.sleep(5)

            try:
                self.vm.wait_for_migration(10)
            except virt_vm.VMMigrateTimeoutError:
                qemu_migration.set_downtime(self.vm, 1)
                self.vm.wait_for_migration(mig_timeout)

            self.clone.resume()
            self.vm.destroy(gracefully=False)

            stress_session = self.clone.wait_for_login()

            # If cpuflags-test hang up during migration test raise exception
            try:
                stress_session.cmd("killall cpuflags-test")
            except aexpect.ShellCmdError:
                test.fail(
                    "Stress cpuflags-test should be still running after migration."
                )
            try:
                stress_session.cmd("ls /tmp/stressblock && rm -f /tmp/stressblock")
            except aexpect.ShellCmdError:
                test.fail("Background 'dd' command failed to produce output file.")

    def net_send_object(socket, obj):
        """
        Send python object over network.

        :param ip_addr: ipaddres of waiter for data.
        :param obj: object to send
        """
        data = pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)
        socket.sendall("%6d" % len(data))
        socket.sendall(data)

    def net_recv_object(socket, timeout=60):
        """
        Receive python object over network.

        :param ip_addr: ipaddres of waiter for data.
        :param obj: object to send
        :return: object from network
        """
        try:
            time_start = time.time()
            data = ""
            d_len = int(socket.recv(6))

            while len(data) < d_len and (time.time() - time_start) < timeout:
                data += socket.recv(d_len - len(data))

            data = pickle.loads(data)
            return data
        except:
            test.fail("Failed to receive python object over the network")

    class test_multi_host_migration(Test_temp):
        def test(self):
            """
            Test migration between multiple hosts.
            """
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            test.log.debug("Cpu mode flags %s.", str(flags.quest_cpu_model_flags))
            test.log.debug("Added flags %s.", str(flags.cpumodel_unsupport_flags))
            cpuf_model = cpu_model

            for fadd in extra_flags:
                cpuf_model += ",+" + str(fadd)

            for fdel in flags.host_unsupported_flags:
                cpuf_model += ",-" + str(fdel)

            install_path = "/tmp"

            class testMultihostMigration(migration.MultihostMigration):
                def __init__(self, test, params, env):
                    migration.MultihostMigration.__init__(self, test, params, env)

                def migration_scenario(self):
                    srchost = self.params.get("hosts")[0]
                    dsthost = self.params.get("hosts")[1]

                    def worker(mig_data):
                        vm = env.get_vm("vm1")
                        session = vm.wait_for_login(timeout=self.login_timeout)

                        install_cpuflags_test_on_vm(vm, install_path)

                        Flags = check_cpuflags_work(
                            vm, install_path, flags.all_possible_guest_flags
                        )
                        test.log.info("Woking CPU flags: %s", str(Flags[0]))
                        test.log.info("Not working CPU flags: %s", str(Flags[1]))
                        test.log.warning(
                            "Flags works even if not defined on guest cpu flags: %s",
                            str(Flags[0] - flags.guest_flags),
                        )
                        test.log.warning("Not tested CPU flags: %s", str(Flags[2]))
                        session.sendline(
                            "nohup dd if=/dev/[svh]da of=/tmp/"
                            "stressblock bs=10MB count=100 &"
                        )

                        cmd = "nohup %s/cpuflags-test --stress  %s%s &" % (
                            os.path.join(install_path, "src"),
                            smp,
                            cpu.kvm_flags_to_stresstests(Flags[0] & flags.guest_flags),
                        )
                        test.log.debug("Guest_flags: %s", str(flags.guest_flags))
                        test.log.debug("Working_flags: %s", str(Flags[0]))
                        test.log.debug("Start stress on guest: %s", cmd)
                        session.sendline(cmd)

                    def check_worker(mig_data):
                        vm = env.get_vm("vm1")

                        vm.verify_illegal_instruction()

                        session = vm.wait_for_login(timeout=self.login_timeout)

                        try:
                            session.cmd("killall cpuflags-test")
                        except aexpect.ShellCmdError:
                            test.fail(
                                "The cpuflags-test program"
                                " should be active after"
                                " migration and it's not."
                            )

                        Flags = check_cpuflags_work(
                            vm, install_path, flags.all_possible_guest_flags
                        )
                        test.log.info("Woking CPU flags: %s", str(Flags[0]))
                        test.log.info("Not working CPU flags: %s", str(Flags[1]))
                        test.log.warning(
                            "Flags works even if not defined on guest cpu flags: %s",
                            str(Flags[0] - flags.guest_flags),
                        )
                        test.log.warning("Not tested CPU flags: %s", str(Flags[2]))

                    self.migrate_wait(["vm1"], srchost, dsthost, worker, check_worker)

            params_b = params.copy()
            params_b["cpu_model"] = cpu_model
            mig = testMultihostMigration(test, params_b, env)
            mig.run()

    class test_multi_host_migration_onoff_cpu(Test_temp):
        def test(self):
            """
            Test migration between multiple hosts.
            """
            cpu_model, extra_flags = parse_cpu_model()

            flags = HgFlags(cpu_model, extra_flags)

            test.log.debug("Cpu mode flags %s.", str(flags.quest_cpu_model_flags))
            test.log.debug("Added flags %s.", str(flags.cpumodel_unsupport_flags))
            cpuf_model = cpu_model

            for fadd in extra_flags:
                cpuf_model += ",+" + str(fadd)

            for fdel in flags.host_unsupported_flags:
                cpuf_model += ",-" + str(fdel)

            smp = int(params["smp"])
            disable_cpus = list(
                map(lambda cpu: int(cpu), params.get("disable_cpus", "").split())
            )

            install_path = "/tmp"

            class testMultihostMigration(migration.MultihostMigration):
                def __init__(self, test, params, env):
                    migration.MultihostMigration.__init__(self, test, params, env)
                    self.srchost = self.params.get("hosts")[0]
                    self.dsthost = self.params.get("hosts")[1]
                    self.id = {
                        "src": self.srchost,
                        "dst": self.dsthost,
                        "type": "disable_cpu",
                    }
                    self.migrate_count = int(self.params.get("migrate_count", "2"))

                def ping_pong_migrate(self, sync, worker, check_worker):
                    for _ in range(self.migrate_count):
                        test.log.info(
                            "File transfer not ended, starting a round of migration..."
                        )
                        sync.sync(True, timeout=mig_timeout)
                        if self.hostid == self.srchost:
                            self.migrate_wait(
                                ["vm1"], self.srchost, self.dsthost, start_work=worker
                            )
                        elif self.hostid == self.dsthost:
                            self.migrate_wait(
                                ["vm1"],
                                self.srchost,
                                self.dsthost,
                                check_work=check_worker,
                            )
                        tmp = self.dsthost
                        self.dsthost = self.srchost
                        self.srchost = tmp

                def migration_scenario(self):
                    from autotest.client.shared.syncdata import SyncData

                    sync = SyncData(
                        self.master_id(),
                        self.hostid,
                        self.hosts,
                        self.id,
                        self.sync_server,
                    )

                    def worker(mig_data):
                        vm = env.get_vm("vm1")
                        session = vm.wait_for_login(timeout=self.login_timeout)

                        install_cpuflags_test_on_vm(vm, install_path)

                        Flags = check_cpuflags_work(
                            vm, install_path, flags.all_possible_guest_flags
                        )
                        test.log.info("Woking CPU flags: %s", str(Flags[0]))
                        test.log.info("Not working CPU flags: %s", str(Flags[1]))
                        test.log.warning(
                            "Flags works even if not defined on guest cpu flags: %s",
                            str(Flags[0] - flags.guest_flags),
                        )
                        test.log.warning("Not tested CPU flags: %s", str(Flags[2]))
                        for vcpu in disable_cpus:
                            if vcpu < smp:
                                disable_cpu(session, vcpu, True)
                            else:
                                test.log.warning(
                                    "There is no enouth cpu"
                                    " in Guest. It is trying to"
                                    "remove cpu:%s from guest with"
                                    " smp:%s.",
                                    vcpu,
                                    smp,
                                )
                        test.log.debug("Guest_flags: %s", str(flags.guest_flags))
                        test.log.debug("Working_flags: %s", str(Flags[0]))

                    def check_worker(mig_data):
                        vm = env.get_vm("vm1")

                        vm.verify_illegal_instruction()

                        session = vm.wait_for_login(timeout=self.login_timeout)

                        really_disabled = check_online_cpus(session, smp, disable_cpus)

                        not_disabled = set(really_disabled) & set(disable_cpus)
                        if not_disabled:
                            test.fail(
                                "Some of disabled cpus are "
                                "online. This shouldn't "
                                "happen. Cpus disabled on "
                                "srchost:%s, Cpus not "
                                "disabled on dsthost:%s" % (disable_cpus, not_disabled)
                            )

                        Flags = check_cpuflags_work(
                            vm, install_path, flags.all_possible_guest_flags
                        )
                        test.log.info("Woking CPU flags: %s", str(Flags[0]))
                        test.log.info("Not working CPU flags: %s", str(Flags[1]))
                        test.log.warning(
                            "Flags works even if not defined on guest cpu flags: %s",
                            str(Flags[0] - flags.guest_flags),
                        )
                        test.log.warning("Not tested CPU flags: %s", str(Flags[2]))

                    self.ping_pong_migrate(sync, worker, check_worker)

            params_b = params.copy()
            params_b["cpu_model"] = cpu_model
            mig = testMultihostMigration(test, params_b, env)
            mig.run()

    test_type = params.get("test_type")
    if test_type in locals():
        tests_group = locals()[test_type]
        if params.get("cpu_model"):
            tests_group()
        else:
            cpu_models = set(get_cpu_models_supported_by_host()) - set(
                cpu_model_black_list
            )
            if not cpu_models:
                test.cancel("No cpu_models detected, nothing to test.")
            test.log.info("Start test with cpu models %s", str(cpu_models))
            failed = []
            for cpumodel in cpu_models:
                params["cpu_model"] = cpumodel
                try:
                    tests_group()
                except:
                    print_exception(tests_group)
                    failed.append(cpumodel)
            if failed != []:
                test.fail("Test of cpu models %s failed." % (str(failed)))
    else:
        test.fail("Test group '%s' is not defined in cpuflags test" % test_type)
