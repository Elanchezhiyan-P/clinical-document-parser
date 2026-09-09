"""Sniffs raw uploaded bytes and decides which parser should handle them:
C-CDA (HL7 CDA XML), HL7 v2.x (pipe-delimited), or FHIR (JSON or XML).
"""
import re

FORMAT_CCDA = "CCDA"
FORMAT_HL7V2 = "HL7v2"
FORMAT_FHIR_JSON = "FHIR_JSON"
FORMAT_FHIR_XML = "FHIR_XML"
FORMAT_UNKNOWN = "UNKNOWN"


def detect_format(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="ignore").strip()

    if not text:
        return FORMAT_UNKNOWN

    # HL7 v2.x: messages start with an MSH segment, fields pipe-delimited.
    if text.startswith("MSH|") or "\rMSH|" in text or "\nMSH|" in text:
        return FORMAT_HL7V2

    # FHIR JSON: any JSON object/array containing a "resourceType" key.
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        if re.search(r'"resourceType"\s*:\s*"', text):
            return FORMAT_FHIR_JSON
        return FORMAT_UNKNOWN

    # XML: distinguish CDA (ClinicalDocument root) from FHIR XML (fhir namespace).
    if stripped.startswith("<"):
        head = text[:4000]
        if "ClinicalDocument" in head and "urn:hl7-org:v3" in head:
            return FORMAT_CCDA
        if "http://hl7.org/fhir" in head:
            return FORMAT_FHIR_XML
        # Fall back: a CDA-like root without the exact namespace string nearby.
        if "<ClinicalDocument" in text:
            return FORMAT_CCDA

    return FORMAT_UNKNOWN
