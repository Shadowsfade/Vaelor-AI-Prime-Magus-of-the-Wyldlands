import unittest
from unittest.mock import patch
from core.software_platforms.windows import WindowsAdapter

class GenericSoftwareTests(unittest.TestCase):
    def test_arbitrary_names_are_actionable(self):
        adapter=WindowsAdapter()
        for name in ("O3DE","Blender","Godot","CMake","Frobnicator"):
            request=adapter.canonicalize_program("download "+name)
            self.assertEqual(request.action,"install")
            self.assertEqual(request.requested_program.lower(),name.lower())

    def test_explicit_download_only_and_clone_semantics(self):
        adapter=WindowsAdapter()
        self.assertEqual(adapter.canonicalize_program("download the Blender installer but don't install it").action,"download_only")
        self.assertEqual(adapter.canonicalize_program("clone Blender source only").action,"clone")

    def test_unknown_resolution_blocks_with_discovery_evidence(self):
        adapter=WindowsAdapter(); request=adapter.canonicalize_program("download Frobnicator")
        with patch.object(adapter,"find_executable",return_value=None), patch.object(adapter,"_discover",return_value=([],[{"provider":"winget","status":"unavailable"},{"provider":"chocolatey","status":"unavailable"}])):
            with self.assertRaises(ValueError) as raised: adapter.resolve_source(request)
        self.assertIn("No trusted Windows source",str(raised.exception)); self.assertEqual(len(raised.exception.evidence),2)

    def test_exact_candidate_is_generic(self):
        adapter=WindowsAdapter(); request=adapter.canonicalize_program("install Frobnicator")
        candidate={"name":"Frobnicator","package":"Acme.Frobnicator","version":"1.2.3","source":"winget","score":100}
        with patch.object(adapter,"find_executable",return_value=None), patch.object(adapter,"_discover",return_value=([candidate],[{"provider":"winget","status":"available"}])):
            with patch("core.software_platforms.windows.shutil.which",return_value="winget.exe"):
                source=adapter.resolve_source(request)
        self.assertEqual(source.method,"winget"); self.assertEqual(source.package,"Acme.Frobnicator"); self.assertEqual(source.confidence,"high")
