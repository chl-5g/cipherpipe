#!/usr/bin/env python3
"""Security regression tests: path traversal in file downloads."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.file.transfer import safe_download_path, DOWNLOAD_DIR


def test_normal_name():
    p = safe_download_path("report.pdf")
    assert p == os.path.join(DOWNLOAD_DIR, "report.pdf")


def test_path_traversal_blocked():
    for evil in ["../../etc/passwd", "../../../tmp/evil", "..\\..\\win.ini", "/etc/shadow"]:
        p = safe_download_path(evil)
        # Result must stay flat inside DOWNLOAD_DIR — no traversal possible
        assert os.path.dirname(p) == DOWNLOAD_DIR
        assert ".." not in os.path.basename(p)
        assert os.path.realpath(p).startswith(os.path.realpath(DOWNLOAD_DIR))


def test_absolute_path_blocked():
    p = safe_download_path("/etc/passwd")
    assert p == os.path.join(DOWNLOAD_DIR, "passwd")


def test_empty_and_dot_names_get_random():
    for bad in ["", ".", "..", "\x00"]:
        p = safe_download_path(bad)
        base = os.path.basename(p)
        assert base.startswith("file_") or base not in ("", ".", "..")
        assert os.path.dirname(p) == DOWNLOAD_DIR


def test_null_byte_stripped():
    p = safe_download_path("evil\x00.txt")
    assert "\x00" not in p
    assert os.path.basename(p) == "evil.txt"


def test_nested_path_flattened():
    p = safe_download_path("a/b/c.txt")
    assert p == os.path.join(DOWNLOAD_DIR, "c.txt")
