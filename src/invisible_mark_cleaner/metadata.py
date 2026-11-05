from __future__ import annotations

import re

import pikepdf
from lxml import etree
from pikepdf import Dictionary, Stream

from .content import snippet
from .model import Finding, MarkKind

INFO_STANDARD = {"/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer", "/CreationDate", "/ModDate", "/Trapped"}
INFO_TEXT = {"/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer"}

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XML = "http://www.w3.org/XML/1998/namespace"
DC = "http://purl.org/dc/elements/1.1/"
XMP = "http://ns.adobe.com/xap/1.0/"
PDF = "http://ns.adobe.com/pdf/1.3/"
PDFX = "http://ns.adobe.com/pdfx/1.3/"
STANDARD_NAMESPACES = {
    RDF, XML, DC, XMP, PDF, PDFX,
    "http://ns.adobe.com/xap/1.0/mm/",
    "http://ns.adobe.com/xap/1.0/rights/",
    "http://ns.adobe.com/xap/1.0/t/pg/",
    "http://ns.adobe.com/xmp/Identifier/qual/1.0/",
    "http://ns.adobe.com/xap/1.0/sType/ResourceEvent#",
    "http://ns.adobe.com/xap/1.0/sType/ResourceRef#",
    "http://ns.adobe.com/photoshop/1.0/",
    "http://www.aiim.org/pdfa/ns/id/",
    "http://www.aiim.org/pdfua/ns/id/",
    "http://www.npes.org/pdfx/ns/id/",
    "http://www.aiim.org/pdfa/ns/extension/",
    "http://www.aiim.org/pdfa/ns/schema#",
    "http://www.aiim.org/pdfa/ns/property#",
    "http://www.aiim.org/pdfa/ns/type#",
    "http://www.aiim.org/pdfa/ns/field#",
}
XMP_TEXT = {(DC, "title"), (DC, "description"), (DC, "subject"), (DC, "creator"),
            (PDF, "Keywords"), (PDF, "Producer"), (XMP, "CreatorTool")}

INSTRUCTION = re.compile(
    r"\b(ignore|disregard)\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above)\s+instructions"
    r"|\bsystem\s+prompts?\b|\brate\s+this\b|\byou\s+are\s+an?\s+(ai|assistant|language\s+model|grader|evaluator)\b"
    r"|\bllms?\b|\blanguage\s+models?\b"
    r"|\bai\s+(model|assistant)s?\b|\b(chatgpt|gpt-?\d|openai|anthropic)\b",
    re.IGNORECASE,
)
OPAQUE = re.compile(
    r"\b[0-9a-f]{16,}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
BASE64ISH = re.compile(r"[A-Za-z0-9+/]{32,}=*")


def looks_like_marker(text: str) -> bool:
    """Instructions aimed at a model, or opaque tracking tokens."""
    if INSTRUCTION.search(text) or OPAQUE.search(text):
        return True
    return any(re.search(r"\d", m) and re.search("[a-z]", m) and re.search("[A-Z]", m)
               for m in BASE64ISH.findall(text))


def clean_metadata(pdf: pikepdf.Pdf) -> list[Finding]:
    return clean_info(pdf) + clean_xmp(pdf)


def clean_info(pdf: pikepdf.Pdf) -> list[Finding]:
    info = pdf.trailer.get("/Info")
    if not isinstance(info, Dictionary):
        return []
    findings = []
    for key in list(info.keys()):
        value = str(info[key])
        if key not in INFO_STANDARD or (key in INFO_TEXT and looks_like_marker(value)):
            del info[key]
            findings.append(Finding(MarkKind.METADATA, None, snippet(value), f"Info {key} removed"))
    return findings


def clean_xmp(pdf: pikepdf.Pdf) -> list[Finding]:
    stream = pdf.Root.get("/Metadata")
    if not isinstance(stream, Stream):
        return []
    try:
        root = etree.fromstring(stream.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
    except (etree.XMLSyntaxError, pikepdf.PdfError):
        return []
    findings = []
    for rdf in [root] if root.tag == f"{{{RDF}}}RDF" else root.iter(f"{{{RDF}}}RDF"):
        for description in rdf.findall(f"{{{RDF}}}Description"):
            prefixes = {uri: prefix for prefix, uri in description.nsmap.items()}
            for key, value in list(description.attrib.items()):
                if removable(etree.QName(key), value):
                    del description.attrib[key]
                    findings.append(xmp_finding(etree.QName(key), prefixes, value))
            for prop in [p for p in description if isinstance(p.tag, str)]:
                value = " ".join(t.strip() for t in prop.itertext() if t.strip())
                if removable(etree.QName(prop), value):
                    description.remove(prop)
                    findings.append(xmp_finding(etree.QName(prop), prefixes, value))
    if findings:
        stream.write(etree.tostring(root.getroottree(), encoding="utf-8"))
    return findings


def removable(name: etree.QName, value: str) -> bool:
    if name.namespace == PDFX:
        # pdfx holds the custom document properties mirrored from Info; only its PDF/X version keys are standard.
        return not name.localname.startswith("GTS_")
    if name.namespace not in STANDARD_NAMESPACES:
        return True
    return (name.namespace, name.localname) in XMP_TEXT and looks_like_marker(value)


def xmp_finding(name: etree.QName, prefixes: dict[str, str], value: str) -> Finding:
    prefix = prefixes.get(name.namespace) or name.namespace
    return Finding(MarkKind.METADATA, None, snippet(value), f"XMP {prefix}:{name.localname} removed")
