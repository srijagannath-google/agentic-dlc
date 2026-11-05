"""Unit tests for the pure business rules (BR-01…BR-07) and the workflow guards — `python3 -m unittest discover -s src/backend -p 'test_*.py'`."""
import datetime as dt
import unittest

import repositories as repos
import workflow as wf


class FakePayroll:
    def __init__(self, ok=True):
        self.ok = ok

    def post(self, row):
        return (True, 201, "PAY-TEST") if self.ok else (False, 503, None)


class RulesTest(unittest.TestCase):
    def test_br01_available(self):
        self.assertEqual(wf.available_hours(40, 0, 8), 32)

    def test_br02_threshold(self):
        self.assertFalse(wf.requires_certification(40, "Vacation"))
        self.assertTrue(wf.requires_certification(40.5, "Vacation"))
        self.assertTrue(wf.requires_certification(1, "Exception"))

    def test_br03_lead_time(self):
        today = dt.date(2031, 3, 2)
        self.assertFalse(wf.lead_time_ok(dt.date(2031, 3, 4), today, "Vacation"))
        self.assertTrue(wf.lead_time_ok(dt.date(2031, 3, 5), today, "Vacation"))
        self.assertTrue(wf.lead_time_ok(dt.date(2031, 3, 4), today, "Exception"))

    def test_br04_overlap(self):
        d = dt.date
        self.assertTrue(wf.overlaps(d(2031, 6, 12), d(2031, 6, 16), d(2031, 6, 9), d(2031, 6, 13)))
        self.assertFalse(wf.overlaps(d(2031, 6, 14), d(2031, 6, 16), d(2031, 6, 9), d(2031, 6, 13)))

    def test_br06_reason(self):
        base = {"leaveType": "Vacation", "startDate": "2031-04-01", "endDate": "2031-04-01", "hours": 8}
        wf.validate_input({**base, "reason": "x" * 500})
        with self.assertRaises(wf.WorkflowError) as cm:
            wf.validate_input({**base, "reason": "x" * 501})
        self.assertIn("remove 1 characters", cm.exception.message)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.repo = repos.Repository(":memory:", reset=False)
        repos.seed_demo(self.repo)
        self.svc = wf.WorkflowService(self.repo, FakePayroll(), lambda: dt.date(2031, 3, 2))
        self.alex = wf.Actor(wf.EMPLOYEE, "EMP-10042", "Alex Rivera")
        self.morgan = wf.Actor(wf.MANAGER, "EMP-20001", "Morgan Lee")
        self.priya = wf.Actor(wf.HR_CERTIFIER, "EMP-30001", "Priya Nair")

    def test_happy_path_routes_by_br02_and_posts(self):
        ref = self.svc.create(self.alex, {"leaveType": "Vacation", "startDate": "2031-09-01", "endDate": "2031-09-01", "hours": 8})
        self.svc.apply(self.alex, ref, "Submit")
        self.svc.apply(self.morgan, ref, "Manager Approve")
        self.assertEqual(self.repo.get_request(ref)["status"], "POSTED")
        ref2 = self.svc.create(self.alex, {"leaveType": "Vacation", "startDate": "2031-10-01", "endDate": "2031-10-05", "hours": 48})
        self.svc.apply(self.alex, ref2, "Submit")
        self.svc.apply(self.morgan, ref2, "Manager Approve")
        self.assertEqual(self.repo.get_request(ref2)["status"], "MANAGER_APPROVED")
        self.svc.apply(self.priya, ref2, "Certify")
        self.assertEqual(self.repo.get_request(ref2)["status"], "POSTED")

    def test_state_and_role_guards(self):
        with self.assertRaises(wf.WorkflowError) as cm:
            self.svc.apply(self.alex, "LR-1001", "Submit")
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(wf.WorkflowError) as cm:
            self.svc.apply(self.alex, "LR-1006", "Manager Approve")
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(wf.WorkflowError) as cm:
            self.svc.apply(self.morgan, "LR-1003", "Manager Approve")  # not a direct report
        self.assertEqual(cm.exception.status, 403)
        denied = [e for e in self.repo.audit_entries("LR-1001") if e["outcome"] == "denied"]
        self.assertTrue(denied)

    def test_return_requires_comment(self):
        with self.assertRaises(wf.WorkflowError) as cm:
            self.svc.apply(self.morgan, "LR-1006", "Return", {"comment": " "})
        self.assertEqual(cm.exception.code, "COMMENT_REQUIRED")
        self.svc.apply(self.morgan, "LR-1006", "Return", {"comment": "Please shorten"})
        self.assertEqual(self.repo.get_request("LR-1006")["status"], "DRAFT")

    def test_payroll_failure_keeps_approved(self):
        svc = wf.WorkflowService(self.repo, FakePayroll(ok=False), lambda: dt.date(2031, 3, 2))
        ref = svc.create(self.alex, {"leaveType": "Sick", "startDate": "2031-09-10", "endDate": "2031-09-10", "hours": 8})
        svc.apply(self.alex, ref, "Submit")
        svc.apply(self.morgan, ref, "Manager Approve")
        self.assertEqual(self.repo.get_request(ref)["status"], "APPROVED")
        self.assertEqual(self.repo.last_posting(ref)["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
