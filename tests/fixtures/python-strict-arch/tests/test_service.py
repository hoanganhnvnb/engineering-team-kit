import unittest

from app.service import make_service


class RegisterTests(unittest.TestCase):
    def test_register_lowercases_email(self):
        svc = make_service()
        user = svc.register("  Ann@Example.COM ", "Ann")
        self.assertEqual(user.email, "ann@example.com")

    def test_duplicate_email_rejected(self):
        svc = make_service()
        svc.register("a@x.io", "A")
        with self.assertRaises(ValueError):
            svc.register("A@x.io", "A2")


if __name__ == "__main__":
    unittest.main()
