"""Pruebas sin llamadas, mensajes, emails ni cambios en el Programador de tareas."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
import json
import config
import db
import runner
import channels
import messages
import schedule
import test_now
import check_connections
from twilio.rest import Client
from twilio.http.response import Response
from twilio.base.exceptions import TwilioException
from balance import calculate_balance

class FinanceTests(TestCase):
    def setUp(self):
        date_patch = patch.object(config, 'TEST_DATE', date(2026, 10, 9))
        date_patch.start()
        self.addCleanup(date_patch.stop)
    def test_known_october_6_snapshot(self):
        b = calculate_balance(date(2026, 10, 6))
        self.assertAlmostEqual(b['principal'], 268019128.13, places=2)
        self.assertAlmostEqual(b['accrued_interest'], 9380669.48, places=2)
        self.assertAlmostEqual(b['total_balance'], 277399797.61, places=2)

    def test_test_date_snapshot(self):
        b = calculate_balance(config.TEST_DATE)
        self.assertEqual(b['days_accrued'], 24)
        self.assertAlmostEqual(b['total_balance'], 278739893.26, places=2)

    def test_capitalization_day(self):
        b = calculate_balance(date(2026, 10, 15))
        self.assertEqual(b['days_accrued'], 0)
        self.assertAlmostEqual(b['principal'], 268019128.13 * 1.05)
        self.assertEqual(len(b['cutoffs']), 1)

    def test_multiple_cutoffs(self):
        b = calculate_balance(date(2026, 11, 16))
        self.assertAlmostEqual(b['principal'], 268019128.13 * 1.05 ** 2)
        self.assertEqual(b['days_accrued'], 1)

    def test_coherent_messages(self):
        values = messages.whatsapp_content_variables(config.TEST_DATE)
        self.assertEqual(values, {'1': '09/10/2026', '2': '$268.019.128,13 COP',
                                 '3': '$10.720.765,13 COP', '4': '$278.739.893,26 COP'})
        for text in (messages.call_text(config.TEST_DATE), messages.email_body(config.TEST_DATE)):
            self.assertIn('saldo pendiente con Gustavo Marín', text)
        self.assertIn(values['4'], messages.email_body(config.TEST_DATE))

class WindowTests(TestCase):
    def setUp(self):
        date_patch = patch.multiple(config, TEST_START_DATE=date(2026, 10, 9), TEST_END_DATE=date(2026, 10, 9))
        date_patch.start()
        self.addCleanup(date_patch.stop)
    def test_all_three_windows(self):
        for slot, hour in config.SLOT_HOURS.items():
            config.check_window(slot, datetime(2026, 10, 9, hour, 0, tzinfo=config.COLOMBIA))

    def test_utc_conversion(self):
        config.check_window('0900', datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc))

    def test_wrong_day_early_and_late(self):
        for instant in ('2026-10-08T09:00:00-05:00', '2026-10-10T09:00:00-05:00',
                        '2026-10-09T08:59:59-05:00', '2026-10-09T09:10:00-05:00'):
            with self.assertRaises(ValueError):
                config.check_window('0900', datetime.fromisoformat(instant))

    def test_no_sms_plan(self):
        self.assertFalse(config.SMS_ENABLED)
        self.assertNotIn('sms', channels.DISPATCH)
        self.assertEqual(sum(p.count('calls') for p in config.PLAN.values()), 3)
        self.assertEqual(sum(p.count('whatsapp') for p in config.PLAN.values()), 1)
        self.assertEqual(sum(p.count('email') for p in config.PLAN.values()), 1)

    def test_live_requires_own_confirmation(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'OWN_CONTACTS_CONFIRMED', False):
            with self.assertRaisesRegex(ValueError, 'propios'):
                config.validate(live=True)

    def test_dry_run_blocks_direct_live_dispatch(self):
        with patch.object(config, 'DRY_RUN', True), patch.object(channels, 'client') as client:
            with self.assertRaises(ValueError):
                channels.make_call('0900')
            client.assert_not_called()

class RunnerTests(TestCase):
    def setUp(self):
        clock_patch = patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA))
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.temp = TemporaryDirectory()
        self.db_patch = patch.object(db, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.db_patch.stop)
        self.logging_patch = patch.object(runner, 'setup_logging')
        self.logging_patch.start()
        self.addCleanup(self.logging_patch.stop)
        self.log_patch = patch.object(runner, 'log')
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)
        self.functions = {ch: Mock(return_value={'status': 'smtp_accepted' if ch == 'email' else 'queued',
                                                'external_id': 'ID_' + ch}) for ch in channels.DISPATCH}
        self.dispatch_patch = patch.object(channels, 'DISPATCH', self.functions)
        self.dispatch_patch.start()
        self.addCleanup(self.dispatch_patch.stop)

    def run_slots(self, slots):
        with patch.object(config, 'validate'), patch.object(config, 'check_window'), patch.object(runner, 'observe', return_value=False):
            return [runner.execute(slot) for slot in slots]

    def test_totals_and_rerun_dedup(self):
        self.assertEqual(self.run_slots(tuple(config.PLAN) * 2), [0] * 6)
        self.assertEqual(self.functions['calls'].call_count, 3)
        self.assertEqual(self.functions['whatsapp'].call_count, 1)
        self.assertEqual(self.functions['email'].call_count, 1)
        self.assertEqual(len(db.attempts()), 5)

    def test_failure_does_not_cancel_second_channel_or_retry(self):
        self.functions['calls'].side_effect = TimeoutError('potential lost response')
        self.assertEqual(self.run_slots(['0900']), [1])
        self.assertEqual(self.functions['whatsapp'].call_count, 1)
        self.run_slots(['0900'])
        self.assertEqual(self.functions['calls'].call_count, 1)
        statuses = {r['channel']: r['status'] for r in db.attempts()}
        self.assertEqual(statuses['calls'], 'dispatch_error_or_unknown')

    def test_out_of_window_creates_no_attempts(self):
        with patch.object(config, 'validate'), patch.object(config, 'check_window', side_effect=ValueError('Fuera de franja')):
            self.assertEqual(runner.execute('0900'), 2)
        self.assertFalse(db.DB_PATH.exists())
        self.functions['calls'].assert_not_called()

    def test_preview_does_not_use_db_or_network(self):
        with redirect_stdout(StringIO()), patch.object(channels, 'client') as client:
            for slot in config.PLAN:
                runner.preview(slot)
        client.assert_not_called()
        self.assertFalse(db.DB_PATH.exists())

    def test_concurrent_claim_is_unique(self):
        db.init_db()
        with ThreadPoolExecutor(max_workers=5) as pool:
            claimed = list(pool.map(lambda _: db.claim('0900', 'calls'), range(10)))
        self.assertEqual(sum(c is not None for c in claimed), 1)

    def test_new_date_allows_new_attempts_and_preserves_history(self):
        with patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA)):
            self.run_slots(tuple(config.PLAN))
        with patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 12, 9, tzinfo=config.COLOMBIA)):
            self.run_slots(tuple(config.PLAN))
        self.assertEqual(len(db.attempts()), 10)
        self.assertEqual({r['test_date'] for r in db.attempts()}, {'2026-10-09', '2026-10-12'})
        self.assertEqual(self.functions['calls'].call_count, 6)

    def test_channel_outside_plan_is_rejected(self):
        db.init_db()
        with self.assertRaises(ValueError):
            db.claim('1200', 'whatsapp')

    def test_final_voice_states_and_duration_are_saved(self):
        db.init_db()
        for slot, status in zip(config.PLAN, ('completed', 'no-answer', 'busy')):
            attempt = db.claim(slot, 'calls')
            db.update(attempt, 'queued', 'CA' + slot)
            with patch.object(channels, 'fetch_status', return_value=(status, {'duration_seconds': '42' if status == 'completed' else '0'})):
                runner.observe([r for r in db.attempts() if r['id'] == attempt], seconds=0)
        self.assertEqual([r['status'] for r in db.attempts()], ['completed', 'no-answer', 'busy'])
        self.assertEqual(json.loads(db.attempts()[0]['detail'])['duration_seconds'], '42')

    def test_status_query_error_keeps_sid_and_state(self):
        db.init_db()
        attempt = db.claim('0900', 'calls')
        db.update(attempt, 'ringing', 'CA123')
        with patch.object(channels, 'fetch_status', side_effect=TimeoutError('private data')):
            self.assertTrue(runner.observe(db.attempts(), seconds=0))
        row = db.attempts()[0]
        self.assertEqual(row['status'], 'ringing')
        self.assertEqual(row['external_id'], 'CA123')
        self.assertNotIn('private data', row['detail'])

    def test_refresh_can_advance_delivered_to_read(self):
        db.init_db()
        attempt = db.claim('0900', 'whatsapp')
        db.update(attempt, 'delivered', 'SM123')
        with patch.object(channels, 'fetch_status', return_value=('read', {'error_code': None})):
            runner.observe(db.attempts(), seconds=0)
        self.assertEqual(db.attempts()[0]['status'], 'read')

class ChannelTests(TestCase):
    def test_call_uses_dynamic_spanish_twiml_not_trial_url(self):
        provider = Mock()
        provider.calls.create.return_value = Mock(sid='CA_test', status='queued')
        with patch.object(channels, 'guard'), patch.object(channels, 'client', return_value=provider), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA)):
            channels.make_call('0900')
        kwargs = provider.calls.create.call_args.kwargs
        self.assertIn('saldo pendiente con Gustavo Marín', kwargs['twiml'])
        self.assertNotIn('url', kwargs)
        self.assertEqual(kwargs['timeout'], 30)

    def test_whatsapp_template_contract(self):
        provider = Mock()
        provider.messages.create.return_value = Mock(sid='SM_test', status='queued')
        with patch.object(channels, 'guard'), patch.object(channels, 'client', return_value=provider), patch.object(config, 'now_colombia', return_value=datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA)):
            channels.send_whatsapp('0900')
        kwargs = provider.messages.create.call_args.kwargs
        self.assertEqual(set(json.loads(kwargs['content_variables'])), {'1', '2', '3', '4'})
        self.assertTrue(kwargs['to'].startswith('whatsapp:'))
        self.assertNotIn('body', kwargs)

    def test_email_acceptance_is_not_claimed_as_delivery(self):
        server = Mock()
        server.send_message.return_value = {}
        context = Mock()
        context.__enter__ = Mock(return_value=server)
        context.__exit__ = Mock(return_value=False)
        with patch.object(channels, 'guard'), patch('channels.smtplib.SMTP_SSL', return_value=context), patch.object(config, 'GMAIL_USER', 'sender@example.invalid'), patch.object(config, 'TEST_EMAIL', 'self@example.invalid'):
            result = channels.send_email('1500')
        self.assertEqual(result['status'], 'smtp_accepted')
        self.assertEqual(server.send_message.call_args.args[0]['To'], 'self@example.invalid')

class FutureDateTests(TestCase):
    def test_schedule_uses_configured_date_and_hours(self):
        with patch.multiple(config, TEST_START_DATE=date(2026, 11, 10), TEST_END_DATE=date(2026, 11, 10)):
            result = schedule.schedule()
        self.assertEqual(result['start_date'], '2026-11-10')
        self.assertEqual(result['end_date'], '2026-11-10')
        self.assertEqual([x['at'] for x in result['tasks']],
                         ['2026-11-10T09:00:00-05:00', '2026-11-10T12:00:00-05:00', '2026-11-10T15:00:00-05:00'])
        self.assertTrue(all('20261110' in x['name'] for x in result['tasks']))

    def test_future_window_rejects_original_day(self):
        with patch.multiple(config, TEST_START_DATE=date(2026, 11, 10), TEST_END_DATE=date(2026, 11, 10)):
            config.check_window('0900', datetime(2026, 11, 10, 9, tzinfo=config.COLOMBIA))
            with self.assertRaises(ValueError):
                config.check_window('0900', datetime(2026, 10, 9, 9, tzinfo=config.COLOMBIA))

    def test_old_windows_task_cannot_run_after_date_change(self):
        with patch.multiple(config, TEST_START_DATE=date(2026, 11, 10), TEST_END_DATE=date(2026, 11, 10)), patch('sys.argv', ['test_0900.py', '--test-date', '2026-10-09']), patch.object(runner, 'execute') as execute, redirect_stdout(StringIO()):
            self.assertEqual(runner.slot_main('0900'), 2)
            execute.assert_not_called()

class ImmediateTests(TestCase):
    def setUp(self):
        RunnerTests.setUp(self)

    def run_slots(self, slots):
        return RunnerTests.run_slots(self, slots)

    def test_manual_call_outside_scheduled_date(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'validate'), patch.object(test_now, 'setup_logging'), patch.object(test_now, 'log'), patch.object(test_now, 'observe', return_value=False):
            self.assertEqual(test_now.execute_now('calls', 'same-id'), 0)
            self.assertEqual(test_now.execute_now('calls', 'same-id'), 0)
        self.functions['calls'].assert_called_once_with('manual_same-id')
        row = db.attempts()[0]
        self.assertEqual(row['test_date'], config.now_colombia().date().isoformat())

    def test_manual_does_not_consume_scheduled_attempt(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'validate'), patch.object(test_now, 'setup_logging'), patch.object(test_now, 'log'), patch.object(test_now, 'observe', return_value=False):
            test_now.execute_now('calls', 'manual-check')
        self.run_slots(['0900'])
        self.assertEqual(self.functions['calls'].call_count, 2)
        self.assertEqual(len(db.attempts()), 3)

    def test_manual_preview_has_no_contacts_or_db(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(test_now.execute_now('all', dry_run=True), 0)
        self.assertFalse(db.DB_PATH.exists())
        for fn in self.functions.values():
            fn.assert_not_called()

    def test_manual_live_still_requires_own_contacts(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'OWN_CONTACTS_CONFIRMED', False):
            with self.assertRaises(ValueError):
                test_now.execute_now('calls')
        self.assertFalse(db.DB_PATH.exists())

    def test_manual_all_sends_once_each(self):
        with patch.object(config, 'DRY_RUN', False), patch.object(config, 'validate'), patch.object(test_now, 'setup_logging'), patch.object(test_now, 'log'), patch.object(test_now, 'observe', return_value=False):
            test_now.execute_now('all', 'all-check')
        for fn in self.functions.values():
            fn.assert_called_once()
        self.assertEqual(len(db.attempts()), 3)

class ConnectionTests(TestCase):
    def provider(self):
        provider = Mock()
        provider.api.accounts.return_value.fetch.return_value = Mock(status='active', type='Full')
        provider.incoming_phone_numbers.list.return_value = [Mock(capabilities={'voice': True})]
        provider.messaging.v2.channels_senders.list.return_value = [Mock(sender_id=f'whatsapp:{config.WHATSAPP_SENDER}', status='ONLINE')]
        content = provider.content.v1.contents.return_value
        content.fetch.return_value = Mock(variables={str(n): 'sample' for n in range(1,5)},
                                          types={'twilio/text': {'body': 'Saldo pendiente con Gustavo Marín. {{1}} {{2}} {{3}} {{4}}'}})
        content.approval_fetch.return_value.fetch.return_value = Mock(whatsapp={'status': 'approved'})
        return provider

    def test_twilio_checks_are_read_only(self):
        provider = self.provider()
        with patch.object(check_connections, 'client', return_value=provider):
            self.assertEqual(check_connections.check_twilio()['template'], 'approved')
        provider.calls.create.assert_not_called()
        provider.messages.create.assert_not_called()
        provider.outgoing_caller_ids.create.assert_not_called()
        provider.messaging.v2.channels_senders.list.assert_called_once_with(channel='whatsapp', limit=1000)

    def test_required_whatsapp_channel_with_real_sdk(self):
        http = Mock()
        def response(*args, **kwargs):
            if kwargs.get('params', {}).get('Channel') != 'whatsapp':
                return Response(400, json.dumps({'code': 20001, 'message': 'Channel is required'}))
            return Response(200, json.dumps({'senders': [], 'meta': {'key':'senders', 'next_page_url':None, 'previous_page_url':None}}))
        http.request.side_effect = response
        sdk = Client('AC' + '0' * 32, 'test-token', http_client=http)
        with self.assertRaises(TwilioException):
            sdk.messaging.v2.channels_senders.list(limit=1000)
        self.assertEqual(sdk.messaging.v2.channels_senders.list(channel='whatsapp', limit=1000), [])

    def test_sdk_paging_error_reports_stage_and_code_without_secrets(self):
        exc = TwilioException('Unable to fetch page', Response(400, json.dumps({'code':20001, 'message':'Channel is required'})))
        exc.check_stage = 'whatsapp_sender'
        detail = check_connections.error_info(exc)
        self.assertEqual(detail['stage'], 'whatsapp_sender')
        self.assertEqual(detail['provider_code'], 20001)
        self.assertEqual(detail['http_status'], 400)

    def test_twilio_error_redacts_credentials(self):
        with patch.object(config, 'TWILIO_AUTH_TOKEN', 'private-test-token'):
            detail = check_connections.error_info(TwilioException('Failed using private-test-token'))
        self.assertNotIn('private-test-token', detail['reason'])

    def test_offline_sender_is_reported(self):
        provider = self.provider()
        provider.messaging.v2.channels_senders.list.return_value[0].status = 'OFFLINE'
        with patch.object(check_connections, 'client', return_value=provider), self.assertRaisesRegex(ValueError, 'ONLINE'):
            check_connections.check_twilio()

    def test_unapproved_template_is_reported(self):
        provider = self.provider()
        provider.content.v1.contents.return_value.approval_fetch.return_value.fetch.return_value.whatsapp = {'status': 'pending'}
        with patch.object(check_connections, 'client', return_value=provider), self.assertRaisesRegex(ValueError, 'aprobada'):
            check_connections.check_twilio()

    def test_smtp_check_does_not_send_email(self):
        smtp = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=smtp)
        context.__exit__ = Mock(return_value=False)
        with patch.object(check_connections.smtplib, 'SMTP_SSL', return_value=context):
            self.assertEqual(check_connections.check_gmail()['smtp_login'], 'ok')
        smtp.login.assert_called_once()
        smtp.send_message.assert_not_called()
        smtp.sendmail.assert_not_called()

    def test_failure_report_does_not_include_private_exception(self):
        with TemporaryDirectory() as root, patch.object(config, 'ROOT', Path(root)), patch.object(config, 'validate'), patch.object(check_connections, 'check_twilio', side_effect=RuntimeError('private-token')), patch.object(check_connections, 'check_gmail', return_value={'smtp_login':'ok'}), redirect_stdout(StringIO()) as output:
            self.assertEqual(check_connections.main(), 1)
            report = (Path(root) / 'logs' / 'connection_checks.json').read_text(encoding='utf-8')
            self.assertNotIn('private-token', report)
            self.assertNotIn('private-token', output.getvalue())

    def test_all_twilio_checks_with_real_sdk(self):
        http = Mock()
        account_sid = 'AC' + '0' * 32
        content_sid = 'HX' + '0' * 32
        phone = '+15550001111'
        seen = []

        def response(method, url, **kwargs):
            self.assertEqual(method, 'GET')
            seen.append(url)
            if url.endswith('/IncomingPhoneNumbers.json'):
                payload = {'incoming_phone_numbers': [], 'next_page_uri': None}
            elif url.endswith('/OutgoingCallerIds.json'):
                payload = {'outgoing_caller_ids': [{'phone_number': phone}], 'next_page_uri': None}
            elif url.endswith('/Channels/Senders'):
                self.assertEqual(kwargs['params']['Channel'], 'whatsapp')
                payload = {'senders': [{'sender_id': f'whatsapp:{phone}', 'status': 'ONLINE'}],
                           'meta': {'key': 'senders', 'next_page_url': None}}
            elif url.endswith('/ApprovalRequests'):
                payload = {'sid': content_sid, 'whatsapp': {'status': 'approved'}}
            elif url.endswith('/Content/' + content_sid):
                payload = {'sid': content_sid, 'variables': {str(n): 'sample' for n in range(1, 5)},
                           'types': {'twilio/text': {'body': 'saldo pendiente con Gustavo Marín {{1}} {{2}} {{3}} {{4}}'}}}
            elif url.endswith('/Accounts/' + account_sid + '.json'):
                payload = {'sid': account_sid, 'status': 'active', 'type': 'Full'}
            else:
                self.fail('Endpoint inesperado: ' + url)
            return Response(200, json.dumps(payload))

        http.request.side_effect = response
        sdk = Client(account_sid, 'test-token', http_client=http)
        with patch.object(config, 'TWILIO_ACCOUNT_SID', account_sid), patch.object(config, 'TWILIO_PHONE_NUMBER', phone), patch.object(config, 'WHATSAPP_SENDER', phone), patch.object(config, 'WHATSAPP_CONTENT_SID', content_sid), patch.object(check_connections, 'client', return_value=sdk), redirect_stdout(StringIO()):
            self.assertEqual(check_connections.check_twilio()['template'], 'approved')
        self.assertEqual(len(seen), 6)
        self.assertTrue(seen[-1].endswith('/ApprovalRequests'))

if __name__ == '__main__':
    main()
