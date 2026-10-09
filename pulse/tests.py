from unittest.mock import patch
from rest_framework.test import APIClient
from .tasks import check_prices, send_notification
from django.test import TestCase
from django.contrib.auth.models import User
from .models import PriceAlert, NotificationLog



class PriceThresholdTest(TestCase):
    def test_price_below_threshold_triggers_alert(self):
        self.assertTrue(4200 <= 4500)

    def test_price_above_threshold_does_not_trigger(self):
        self.assertFalse(5000 <= 4500)

    def test_price_equal_to_threshold_triggers_alert(self):
        self.assertTrue(4500 <= 4500)


class NotificationLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin='DEL', destination='BOM',
            threshold_price=4500,
            status=PriceAlert.Status.ACTIVE
        )

    def test_notification_log_created_with_correct_message(self):
        log = NotificationLog.objects.create(
            alert=self.alert,
            triggered_price=4200,
            message='Price dropped to 4200 for DEL-BOM'
        )
        self.assertEqual(log.triggered_price, 4200)
        self.assertEqual(log.alert, self.alert)
        self.assertIn('DEL-BOM', log.message)


class AlertScopingTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', password='pass')
        self.user2 = User.objects.create_user(username='user2', password='pass')

        PriceAlert.objects.create(
            user=self.user1, origin='DEL', destination='BOM', threshold_price=4500
        )
        PriceAlert.objects.create(
            user=self.user2, origin='BLR', destination='HYD', threshold_price=2000
        )

    def test_user_only_sees_own_alerts(self):
        user1_alerts = PriceAlert.objects.filter(user=self.user1)
        self.assertEqual(user1_alerts.count(), 1)
        self.assertEqual(user1_alerts.first().origin, 'DEL')

    def test_user_cannot_see_other_users_alerts(self):
        user1_alerts = PriceAlert.objects.filter(user=self.user1)
        self.assertNotEqual(user1_alerts.first().origin, 'BLR')

class CheckPricesTaskTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='u', password='p')
        self.alert = PriceAlert.objects.create(
            user=user, origin='DEL', destination='BOM', threshold_price=4500)

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_fires_when_price_below_threshold(self, mock_get, mock_delay):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'route': 'DEL-BOM', 'price': 4200}
        check_prices()
        mock_delay.assert_called_once_with(self.alert.id, 4200)

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_does_not_fire_when_price_above_threshold(self, mock_get, mock_delay):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'route': 'DEL-BOM', 'price': 5000}
        check_prices()
        mock_delay.assert_not_called()

    def test_send_notification_logs_and_marks_triggered(self):
        send_notification(self.alert.id, 4200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)
        self.assertEqual(self.alert.notifications.count(), 1)
        self.assertIn('DEL-BOM', self.alert.notifications.first().message)


class AlertApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user(username='alice', password='pass')
        self.bob = User.objects.create_user(username='bob', password='pass')
        self.alert = PriceAlert.objects.create(
            user=self.alice, origin='DEL', destination='BOM', threshold_price=4500)

    def test_cannot_deactivate_another_users_alert(self):
        self.client.force_authenticate(user=self.bob)
        response = self.client.delete(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(response.status_code, 404)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.ACTIVE)

    def test_owner_can_deactivate_own_alert(self):
        self.client.force_authenticate(user=self.alice)
        response = self.client.delete(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'inactive')

    def test_regular_user_gets_403_on_admin_summary(self):
        self.client.force_authenticate(user=self.alice)
        self.assertEqual(self.client.get('/api/admin/summary/').status_code, 403)

    def test_register_ignores_role_in_body(self):
        response = APIClient().post('/api/auth/register/', {
            'username': 'carol', 'password': 'securepass',
            'email': 'carol@example.com', 'role': 'admin'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['role'], 'user')