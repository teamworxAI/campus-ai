import importlib
import unittest


class PackageTests(unittest.TestCase):
    def test_packages_import(self):
        for name in (
            "campus_ai",
            "campus_ai.core",
            "campus_ai.course_access",
            "campus_ai.research_assistant",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
