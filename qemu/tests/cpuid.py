"""
Group of cpuid tests for X86 CPU
"""

import logging
import os
import re

from avocado.utils import build, process
from virttest import cpu, data_dir, env_process, utils_misc, virt_vm

logger = logging.getLogger(__name__)
dbg = logger.debug
info = logger.info


def isprintable(c):
    try:
        import string

        if c in string.printable:
            return True
        return False
    except ImportError:
        return c.isprintable()


def run(test, params, env):
    """
    Boot guest with different cpu_models, cpu flags and check if guest works correctly.

    :param test: kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    qemu_binary = utils_misc.get_qemu_binary(params)

    cpu_model = params.get("cpu_model", "qemu64")

    xfail = False
    if (params.get("xfail") is not None) and (params.get("xfail") == "yes"):
        xfail = True

    def cpu_models_to_test():
        """Return the list of CPU models to be tested, based on the
        cpu_models and cpu_model config options.

        Config option "cpu_model" may be used to ask a single CPU model
        to be tested. Config option "cpu_models" may be used to ask
        multiple CPU models to be tested.

        If cpu_models is "*", all CPU models reported by QEMU will be tested.
        """
        models_opt = params.get("cpu_models")
        model_opt = params.get("cpu_model")

        if models_opt is None and model_opt is None:
            test.error("No cpu_models or cpu_model option is set")

        cpu_models = set()

        if models_opt == "*":
            cpu_models.update(cpu.get_qemu_cpu_models(qemu_binary))
        elif models_opt:
            cpu_models.update(models_opt.split())

        if model_opt:
            cpu_models.add(model_opt)

        return cpu_models

    def test_qemu_cpu_models_list(self):
        """
        check CPU models returned by <qemu> -cpu '?' are what is expected
        """
        """
        test method
        """
        cpu_models = cpu_models_to_test()
        qemu_models = cpu.get_qemu_cpu_models(qemu_binary)
        missing = set(cpu_models) - set(qemu_models)
        if missing:
            test.fail("Some CPU models not in QEMU CPU model list: %r" % (missing))
        added = set(qemu_models) - set(cpu_models)
        if added:
            test.log.info("Extra CPU models in QEMU CPU listing: %s", added)

    def compare_cpuid_output(a, b):
        """
        Generates a list of (bit, va, vb) tuples for
        each bit that is different between a and b.
        """
        for bit in range(32):
            ba = (a & (1 << bit)) >> bit
            if b is not None:
                bb = (b & (1 << bit)) >> bit
            else:
                bb = None
            if ba != bb:
                yield (bit, ba, bb)

    def parse_cpuid_dump(output):
        dbg("parsing cpuid dump: %r", output)
        cpuid_re = re.compile(
            "^ *(0x[0-9a-f]+) +0x([0-9a-f]+): +eax=0x([0-9a-f]+) ebx=0x([0-9a-f]+) "
            "ecx=0x([0-9a-f]+) edx=0x([0-9a-f]+)$"
        )
        output_match = re.search(
            "(==START TEST==.*==END TEST==)", output, re.M | re.DOTALL
        )
        if output_match is None:
            dbg("cpuid dump doesn't follow expected pattern")
            return None
        output = output_match.group(1)
        out_lines = output.splitlines()
        if out_lines[0] != "==START TEST==" or out_lines[-1] != "==END TEST==":
            dbg("cpuid dump doesn't have expected delimiters")
            return None
        if out_lines[1] != "CPU:":
            dbg("cpuid dump doesn't start with 'CPU:' line")
            return None
        result = {}
        for l in out_lines[2:-1]:
            m = cpuid_re.match(l)
            if m is None:
                dbg("invalid cpuid dump line: %r", l)
                return None
            in_eax = int(m.group(1), 16)
            in_ecx = int(m.group(2), 16)
            result[in_eax, in_ecx, "eax"] = int(m.group(3), 16)
            result[in_eax, in_ecx, "ebx"] = int(m.group(4), 16)
            result[in_eax, in_ecx, "ecx"] = int(m.group(5), 16)
            result[in_eax, in_ecx, "edx"] = int(m.group(6), 16)
        return result

    def get_test_kernel_cpuid(self, vm):
        vm.resume()

        timeout = float(params.get("login_timeout", 240))
        test.log.debug("Will wait for CPUID serial output at %r", vm.serial_console)
        if not utils_misc.wait_for(
            lambda: re.search("==END TEST==", vm.serial_console.get_output()),
            timeout,
            1,
        ):
            test.fail("Could not get test complete message.")

        test_output = parse_cpuid_dump(vm.serial_console.get_output())
        test.log.debug("Got CPUID serial output: %r", test_output)
        if test_output is None:
            test.fail(
                "Test output signature not found in " "output:\n %s",
                vm.serial_console.get_output(),
            )
        vm.destroy(gracefully=False)
        return test_output

    def find_cpu_obj(vm):
        """Find path of a valid VCPU object"""
        roots = ["/machine/icc-bridge/icc", "/machine/unattached/device"]
        for root in roots:
            for child in vm.monitor.cmd("qom-list", dict(path=root)):
                test.log.debug("child: %r", child)
                if child["type"].rstrip(">").endswith("-cpu"):
                    return root + "/" + child["name"]

    def get_qom_cpuid(self, vm):
        assert vm.monitor.protocol == "qmp"
        cpu_path = find_cpu_obj(vm)
        test.log.debug("cpu path: %r", cpu_path)
        r = {}
        for prop in "feature-words", "filtered-features":
            words = vm.monitor.cmd("qom-get", dict(path=cpu_path, property=prop))
            test.log.debug("%s property: %r", prop, words)
            for w in words:
                reg = w["cpuid-register"].lower()
                key = (w["cpuid-input-eax"], w.get("cpuid-input-ecx", 0), reg)
                r.setdefault(key, 0)
                r[key] |= w["features"]
        return r

    def get_guest_cpuid(
        self, cpu_model, feature=None, extra_params=None, qom_mode=False
    ):
        if not qom_mode:
            test_kernel_dir = os.path.join(data_dir.get_deps_dir(), "cpuid", "src")
            build.make(test_kernel_dir, extra_args="cpuid_dump_kernel.bin")

        vm_name = params["main_vm"]
        params_b = params.copy()
        if not qom_mode:
            params_b["kernel"] = os.path.join(test_kernel_dir, "cpuid_dump_kernel.bin")
        params_b["cpu_model"] = cpu_model
        params_b["cpu_model_flags"] = feature
        del params_b["images"]
        del params_b["nics"]
        if extra_params:
            params_b.update(extra_params)
        env_process.preprocess_vm(self, params_b, env, vm_name)
        vm = env.get_vm(vm_name)
        dbg("is dead: %r", vm.is_dead())
        vm.create()
        self.vm = vm
        if qom_mode:
            return get_qom_cpuid(self, vm)
        else:
            return get_test_kernel_cpuid(self, vm)

    def cpuid_to_vendor(cpuid_dump, idx):
        dst = []
        for i in range(0, 4):
            dst.append((chr(cpuid_dump[idx, 0, "ebx"] >> (8 * i) & 0xFF)))
        for i in range(0, 4):
            dst.append((chr(cpuid_dump[idx, 0, "edx"] >> (8 * i) & 0xFF)))
        for i in range(0, 4):
            dst.append((chr(cpuid_dump[idx, 0, "ecx"] >> (8 * i) & 0xFF)))
        return "".join(dst)

    def default_vendor(self):
        """
        Boot qemu with specified cpu models and
        verify that CPU vendor matches requested
        """
        cpu_models = cpu_models_to_test()

        vendor = params.get("vendor")
        if vendor is None or vendor == "host":
            cmd = "grep 'vendor_id' /proc/cpuinfo | head -n1 | awk '{print $3}'"
            cmd_result = process.run(cmd, ignore_status=True, shell=True)
            vendor = cmd_result.stdout.strip()

        ignore_cpus = set(params.get("ignore_cpu_models", "").split(" "))
        cpu_models = cpu_models - ignore_cpus

        for cpu_model in cpu_models:
            out = get_guest_cpuid(self, cpu_model)
            guest_vendor = cpuid_to_vendor(out, 0x00000000)
            test.log.debug("Guest's vendor: %s", guest_vendor)
            if guest_vendor != vendor:
                test.fail(
                    "Guest vendor [%s], doesn't match "
                    "required vendor [%s] for CPU [%s]"
                    % (guest_vendor, vendor, cpu_model)
                )

    def custom_vendor(self):
        """
        Boot qemu with specified vendor
        """
        has_error = False
        vendor = params["vendor"]

        try:
            out = get_guest_cpuid(self, cpu_model, "vendor=" + vendor)
            guest_vendor0 = cpuid_to_vendor(out, 0x00000000)
            guest_vendor80000000 = cpuid_to_vendor(out, 0x80000000)
            test.log.debug("Guest's vendor[0]: %s", guest_vendor0)
            test.log.debug("Guest's vendor[0x80000000]: %s", guest_vendor80000000)
            if guest_vendor0 != vendor:
                test.fail(
                    "Guest vendor[0] [%s], doesn't match "
                    "required vendor [%s] for CPU [%s]"
                    % (guest_vendor0, vendor, cpu_model)
                )
            if guest_vendor80000000 != vendor:
                test.fail(
                    "Guest vendor[0x80000000] [%s], "
                    "doesn't match required vendor "
                    "[%s] for CPU [%s]" % (guest_vendor80000000, vendor, cpu_model)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_level(cpuid_dump):
        r = cpuid_dump[0, 0]
        return r["eax"]

    def custom_level(self):
        """
        Boot qemu with specified level
        """
        has_error = False
        level = params["level"]
        try:
            out = get_guest_cpuid(self, cpu_model, "level=" + level)
            guest_level = str(cpuid_to_level(out))
            if guest_level != level:
                test.fail(
                    "Guest's level [%s], doesn't match "
                    "required level [%s]" % (guest_level, level)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_family(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]["eax"]
        family = (eax >> 8) & 0xF
        if family == 0xF:
            # extract extendend family
            return family + ((eax >> 20) & 0xFF)
        return family

    def custom_family(self):
        """
        Boot qemu with specified family
        """
        has_error = False
        family = params["family"]
        try:
            out = get_guest_cpuid(self, cpu_model, "family=" + family)
            guest_family = str(cpuid_to_family(out))
            if guest_family != family:
                test.fail(
                    "Guest's family [%s], doesn't match "
                    "required family [%s]" % (guest_family, family)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_model(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]["eax"]
        model = (eax >> 4) & 0xF
        # extended model
        model |= (eax >> 12) & 0xF0
        return model

    def custom_model(self):
        """
        Boot qemu with specified model
        """
        has_error = False
        model = params["model"]
        try:
            out = get_guest_cpuid(self, cpu_model, "model=" + model)
            guest_model = str(cpuid_to_model(out))
            if guest_model != model:
                test.fail(
                    "Guest's model [%s], doesn't match "
                    "required model [%s]" % (guest_model, model)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_stepping(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]["eax"]
        stepping = eax & 0xF
        return stepping

    def custom_stepping(self):
        """
        Boot qemu with specified stepping
        """
        has_error = False
        stepping = params["stepping"]
        try:
            out = get_guest_cpuid(self, cpu_model, "stepping=" + stepping)
            guest_stepping = str(cpuid_to_stepping(out))
            if guest_stepping != stepping:
                test.fail(
                    "Guest's stepping [%s], doesn't match "
                    "required stepping [%s]" % (guest_stepping, stepping)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_xlevel(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.2.1 Largest Extendend Function # (Function 80000000h)
        return cpuid_dump[0x80000000, 0x00]["eax"]

    def custom_xlevel(self):
        """
        Boot qemu with specified xlevel
        """
        has_error = False
        xlevel = params["xlevel"]
        if params.get("expect_xlevel") is not None:
            xlevel = params.get("expect_xlevel")

        try:
            out = get_guest_cpuid(self, cpu_model, "xlevel=" + params.get("xlevel"))
            guest_xlevel = str(cpuid_to_xlevel(out))
            if guest_xlevel != xlevel:
                test.fail(
                    "Guest's xlevel [%s], doesn't match "
                    "required xlevel [%s]" % (guest_xlevel, xlevel)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_to_model_id(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.2.3 Processor Brand String (Functions 80000002h, 80000003h,
        # 80000004h)
        m_id = ""
        for idx in (0x80000002, 0x80000003, 0x80000004):
            regs = cpuid_dump[idx, 0]
            for name in ("eax", "ebx", "ecx", "edx"):
                for shift in range(4):
                    c = (regs[name] >> (shift * 8)) & 0xFF
                    if c == 0:  # drop trailing \0-s
                        break
                    m_id += chr(c)
        return m_id

    def custom_model_id(self):
        """
        Boot qemu with specified model_id
        """
        has_error = False
        model_id = params["model_id"]

        try:
            out = get_guest_cpuid(self, cpu_model, "model_id='%s'" % model_id)
            guest_model_id = cpuid_to_model_id(out)
            if guest_model_id != model_id:
                test.fail(
                    "Guest's model_id [%s], doesn't match "
                    "required model_id [%s]" % (guest_model_id, model_id)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_regs_to_string(cpuid_dump, leaf, idx, regs):
        r = cpuid_dump[leaf, idx]
        signature = ""
        for i in regs:
            for shift in range(0, 4):
                c = chr((r[i] >> (shift * 8)) & 0xFF)
                if isprintable(c):
                    signature = signature + c
                else:
                    signature = "%s\\x%02x" % (signature, ord(c))
        test.log.debug("(%s.%s:%s: signature: %s", leaf, idx, str(regs), signature)
        return signature

    def cpuid_signature(self):
        """
        test signature in specified leaf:index:regs
        """
        has_error = False
        flags = params.get("flags", "")
        leaf = int(params.get("leaf", "0x40000000"), 0)
        idx = int(params.get("index", "0x00"), 0)
        regs = params.get("regs", "ebx ecx edx").split()
        signature = params["signature"]
        try:
            out = get_guest_cpuid(self, cpu_model, flags)
            _signature = cpuid_regs_to_string(out, leaf, idx, regs)
            if _signature != signature:
                test.fail(
                    "Guest's signature [%s], doesn't"
                    "match required signature [%s]" % (_signature, signature)
                )
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_bit_test(self):
        """
        test bits in specified leaf:func:reg
        """
        has_error = False
        flags = params.get("flags", "")
        leaf = int(params.get("leaf", "0x40000000"), 0)
        idx = int(params.get("index", "0x00"), 0)
        reg = params.get("reg", "eax")
        bits = params["bits"].split()
        try:
            out = get_guest_cpuid(self, cpu_model, flags)
            r = out[leaf, idx][reg]
            test.log.debug("CPUID(%s.%s).%s=0x%08x", leaf, idx, reg, r)
            for i in bits:
                if (r & (1 << int(i))) == 0:
                    test.fail("CPUID(%s.%s).%s[%s] is not set" % (leaf, idx, reg, i))
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def cpuid_reg_test(self):
        """
        test register value in specified leaf:index:reg
        """
        has_error = False
        flags = params.get("flags", "")
        leaf = int(params.get("leaf", "0x00"), 0)
        idx = int(params.get("index", "0x00"), 0)
        reg = params.get("reg", "eax")
        val = int(params["value"], 0)
        try:
            out = get_guest_cpuid(self, cpu_model, flags)
            r = out[leaf, idx][reg]
            test.log.debug("CPUID(%s.%s).%s=0x%08x", leaf, idx, reg, r)
            if r != val:
                test.fail("CPUID(%s.%s).%s is not 0x%08x" % (leaf, idx, reg, val))
        except:
            has_error = True
            if xfail is False:
                raise
        if (has_error is False) and (xfail is True):
            test.fail("Test was expected to fail, but it didn't")

    def check_cpuid_dump(self):
        """
        Compare full CPUID dump data
        """
        machine_type = params.get("machine_type_to_check", "")
        kvm_enabled = params.get("enable_kvm", "yes") == "yes"

        ignore_cpuid_leaves = params.get("ignore_cpuid_leaves", "")
        ignore_cpuid_leaves = ignore_cpuid_leaves.split()
        whitelist = []
        for leaf in ignore_cpuid_leaves:
            leaf = leaf.split(",")
            # syntax of ignore_cpuid_leaves:
            # <in_eax>[,<in_ecx>[,<register>[ ,<bit>]]] ...
            for i in 0, 1, 3:  # integer fields:
                if len(leaf) > i:
                    leaf[i] = int(leaf[i], 0)
            whitelist.append(tuple(leaf))

        if not machine_type:
            test.cancel("No machine_type_to_check defined")
        cpu_model_flags = params.get("cpu_model_flags", "")
        full_cpu_model_name = cpu_model
        if cpu_model_flags:
            full_cpu_model_name += ","
            full_cpu_model_name += cpu_model_flags.lstrip(",")
        ref_file = os.path.join(
            data_dir.get_deps_dir(),
            "cpuid",
            "cpuid_dumps",
            kvm_enabled and "kvm" or "nokvm",
            machine_type,
            "%s-dump.txt" % (full_cpu_model_name),
        )
        if not os.path.exists(ref_file):
            test.cancel("no cpuid dump file: %s" % (ref_file))
        reference = open(ref_file, "r").read()
        if not reference:
            test.cancel("no cpuid dump data on file: %s" % (ref_file))
        reference = parse_cpuid_dump(reference)
        if reference is None:
            test.cancel(
                "couldn't parse reference cpuid dump from file; %s" % (ref_file)
            )
        qom_mode = params.get("qom_mode", "no").lower() == "yes"
        if not qom_mode:
            cpu_model_flags += ",enforce"
        try:
            out = get_guest_cpuid(
                self,
                cpu_model,
                cpu_model_flags,
                extra_params=dict(machine_type=machine_type, smp=1),
                qom_mode=qom_mode,
            )
        except (virt_vm.VMStartError, virt_vm.VMCreateError) as output:
            if (
                "host doesn't support requested feature:" in output
                or (
                    "host cpuid" in output
                    and (
                        "lacks requested flag" in output
                        or "flag restricted to guest" in output
                    )
                )
                or ("Unable to find CPU definition:" in output)
            ):
                test.cancel(
                    "Can't run CPU model %s on this host" % (full_cpu_model_name)
                )
            else:
                raise
        dbg("ref_file: %r", ref_file)
        dbg("ref: %r", reference)
        dbg("out: %r", out)
        ok = True
        for k in reference.keys():
            in_eax, in_ecx, reg = k
            diffs = compare_cpuid_output(reference[k], out.get(k))
            for d in diffs:
                bit, vreference, vout = d
                whitelisted = (
                    (in_eax,) in whitelist
                    or (in_eax, in_ecx) in whitelist
                    or (in_eax, in_ecx, reg) in whitelist
                    or (in_eax, in_ecx, reg, bit) in whitelist
                )
                silent = False

                if vout is None and params.get("ok_missing", "no") == "yes":
                    whitelisted = True
                    silent = True

                if not silent:
                    info(
                        "Non-matching bit: CPUID[0x%x,0x%x].%s[%d]: found %s instead of"
                        " %s%s",
                        in_eax,
                        in_ecx,
                        reg,
                        bit,
                        vout,
                        vreference,
                        whitelisted and " (whitelisted)" or "",
                    )

                if not whitelisted:
                    ok = False
        if not ok:
            test.fail("Unexpected CPUID data")

    # subtests runner
    test_type = params["test_type"]
    if test_type not in locals():
        test.error("Test function '%s' is not defined in test" % test_type)

    test_func = locals()[test_type]
    return test_func(test)
