"""Calendario continuo, cancelacion y reservas: sin contactos reales."""
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import channels
import config
import db
import report
import runner
import schedule


class ContinuousTests(TestCase):
    def setUp(self):
        mode = patch.multiple(config, TEST_SCHEDULE_MODE='continuous', TEST_ENABLED=True,
                              TEST_START_DATE=None, TEST_END_DATE=None)
        mode.start()
        self.addCleanup(mode.stop)

    def test_daily_plan_is_three_tasks_without_end(self):
        now = datetime(2026, 11, 18, 14, 30, tzinfo=config.COLOMBIA)
        with patch.object(config, 'now_colombia', return_value=now):
            plan = schedule.schedule()
        self.assertIsNone(plan['start_date'])
        self.assertIsNone(plan['end_date'])
        self.assertIsNone(plan['awake']['until'])
        self.assertEqual(len(plan['tasks']), 3)
        self.assertEqual(plan['daily_totals'], {'calls': 3, 'whatsapp': 1, 'email': 1, 'sms': 0})
        self.assertEqual(plan['tasks'][0]['at'], '2026-11-19T09:00:00-05:00')
        self.assertEqual(plan['tasks'][2]['at'], '2026-11-18T15:00:00-05:00')
        self.assertTrue(all('test_date' not in row for row in plan['tasks']))

    def test_continuous_window_allows_future_years_but_not_late_attempts(self):
        for year in (2026, 2030, 2040):
            now = datetime(year, 12, 31, 9, 8, tzinfo=config.COLOMBIA)
            self.assertEqual(config.check_window('0900', now), now.date())
            with self.assertRaises(ValueError):
                config.check_window('0900', now.replace(minute=10))

    def test_no_infinite_date_enumeration(self):
        with self.assertRaises(ValueError):
            list(config.test_days())

    def test_daily_balance_validation_does_not_require_dates(self):
        with patch.object(config, 'now_colombia', return_value=datetime(2026, 11, 18, 12, tzinfo=config.COLOMBIA)):
            config.validate()

    def test_cancelled_automation_dispatches_nothing(self):
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(config, 'TEST_ENABLED', False), patch.object(config, 'validate'), patch.object(config, 'now_colombia', return_value=datetime(2026, 11, 18, 9, tzinfo=config.COLOMBIA)), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(channels, 'client') as client:
            self.assertEqual(runner.execute('0900'), 2)
            self.assertFalse(db.DB_PATH.exists())
            client.assert_not_called()
            self.assertEqual(report.missing_attempts([]), [])

    def test_reservations_stay_separate_by_day_and_dedup_minute_retries(self):
        dispatch = {name: Mock(return_value={'status':'queued', 'external_id':'fake-'+name}) for name in config.PLAN['0900']}
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(config, 'validate'), patch.object(channels, 'DISPATCH', dispatch), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(runner, 'observe', return_value=False):
            for day in (18, 19):
                for minute in (0, 1, 9):
                    with patch.object(config, 'now_colombia', return_value=datetime(2026, 11, day, 9, minute, tzinfo=config.COLOMBIA)):
                        self.assertEqual(runner.execute('0900'), 0)
            self.assertEqual(len(db.attempts()), 4)
        self.assertEqual(dispatch['calls'].call_count, 2)
        self.assertEqual(dispatch['whatsapp'].call_count, 2)

    def test_report_checks_only_today_without_inventing_past_misses(self):
        now = datetime(2030, 6, 2, 9, 11, tzinfo=config.COLOMBIA)
        self.assertEqual(report.missing_attempts([], now), [('2030-06-02','0900','calls'), ('2030-06-02','0900','whatsapp')])

    def test_recurring_names_do_not_change_each_day(self):
        names = []
        for day in (18, 19):
            with patch.object(config, 'now_colombia', return_value=datetime(2026, 11, day, 10, tzinfo=config.COLOMBIA)):
                names.append([row['name'] for row in schedule.schedule()['tasks']])
        self.assertEqual(names[0], names[1])
