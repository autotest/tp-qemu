#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
# pylint: disable=unsubscriptable-object

import hashlib
import io
import ssl
import sys
import tempfile
import uuid

import ecdsa
from OpenSSL import crypto
from pyasn1_modules import pem


def intle(data):
    return int.from_bytes(data, 'little')

def indent(data):
    return "\n".join(["    " + line for line in str(data).split("\n")]).lstrip(" ")

# References to appendix
# https://download.01.org/intel-sgx/latest/dcap-latest/linux/docs/Intel_TDX_DCAP_Quoting_Library_API.pdf

# A.3.1. TD Quote Header
class TDQuoteHeader:

    def __init__(self, version, attkeytype, teetype, qevendorid, userdata):
        self.version = version
        self.attkeytype = attkeytype
        self.teetype = teetype
        self.qevendorid = qevendorid
        self.userdata = userdata

    def __repr__(self):
        attkeytypestr = [
            "reserved0",
            "reserved1",
            "ecdsa-256-with-p-256",
            "ecdsa-385-with-p-384",
        ]

        teetypestr = ["reserved"] * 256
        teetypestr[0] = "sgx"
        teetypestr[0x81] = "tdx"

        return "\n".join(["=> TD Quote Header",
                          f"Version: {self.version}",
                          f"Attestation key type: {attkeytypestr[self.attkeytype]}",
                          f"TEE type: {teetypestr[self.teetype]}",
                          f"QE vendor ID: {self.qevendorid}",
                          f"User data: {self.userdata.hex()}"])

    @staticmethod
    def from_bytes(data):
        version = intle(data[0:2])
        attkeytype = intle(data[2:4])
        teetype = intle(data[4:8])
        res1 = intle(data[8:10])
        assert(res1 == 0)
        res2 = intle(data[10:12])
        assert(res2 == 0)
        qevendorid = uuid.UUID(bytes_le=data[12:28])
        userdata = data[28:48]

        return TDQuoteHeader(version, attkeytype, teetype,
                             qevendorid, userdata)


# A.3.4. TD Attributes
class TDAttr:
    def __init__(self, debug_mode, sept_ve_disable, use_svisor_prot_keys,
                 use_key_locker, perfmon):
        self.debug_mode = debug_mode
        self.sept_ve_disable = sept_ve_disable
        self.use_svisor_prot_keys = use_svisor_prot_keys
        self.use_key_locker = use_key_locker
        self.perfmon = perfmon

    def __repr__(self):
        return "\n".join(["=> TD Attr",
                          f"Debug mode: {self.debug_mode}",
                          f"Sept VE disable: {self.sept_ve_disable}",
                          f"Use svisor prot keys: {self.use_svisor_prot_keys}",
                          f"Use key locker: {self.use_key_locker}",
                          f"Perfmon: {self.perfmon}"])

    @staticmethod
    def from_bytes(data):
        def bit(n):
            bit = n % 8
            el = int(n / 8)
            return (data[el] & (1 << bit)) != 0

        debug_mode = bit(0)
        sept_ve_disable = bit(28)
        use_svisor_prot_keys = bit(30)
        use_key_locker = bit(31)
        perfmon = bit(63)

        for i in range((len(data) * 8)):
            if i not in [0, 28, 30, 31, 63]:
                assert(not bit(i))

        return TDAttr(debug_mode, sept_ve_disable, use_svisor_prot_keys,
                      use_key_locker, perfmon)

# A.3.2. TD Quote Body
class TDQuoteBody:
    def __init__(self, teetcbsvn, mrseam, mrsignerseam, seamattr,
                 tdattr, xfam, mrtd, mrconfigid, mrowner,
                 mrownerconfig, rtmrs, reportdata):
        # A.3.3. TEE_TCB_SVN
        self.teetcbsvn = teetcbsvn # bytes
        self.mrseam = mrseam # bytes
        self.mrsignerseam = mrsignerseam # bytes
        self.seamattr = seamattr # bytes
        # A.3.4. TD Attributes
        self.tdattr = tdattr # TDAttr
        self.xfam = xfam # bytes
        self.mrtd = mrtd # bytes
        self.mrconfigid = mrconfigid # bytes
        self.mrowner = mrowner # bytes
        self.mrownerconfig = mrownerconfig # bytes
        self.rtmrs = rtmrs # list(bytes)
        self.reportdata = reportdata # bytes

    def __repr__(self):
        rtmrs = "\n".join([""] + ["- " + r.hex() for r in self.rtmrs])
        return "\n".join([
            "=> TD Quote Body",
            f"TD TCB: {self.teetcbsvn.hex()}",
            f"TDX mod measurement: {self.mrseam.hex()}",
            f"Seam Signer: {self.mrsignerseam.hex()}",
            f"SEAM attributes: {self.seamattr.hex()}",
            f"TD attributes: {indent(self.tdattr)}",
            f"Extended features mask: {self.xfam.hex()}",
            f"TD measurement: {self.mrtd.hex()}",
            f"TD config ID: {self.mrconfigid.hex()}",
            f"TD owner ID: {self.mrowner.hex()}",
            f"TR owner config: {self.mrownerconfig.hex()}",
            f"RTMRs: {indent(rtmrs)}",
            f"Report data: {self.reportdata.hex()}"])

    @staticmethod
    def from_bytes(data):
        teetcbsvn = data[0:16]
        mrseam = data[16:64]
        mrsignerseam = data[64:112]
        seamattr = data[112:120]
        tdattr = TDAttr.from_bytes(data[120:128])
        xfam = data[128:136]
        mrtd = data[136:184]
        mrconfigid = data[184:232]
        mrowner = data[232:280]
        mrownerconfig = data[280:328]
        rtmrs = [
            data[328:376],
            data[376:424],
            data[424:472],
            data[472:520]
        ]
        reportdata = data[520:584]
        return TDQuoteBody(teetcbsvn, mrseam, mrsignerseam, seamattr,
                           tdattr, xfam, mrtd, mrconfigid, mrowner,
                           mrownerconfig, rtmrs, reportdata)


# A.3.8. ECDSA 256-bit Quote Signature Data Structure – Version 4
class ECDSA256QuoteSignature:

    def __init__(self, signature, ecdsaattkey, qecertdata):
        self.signature = signature
        self.ecdsaattkey = ecdsaattkey
        self.qecertdata = qecertdata # QECertificationDataV4

    def __repr__(self):
        return "\n".join(["=> ECDSA 256 Quote Sig v4",
                          f"Quote sig: {self.signature.hex()}",
                          f"ECDSA attestation key: {self.ecdsaattkey.hex()}",
                          f"QE Cert Data: {indent(self.qecertdata)}"])

    @staticmethod
    def from_bytes(data):
        signature = data[0:64]
        ecdsaattkey = data[64:128]
        qecertdata = QECertificationDataV4.from_bytes(data[128:])

        return ECDSA256QuoteSignature(signature, ecdsaattkey, qecertdata)


# A.3.9. QE Certification Data – Version 4
class QECertificationDataV4:

    def __init__(self, certdatatype, qereportcertdata=None, pckcertchain=None):
        self.certdatatype = certdatatype
        if self.certdatatype == 5:
            assert(pckcertchain is not None)
            assert(qereportcertdata is None)
        elif self.certdatatype == 6:
            assert(pckcertchain is None)
            assert(qereportcertdata is not None)
        else:
            assert(pckcertchain is None)
            assert(qereportcertdata is None)
        self.qereportcertdata = qereportcertdata # QEReportCertificationData
        self.pckcertchain = pckcertchain # PCKCertChain

    def __repr__(self):
        return "\n".join(["=> QE certification data v4",
                          f"Cert data type: {self.certdatatype}",
                          f"QE Report cert data: {indent(self.qereportcertdata)}",
                          f"PCK Cert chain: {indent(self.pckcertchain)}"])

    @staticmethod
    def from_bytes(data):
        certdatatype = intle(data[0:2])
        assert(certdatatype in [5, 6])
        certdatalen = intle(data[2:6])
        certdata = data[6:6+certdatalen]

        qereportcertdata = None
        pckcertchain = None
        if certdatatype == 5:
            pckcertchain = PCKCertChain.from_bytes(certdata)
        elif certdatatype == 6:
            qereportcertdata = QEReportCertificationData.from_bytes(certdata)

        return QECertificationDataV4(certdatatype, qereportcertdata, pckcertchain)


# A.3.10. Enclave Report Body
class EnclaveReportBody:
    def __init__(self, cpusvn, miscselect, attrs, mrenclave, mrsigner,
                 isvprodid, isvsvn, reportdata):
        self.cpusvn = cpusvn # bytes
        self.miscselect = miscselect # int
        self.attrs = attrs # bytes
        self.mrenclave = mrenclave # bytes
        self.mrsigner = mrsigner # bytes
        self.isvprodid = isvprodid # int
        self.isvsvn = isvsvn # int
        self.reportdata = reportdata # bytes

    def __repr__(self):
        return "\n".join([
            "=> Enclave Report Body",
            f"CPU SVN: {self.cpusvn.hex()}",
            f"Misc select: {self.miscselect}",
            f"Attributes: {self.attrs.hex()}",
            f"MR Enclave: {self.mrenclave.hex()}",
            f"MR Signer: {self.mrsigner.hex()}",
            f"ISV Prod ID: {self.isvprodid}",
            f"ISV SVN: {self.isvsvn}",
            f"Report data: {self.reportdata.hex()}"])

    @staticmethod
    def from_bytes(data):
        cpusvn = data[0:16]
        miscselect = intle(data[16:20])
        #reserved = data[20:48]
        #assert(reserved == bytes([0] * 28))
        attrs = data[48:64]
        mrenclave = data[64:96]
        #reserved = data[96:128]
        #assert(reserved == bytes([0] * 28))
        mrsigner = data[128:160]
        #reserved = data[160:256]
        #assert(reserved == bytes([0] * 96))
        isvprodid = intle(data[256:258])
        isvsvn = intle(data[258:260])
        #reserved = data[260:320]
        reportdata = data[320:384]

        return EnclaveReportBody(cpusvn, miscselect, attrs, mrenclave,
                                 mrsigner, isvprodid, isvsvn, reportdata)


# A.3.11. QE Report Certification Data
class QEReportCertificationData:

    def __init__(self, qereport, qereporthash, qereportsig, qeauthdata, qecertdata):
        self.qereport = qereport # EnclaveReportBody
        self.qereporthash = qereporthash # bytes
        self.qereportsig = qereportsig # bytes
        self.qeauthdata = qeauthdata # bytes
        self.qecertdata = qecertdata # QECertificationDataV4

    def __repr__(self):
        return "\n".join([
            "=> QE Report Certification Data",
            f"QE Report: {indent(self.qereport)}",
            f"QE Report Sig: {self.qereportsig.hex()}",
            f"QE Auth Data: {self.qeauthdata.hex()}",
            f"QE Cert Data: {indent(self.qecertdata)}"])

    @staticmethod
    def from_bytes(data):
        qereport = EnclaveReportBody.from_bytes(data[0:384])
        m = hashlib.sha256()
        m.update(data[0:384])
        qereporthash = m.digest()
        qereportsig = data[384:448]
        # A.3.7. QE Authentication Data
        qeauthdatalen = intle(data[448:450])
        qeauthdata = data[450:450+qeauthdatalen]

        qecertdata = QECertificationDataV4.from_bytes(data[450+qeauthdatalen:])

        return QEReportCertificationData(qereport, qereporthash, qereportsig,
                                         qeauthdata, qecertdata)

class PCKCertChain:

    def __init__(self, certs):
        self.certs = certs

    def __repr__(self):
        def cert_name(x509name):
            return "/".join([d[0].decode() + "=" + d[1].decode()
                             for d in x509name.get_components()])

        return "\n".join([
            "=> PCK Cert chain",
            "\n".join(["\n".join(["Cert:",
                                  f"  - Subject: {cert_name(c.get_subject())}",
                                  f"  -  Issuer: {cert_name(c.get_issuer())}"])
                       for c in self.certs])
            ])

    @staticmethod
    def from_bytes(data):
        datafile = io.StringIO(data.decode())
        certs = []
        while True:
            idx, payload = pem.readPemBlocksFromFile(
                datafile,
                ('-----BEGIN CERTIFICATE-----',
                 '-----END CERTIFICATE-----'))

            if idx == -1:
                break

            pemcert = ssl.DER_cert_to_PEM_cert(payload)
            cert = crypto.load_certificate(crypto.FILETYPE_PEM, pemcert)
            certs.append(cert)

        return PCKCertChain(certs)

# A.3.12. Full TD Quote in v4
class TDQuoteV4:

    def __init__(self, header, body, tdreporthash, sig):
        self.header = header # TDQuoteHeader
        self.body = body # TDQuoteBody
        self.tdreporthash = tdreporthash
        self.sig = sig # ECDSA256QuoteSignature

    def __repr__(self):
        return "\n".join([
            "=> TD Quote",
            f"Header: {indent(self.header)}",
            f"Body: {indent(self.body)}",
            f"Signature: {indent(self.sig)}"])

    def verify_tdreport(self):
        vk = ecdsa.VerifyingKey.from_string(self.sig.ecdsaattkey,
                                            curve=ecdsa.NIST256p)
        try:
            vk.verify_digest(self.sig.signature, self.tdreporthash)
            return True
        except Exception:
            return False

    def verify_qereport(self):
        report = self.sig.qecertdata.qereportcertdata

        cert = report.qecertdata.pckcertchain.certs[0]

        pubKeyObject = cert.get_pubkey()
        pubKeyString = crypto.dump_publickey(crypto.FILETYPE_PEM, pubKeyObject)

        qk = ecdsa.VerifyingKey.from_pem(pubKeyString)
        try:
            qk.verify_digest(report.qereportsig, report.qereporthash)
            return True
        except Exception:
            return False

    @staticmethod
    def from_bytes(data):
        header = TDQuoteHeader.from_bytes(data[0:48])
        body = TDQuoteBody.from_bytes(data[48:632])

        #reportdigest = data[0:632]
        m = hashlib.sha256()
        m.update(data[0:632])
        tdreporthash = m.digest()

        siglen = intle(data[632:636])
        sig = ECDSA256QuoteSignature.from_bytes(data[636:636+siglen])

        return TDQuoteV4(header, body, tdreporthash, sig)

    @staticmethod
    def from_file(filename):
        with open(filename, "rb") as fh:
            data = fh.read()
            return TDQuoteV4.from_bytes(data)

def verify_quote(quotebytes):
    quote = TDQuoteV4.from_bytes(quotebytes)
    print(quote)

    retval = 0
    ok = "PASS"
    if not quote.verify_tdreport():
        ok = "FAIL"
        retval = 1
    print(f"Verifying TD report: {ok}")

    ok = "PASS"
    if not quote.verify_qereport():
        ok = "FAIL"
        retval = 1
    print(f"Verifying QE report: {ok}")
    return retval

def make_quote():
    report = tempfile.mkdtemp(dir = '/sys/kernel/config/tsm/report',
                              prefix = 'report')
    print(f'Using directory: {report}')
    with open('/dev/urandom', 'rb') as rng:
        inblob = rng.read(64)
    with open(f'{report}/inblob', 'wb') as f:
        f.write(inblob)
    with open(f'{report}/outblob', 'rb') as f:
        quote = f.read()
    return quote

def main():
    quote = make_quote()
    if len(quote) == 0:
        print("Create quote: FAIL")
        return 1
    return verify_quote(quote)

if __name__ == '__main__':
    sys.exit(main())
