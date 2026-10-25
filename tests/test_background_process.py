"""Windowless launch contracts; no real subprocesses or agents."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import background_process as background


class BackgroundProcessTests(unittest.TestCase):
    def test_run_and_popen_preserve_options_and_hide_windows(self):
        with patch.object(background.os,'name','nt'),patch.object(background.subprocess,'CREATE_NO_WINDOW',0x08000000,create=True):
            for method,target in ((background.run,'run'),(background.popen,'Popen')):
                with patch.object(background.subprocess,target) as launch:
                    method(['fixture'],creationflags=8,cwd='fixture',stdout='capture')
                    self.assertEqual(launch.call_args.kwargs['creationflags'],0x08000008)
                    self.assertEqual(launch.call_args.kwargs['stdout'],'capture')
                    self.assertEqual(launch.call_args.kwargs['cwd'],'fixture')

    def test_other_platforms_keep_their_launch_options(self):
        with patch.object(background.os,'name','posix'):
            self.assertEqual(background.options({'cwd':'fixture'}),{'cwd':'fixture'})


class GhExecutableTests(unittest.TestCase):
    def test_falls_back_to_program_files_when_path_lacks_gh(self):
        import os,tempfile
        with tempfile.TemporaryDirectory() as root:
            folder=os.path.join(root,'GitHub CLI');os.mkdir(folder)
            with open(os.path.join(folder,'gh.exe'),'w',encoding='utf-8') as handle:handle.write('x')
            with patch.object(background.shutil,'which',return_value=None),patch.dict(os.environ,{'ProgramFiles':root}):
                self.assertEqual(background.gh_executable(),os.path.join(folder,'gh.exe'))


if __name__=='__main__':unittest.main()
