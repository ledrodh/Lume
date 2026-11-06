from __future__ import annotations

import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from core.models import ValidationIssue, ValidationSummary


def _resolve_epub_path(base_dir: str, href: str) -> str:
    """Resolves a relative href against base_dir using POSIX separators."""
    joined = posixpath.join(base_dir, href) if base_dir else href
    norm = posixpath.normpath(joined)
    if norm == ".":
        return ""
    return norm


def validate_epub_structure(epub_path: str | Path) -> ValidationSummary:
    """
    Layer 1 Internal Structural EPUB Validator (W3C EPUB 3.3 OCF & Internal Reference Resolver).
    Validates:
    1. ZIP integrity and 'mimetype' position (index 0), compression (ZIP_STORED), and exact content.
    2. Presence and XML validity of META-INF/container.xml.
    3. Presence and XML validity of the OPF package document, manifest items, and spine itemrefs.
    4. XML well-formedness of all XHTML content documents.
    5. Generic internal reference resolution across all href/src attributes and #fragment anchors.
    """
    issues: list[ValidationIssue] = []
    path = Path(epub_path)

    if not path.exists() or not path.is_file():
        issues.append(
            ValidationIssue(
                severity="error",
                code="OCF-001",
                location=str(path),
                message="EPUB file does not exist.",
            )
        )
        return ValidationSummary(is_valid=False, issues=issues)

    if not zipfile.is_zipfile(path):
        issues.append(
            ValidationIssue(
                severity="error",
                code="OCF-002",
                location=str(path),
                message="File is not a valid ZIP archive.",
            )
        )
        return ValidationSummary(is_valid=False, issues=issues)

    mimetype_ok = False
    container_xml_ok = False
    opf_manifest_ok = False
    xhtml_well_formed_ok = True
    checked_files = 0
    checked_links = 0
    broken_links = 0

    with zipfile.ZipFile(path, "r") as zf:
        infolist = zf.infolist()
        namelist_set = set(zf.namelist())
        checked_files = len(infolist)

        # 1. Validate 'mimetype' entry (W3C EPUB 3.3 OCF Section 4.3.2)
        if not infolist:
            issues.append(
                ValidationIssue("error", "OCF-003", "archive", "ZIP archive is empty.")
            )
            return ValidationSummary(is_valid=False, issues=issues)

        first_info = infolist[0]
        if first_info.filename != "mimetype":
            issues.append(
                ValidationIssue(
                    "error",
                    "PKG-006",
                    first_info.filename,
                    f"First file in ZIP must be 'mimetype', found '{first_info.filename}'.",
                )
            )
        elif first_info.compress_type != zipfile.ZIP_STORED:
            issues.append(
                ValidationIssue(
                    "error",
                    "PKG-007",
                    "mimetype",
                    "The 'mimetype' file must be stored uncompressed (ZIP_STORED).",
                )
            )
        else:
            raw_mime = zf.read("mimetype")
            if raw_mime != b"application/epub+zip":
                issues.append(
                    ValidationIssue(
                        "error",
                        "PKG-008",
                        "mimetype",
                        f"Invalid mimetype content: {raw_mime!r}. Expected b'application/epub+zip'.",
                    )
                )
            else:
                mimetype_ok = True

        # 2. Validate META-INF/container.xml
        opf_path = ""
        if "META-INF/container.xml" not in namelist_set:
            issues.append(
                ValidationIssue(
                    "error",
                    "RSC-002",
                    "META-INF/container.xml",
                    "Missing required META-INF/container.xml file.",
                )
            )
        else:
            try:
                container_root = ET.fromstring(zf.read("META-INF/container.xml"))
                for elem in container_root.iter():
                    if elem.tag.endswith("rootfile") and elem.attrib.get("full-path"):
                        opf_path = elem.attrib["full-path"].strip()
                        break
                if opf_path:
                    container_xml_ok = True
                else:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "RSC-003",
                            "META-INF/container.xml",
                            "No <rootfile full-path='...'> found in META-INF/container.xml.",
                        )
                    )
            except ET.ParseError as exc:
                issues.append(
                    ValidationIssue(
                        "error",
                        "XML-001",
                        "META-INF/container.xml",
                        f"Malformed XML in container.xml: {exc}",
                    )
                )

        # 3. Validate OPF Package Document, Manifest, and Spine
        xhtml_files: list[str] = []
        if opf_path:
            if opf_path not in namelist_set:
                issues.append(
                    ValidationIssue(
                        "error",
                        "OPF-001",
                        opf_path,
                        f"OPF package document '{opf_path}' declared in container.xml does not exist in archive.",
                    )
                )
            else:
                opf_dir = posixpath.dirname(opf_path)
                try:
                    opf_root = ET.fromstring(zf.read(opf_path))
                    manifest_ids: set[str] = set()
                    missing_manifest_files = 0

                    for elem in opf_root.iter():
                        if elem.tag.endswith("item"):
                            item_id = elem.attrib.get("id", "")
                            href = urllib.parse.unquote(elem.attrib.get("href", ""))
                            media_type = elem.attrib.get("media-type", "")
                            if item_id:
                                manifest_ids.add(item_id)
                            if href:
                                resolved = _resolve_epub_path(opf_dir, href)
                                if resolved.startswith(".."):
                                    missing_manifest_files += 1
                                    issues.append(
                                        ValidationIssue(
                                            "error",
                                            "OPF-002",
                                            opf_path,
                                            f"Manifest item '{href}' attempts path traversal outside container.",
                                        )
                                    )
                                elif resolved not in namelist_set:
                                    missing_manifest_files += 1
                                    issues.append(
                                        ValidationIssue(
                                            "error",
                                            "RSC-001",
                                            opf_path,
                                            f"Referenced manifest resource '{resolved}' is missing from archive.",
                                        )
                                    )
                                elif "xhtml" in media_type or resolved.endswith((".xhtml", ".html")):
                                    xhtml_files.append(resolved)

                    spine_errors = 0
                    for elem in opf_root.iter():
                        if elem.tag.endswith("itemref"):
                            idref = elem.attrib.get("idref", "")
                            if idref and idref not in manifest_ids:
                                spine_errors += 1
                                issues.append(
                                    ValidationIssue(
                                        "error",
                                        "OPF-003",
                                        opf_path,
                                        f"Spine itemref '{idref}' does not match any manifest item ID.",
                                    )
                                )

                    if missing_manifest_files == 0 and spine_errors == 0:
                        opf_manifest_ok = True
                except ET.ParseError as exc:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "XML-002",
                            opf_path,
                            f"Malformed XML in OPF package document: {exc}",
                        )
                    )

        # Fallback: also include any .xhtml/.html files in the archive even if OPF was omitted in a minimal test fixture
        for name in sorted(namelist_set):
            if name.endswith((".xhtml", ".html")) and name not in xhtml_files:
                xhtml_files.append(name)

        # 4. Pass 1 on XHTML files: Check XML well-formedness and collect all valid target IDs per file
        ids_by_file: dict[str, set[str]] = {}
        soups_by_file: dict[str, BeautifulSoup] = {}

        for xfile in xhtml_files:
            raw_bytes = zf.read(xfile)
            try:
                ET.fromstring(raw_bytes)
            except ET.ParseError as exc:
                xhtml_well_formed_ok = False
                issues.append(
                    ValidationIssue(
                        "error",
                        "HTM-001",
                        xfile,
                        f"XHTML document is not well-formed XML: {exc}",
                    )
                )

            text_content = raw_bytes.decode("utf-8", errors="replace")
            soup = BeautifulSoup(text_content, "html.parser")
            soups_by_file[xfile] = soup
            file_ids: set[str] = set()
            for tag in soup.find_all(True):
                tid = tag.get("id") or tag.get("name")
                if tid:
                    file_ids.add(str(tid))
            ids_by_file[xfile] = file_ids

        # 5. Pass 2 on XHTML files: Generic internal reference & fragment resolver
        for xfile, soup in soups_by_file.items():
            xdir = posixpath.dirname(xfile)
            ref_candidates: list[tuple[str, str]] = []

            for tag in soup.find_all(["a", "link"]):
                href = tag.get("href")
                if href:
                    ref_candidates.append((tag.name, str(href)))

            for tag in soup.find_all(["img", "image", "audio", "video"]):
                src = tag.get("src") or tag.get("xlink:href") or tag.get("href")
                if src:
                    ref_candidates.append((tag.name, str(src)))

            for tag_name, raw_ref in ref_candidates:
                ref = raw_ref.strip()
                if not ref or ref.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")):
                    continue

                checked_links += 1
                parsed = urllib.parse.urlsplit(ref)
                rel_path = urllib.parse.unquote(parsed.path)
                fragment = urllib.parse.unquote(parsed.fragment)

                target_file = _resolve_epub_path(xdir, rel_path) if rel_path else xfile

                if target_file.startswith(".."):
                    broken_links += 1
                    issues.append(
                        ValidationIssue(
                            "error",
                            "RSC-004",
                            xfile,
                            f"<{tag_name}> reference '{raw_ref}' escapes the EPUB container.",
                        )
                    )
                    continue

                if target_file not in namelist_set:
                    broken_links += 1
                    issues.append(
                        ValidationIssue(
                            "error",
                            "RSC-005",
                            xfile,
                            f"<{tag_name}> reference '{raw_ref}' points to missing file '{target_file}'.",
                        )
                    )
                    continue

                if fragment and target_file in ids_by_file:
                    if fragment not in ids_by_file[target_file]:
                        broken_links += 1
                        issues.append(
                            ValidationIssue(
                                "error",
                                "RSC-006",
                                xfile,
                                f"<{tag_name}> reference '{raw_ref}' points to missing anchor '#{fragment}' in '{target_file}'.",
                            )
                        )

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationSummary(
        is_valid=not has_errors,
        checked_files=checked_files,
        checked_links=checked_links,
        broken_links=broken_links,
        mimetype_ok=mimetype_ok,
        container_xml_ok=container_xml_ok,
        opf_manifest_ok=opf_manifest_ok,
        xhtml_well_formed_ok=xhtml_well_formed_ok,
        issues=issues,
    )
