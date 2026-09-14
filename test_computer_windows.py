import unittest
from unittest.mock import Mock, patch
from core.computer_control import ComputerController


class WindowScopeTests(unittest.TestCase):
    def setUp(self):
        self.backend=Mock()
        self.backend.stopped.return_value=False
        self.backend.capture.return_value=(b'image',100,80,123)
        self.backend.windows.return_value=[{'id':'123','pid':5,'title':'Editor','bounds':[10,10,90,70]}]
        self.controller=ComputerController(self.backend)
        self.controller.enable('task',vision_model='vision',window_id='123')

    def test_other_foreground_cannot_be_observed(self):
        self.backend.capture.return_value=(b'image',100,80,456)
        with self.assertRaises(PermissionError): self.controller.observe('task')
        self.assertIsNone(self.controller.snapshot)

    def test_click_outside_selected_window_is_blocked(self):
        snapshot,_=self.controller.observe('task')
        with self.assertRaises(PermissionError):
            self.controller.act('task',snapshot['snapshot_id'],'click',x=1,y=1)
        self.backend.act.assert_not_called()

    def test_reused_window_handle_cannot_inherit_access(self):
        self.backend.windows.return_value=[{'id':'123','pid':9,'title':'Other','bounds':[10,10,90,70]}]
        with self.assertRaises(PermissionError): self.controller.observe('task')
        self.assertFalse(self.controller.status()['enabled'])

    def test_scroll_is_targeted_inside_selected_window(self):
        snapshot,_=self.controller.observe('task')
        self.controller.act('task',snapshot['snapshot_id'],'scroll',amount=1)
        self.assertEqual(self.backend.act.call_args.kwargs['allowed_window'],'123')
        self.assertEqual((self.backend.act.call_args.kwargs['x'],self.backend.act.call_args.kwargs['y']),(50,40))

    def test_valid_click_passes_scope_to_native_boundary(self):
        snapshot,_=self.controller.observe('task')
        self.controller.act('task',snapshot['snapshot_id'],'click',x=20,y=20)
        self.assertEqual(self.backend.act.call_args.kwargs['allowed_window'],'123')

    def test_vision_exception_invalidates_only_its_snapshot(self):
        from core.computer_control import computer_observe, invoking_task
        token=invoking_task.set('task')
        try:
            with patch('core.computer_control.controller',self.controller),patch('spellbook.llm_client.chat',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError): computer_observe()
            self.assertIsNone(self.controller.snapshot)
        finally:
            invoking_task.reset(token)

    def test_native_pointer_boundary_rejects_covering_window(self):
        from core.computer_control import WindowsDesktop
        desktop=object.__new__(WindowsDesktop)
        desktop.u=Mock()
        desktop.u.GetForegroundWindow.return_value=123
        desktop.u.GetAsyncKeyState.return_value=0
        desktop.u.WindowFromPoint.return_value=456
        desktop.u.GetAncestor.return_value=456
        desktop._send=Mock()
        with self.assertRaises(PermissionError):
            desktop.act('click',x=20,y=20,expected_window=123,allowed_window='123')
        desktop.u.SetPhysicalCursorPos.assert_not_called()
        desktop._send.assert_not_called()


def test_window_inventory_requires_local_ui_header():
    from api import server
    from conftest import SynchronousASGIClient
    client=SynchronousASGIClient(server.app)
    try:
        with patch('core.computer_control.WindowsDesktop') as desktop:
            assert client.get('/computer/windows').status_code==403
            desktop.assert_not_called()
            desktop.return_value.windows.return_value=[]
            assert client.get('/computer/windows',headers={'X-Vaelor-Computer':'1'}).json()=={'windows':[]}
    finally:
        client.close()
