from celery import shared_task
import requests
from .models import PriceAlert, NotificationLog


@shared_task
def check_prices():
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)
    routes = active_alerts.values_list('origin', 'destination').distinct()

    for origin, destination in routes:
        route = f'{origin}-{destination}'

        response = requests.get(
            'http://localhost:8000/api/flights/price/',
            params={'route': route}
        )

        if response.status_code != 200:
            continue

        current_price = response.json().get('price')

        route_alerts = active_alerts.filter(origin=origin, destination=destination)

        for alert in route_alerts:
            if current_price <= float(alert.threshold_price):
                send_notification.delay(alert.id, current_price)


@shared_task
def send_notification(alert_id, triggered_price):
    alert = PriceAlert.objects.get(id=alert_id)
    message = (
        f'Price alert triggered! {alert.origin}-{alert.destination} '
        f'is now \u20b9{triggered_price} - below your threshold of '
        f'\u20b9{alert.threshold_price}'
    )

    NotificationLog.objects.create(
        alert=alert,
        triggered_price=triggered_price,
        message=message
    )

    alert.status = PriceAlert.Status.TRIGGERED
    alert.save()