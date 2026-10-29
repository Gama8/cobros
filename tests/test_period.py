"""Períodos inclusivos: todos los proveedores y el reloj se simulan."""
from contextlib import redirect_stdout
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import config
import channels
import db
import runner
import schedule
import report
import messages
from balance import calculate_balance


class PeriodTests(TestCase):
    def setUp(self):
        period = patch.multiple(config, TEST_START_DATE=date(2026, 10, 9), TEST_END_DATE=date(2026, 10, 15))
        period.start()
        self.addCleanup(period.stop)

    def test_inclusive_week_has_21_unique_tasks(self):
        result = schedule.schedule()
        self.assertEqual(result['days'], 7)
        self.assertEqual(result['totals'], {'calls': 21, 'whatsapp': 7, 'email': 7, 'sms': 0})
        self.assertEqual(len(result['tasks']), 21)
        self.assertEqual(len({t['name'] for t in result['tasks']}), 21)
        self.assertEqual(result['tasks'][0]['at'], '2026-10-09T09:00:00-05:00')
        self.assertEqual(result['tasks'][-1]['at'], '2026-10-15T15:00:00-05:00')
        for task in result['tasks']:
            self.assertTrue(task['at'].startswith(task['test_date']))
            self.assertIn(task['test_date'].replace('-', ''), task['name'])

    def test_same_start_end_keeps_original_three_tasks(self):
        with patch.object(config, 'TEST_END_DATE', config.TEST_START_DATE):
            result = schedule.schedule()
        self.assertEqual(len(result['tasks']), 3)
        self.assertEqual(result['totals'], {'calls': 3, 'whatsapp': 1, 'email': 1, 'sms': 0})

    def test_reversed_period_is_rejected(self):
        with patch.object(config, 'TEST_END_DATE', date(2026, 10, 8)):
            with self.assertRaisesRegex(ValueError, 'TEST_END_DATE'):
                schedule.schedule()

    def test_period_before_financial_anchor_is_rejected(self):
        with patch.object(config, 'TEST_START_DATE', date(2026, 9, 14)):
            with self.assertRaisesRegex(ValueError, 'ancla'):
                config.validate()

    def test_first_last_and_weekend_days_are_allowed(self):
        for day in (9, 10, 11, 15):
            instant = datetime(2026, 10, day, 9, tzinfo=config.COLOMBIA)
            self.assertEqual(config.check_window('0900', instant), instant.date())

    def test_before_start_and_after_end_are_blocked(self):
        for day in (8, 16):
            with self.assertRaisesRegex(ValueError, 'período'):
                config.check_window('0900', datetime(2026, 10, day, 9, tzinfo=config.COLOMBIA))

    def test_daily_messages_and_capitalization_are_dynamic(self):
        first, second, last = [calculate_balance(date(2026, 10, d)) for d in (9, 10, 15)]
        self.assertGreater(second['total_balance'], first['total_balance'])
        self.assertEqual(last['days_accrued'], 0)
        self.assertGreater(last['principal'], first['principal'])
        self.assertEqual(messages.whatsapp_content_variables(date(2026, 10, 15))['1'], '15/10/2026')
        self.assertIn('15 de octubre', messages.call_text(date(2026, 10, 15)))

    def test_stale_task_for_another_day_cannot_dispatch(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 10, 9, tzinfo=config.COLOMBIA)), patch('sys.argv', ['test_0900.py', '--test-date', '2026-10-09']), patch.object(runner, 'execute') as execute, redirect_stdout(StringIO()):
            self.assertEqual(runner.slot_main('0900'), 2)
        execute.assert_not_called()

    def test_future_day_preview_is_allowed_without_dispatch(self):
        with patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA)), patch('sys.argv', ['test_0900.py', '--test-date', '2026-10-12', '--dry-run']), patch.object(channels, 'client') as client, patch.object(db, 'init_db') as database, redirect_stdout(StringIO()) as output:
            self.assertEqual(runner.slot_main('0900'), 0)
        self.assertIn('12/10/2026', output.getvalue())
        client.assert_not_called()
        database.assert_not_called()

    def test_malformed_task_date_is_blocked(self):
        with patch('sys.argv', ['test_0900.py', '--test-date', 'today()']), patch.object(runner, 'execute') as execute, redirect_stdout(StringIO()):
            self.assertEqual(runner.slot_main('0900'), 2)
        execute.assert_not_called()

    def test_whole_week_dedup_and_daily_history(self):
        dispatch = {channel: Mock(return_value={'status': 'queued', 'external_id': 'fake-' + channel}) for channel in channels.DISPATCH}
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(channels, 'DISPATCH', dispatch), patch.object(config, 'validate'), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(runner, 'observe', return_value=False):
            for day in config.test_days():
                for slot, hour in config.SLOT_HOURS.items():
                    instant = datetime(day.year, day.month, day.day, hour, tzinfo=config.COLOMBIA)
                    with patch.object(config, 'now_colombia', return_value=instant):
                        self.assertEqual(runner.execute(slot), 0)
                        self.assertEqual(runner.execute(slot), 0)
            rows = db.attempts()
            self.assertEqual(len(rows), 35)
            for day in config.test_days():
                self.assertEqual(len([row for row in rows if row['test_date'] == day.isoformat()]), 5)
            with db.connect() as connection:
                snapshots = connection.execute('SELECT snapshot_date,total_balance FROM balance_snapshots').fetchall()
            for snapshot in snapshots:
                self.assertAlmostEqual(snapshot['total_balance'], calculate_balance(date.fromisoformat(snapshot['snapshot_date']))['total_balance'])
        self.assertEqual(dispatch['calls'].call_count, 21)
        self.assertEqual(dispatch['whatsapp'].call_count, 7)
        self.assertEqual(dispatch['email'].call_count, 7)

    def test_after_period_creates_no_contacts_or_database(self):
        dispatch = {channel: Mock() for channel in channels.DISPATCH}
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(channels, 'DISPATCH', dispatch), patch.object(config, 'validate'), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 16, 9, tzinfo=config.COLOMBIA)), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'):
            self.assertEqual(runner.execute('0900'), 2)
            self.assertFalse(db.DB_PATH.exists())
        for sender in dispatch.values():
            sender.assert_not_called()

    def test_recovery_schedule_stays_inside_contact_window(self):
        result = schedule.schedule()
        self.assertEqual(result['launch_retry']['interval_seconds'], 60)
        self.assertEqual(result['launch_retry']['duration_seconds'], 570)
        self.assertLess(result['launch_retry']['duration_seconds'], config.WINDOW_MINUTES * 60)
        self.assertEqual(result['awake']['until'], '2026-10-15T15:15:00-05:00')

    def test_minute_restarts_do_not_duplicate_contacts_or_snapshots(self):
        dispatch = {channel: Mock(return_value={'status': 'queued', 'external_id': 'fake-' + channel}) for channel in channels.DISPATCH}
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(channels, 'DISPATCH', dispatch), patch.object(config, 'validate'), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(runner, 'observe', return_value=False):
            for minute in range(10):
                with patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, minute, tzinfo=config.COLOMBIA)):
                    self.assertEqual(runner.execute('0900'), 0)
            self.assertEqual(len(db.attempts()), 2)
            with db.connect() as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM balance_snapshots').fetchone()[0], 1)
        dispatch['calls'].assert_called_once_with('0900')
        dispatch['whatsapp'].assert_called_once_with('0900')
        dispatch['email'].assert_not_called()

    def test_missed_launch_recovers_at_0908_without_resending_reserved_call(self):
        dispatch = {channel: Mock(return_value={'status': 'queued', 'external_id': 'fake-' + channel}) for channel in channels.DISPATCH}
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(channels, 'DISPATCH', dispatch), patch.object(config, 'validate'), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(runner, 'observe', return_value=False), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, 8, tzinfo=config.COLOMBIA)):
            db.init_db()
            db.claim('0900', 'calls')
            self.assertEqual(runner.execute('0900'), 0)
            self.assertEqual(len(db.attempts()), 2)
        dispatch['calls'].assert_not_called()
        dispatch['whatsapp'].assert_called_once_with('0900')

    def test_recovery_at_0910_is_blocked(self):
        with TemporaryDirectory() as folder, patch.object(db, 'DB_PATH', Path(folder) / 'test.sqlite3'), patch.object(config, 'validate'), patch.object(runner, 'setup_logging'), patch.object(runner, 'log'), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, 10, tzinfo=config.COLOMBIA)), patch.object(channels, 'client') as provider:
            self.assertEqual(runner.execute('0900'), 2)
            self.assertFalse(db.DB_PATH.exists())
        provider.assert_not_called()

    def test_missing_report_marks_only_expired_slots(self):
        now = datetime(2026, 10, 9, 9, 10, tzinfo=config.COLOMBIA)
        self.assertEqual(report.missing_attempts([], now), [('2026-10-09', '0900', 'calls'), ('2026-10-09', '0900', 'whatsapp')])
        self.assertEqual(report.missing_attempts([], now.replace(minute=9)), [])

    def test_manual_attempt_does_not_hide_a_missed_scheduled_slot(self):
        now = datetime(2026, 10, 9, 9, 40, tzinfo=config.COLOMBIA)
        rows = [{'test_date': '2026-10-09', 'slot': 'manual_retry', 'channel': 'calls'}]
        self.assertEqual(len(report.missing_attempts(rows, now)), 2)
        rows.append({'test_date': '2026-10-09', 'slot': '0900', 'channel': 'calls'})
        self.assertEqual(report.missing_attempts(rows, now), [('2026-10-09', '0900', 'whatsapp')])
