import unittest


class ImportTests(unittest.TestCase):
    def test_specgate_package_imports(self):
        import specgate

        self.assertEqual(specgate.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
