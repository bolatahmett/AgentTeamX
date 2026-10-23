import unittest
import team


class ControllerDetection(unittest.TestCase):
    def test_relative_launch_is_a_controller(self):
        self.assertTrue(team.controller_command('c:/python312/python.exe team.py start --resume'))

    def test_absolute_launch_is_a_controller(self):
        self.assertTrue(team.controller_command(team.CONTROLLER+' start'))

    def test_other_scripts_are_not(self):
        self.assertFalse(team.controller_command('python.exe other.py start'))
        self.assertFalse(team.controller_command('python.exe my_team.py start'))

    def test_relative_launch_competes(self):
        row={'ProcessId':1,'Name':'python.exe','CommandLine':'C:\\Python312\\python.exe team.py start --resume'}
        self.assertEqual(team.competing_processes('C:/x',[row]),[row])


if __name__=='__main__':unittest.main()
