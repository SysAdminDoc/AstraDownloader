#!/usr/bin/env python3
"""Safety boundaries for the packaged offscreen review entry point."""
import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from visual_review import prepare_review


def test_normal_launch_does_not_change_environment():
    original = dict(os.environ)
    assert prepare_review(['--portable']) is None
    assert dict(os.environ) == original


@pytest.mark.parametrize('args', [
    ['--review-dir'], ['--review-dir', 'relative'], ['--review-dir', ''],
    ['--review-dir', 'C:/review', '--install'],
    ['--install', '--review-dir', 'C:/review'],
])
def test_review_rejects_ambiguous_arguments(args):
    with pytest.raises(SystemExit):
        prepare_review(args)


def test_review_never_reuses_an_existing_directory(tmp_path):
    sentinel = tmp_path / 'keep.txt'
    sentinel.write_text('keep', encoding='utf-8')
    original = dict(os.environ)
    with pytest.raises(FileExistsError):
        prepare_review(['--review-dir', str(tmp_path)])
    assert sentinel.read_text(encoding='utf-8') == 'keep'
    assert dict(os.environ) == original


def test_review_forces_owned_profile_and_offscreen(tmp_path):
    with patch.dict(os.environ, {'QT_QPA_PLATFORM': 'windows', 'ASTRA_PORTABLE': '1'}):
        root = prepare_review(['--review-dir', str(tmp_path / 'new')])
        assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'
        assert os.environ['QT_SCALE_FACTOR'] == '1'
        assert 'ASTRA_PORTABLE' not in os.environ
        for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
            assert Path(os.environ[name]).is_relative_to(root)
            assert Path(os.environ[name]).is_dir()


def test_frozen_worker_guard_precedes_other_imports():
    entry = Path(__file__).with_name('astra_downloader.py')
    nodes = ast.parse(entry.read_text(encoding='utf-8')).body
    assert isinstance(nodes[1], ast.Import)
    assert nodes[1].names[0].name == 'multiprocessing'
    assert ast.unparse(nodes[2]) == 'multiprocessing.freeze_support()'
    hook = Path(__file__).with_name('runtime_hook_mp.py').read_text(encoding='utf-8')
    assert 'multiprocessing.freeze_support()' in hook
    build = Path(__file__).with_name('build.py').read_text(encoding='utf-8')
    assert '"--runtime-hook", str(HERE / "runtime_hook_mp.py")' in build
