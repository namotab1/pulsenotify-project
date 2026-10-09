# PulseNotify - Flight Price Monitor & Alert System

PulseNotify is a backend for flight price alerts. A user sets a target price for a route (for example DEL-BOM below ₹4500). The API saves the alert and responds immediately. In the background, Celery Beat wakes up every 60 seconds, checks the current price for every route that has active alerts, and fires an asynchronous notification task when a target is hit.

## How it works

```
POST /api/alerts/        ->  PriceAlert saved to PostgreSQL (instant response)
        |
Celery Beat fires check_prices every 60 seconds
        |
check_prices groups active alerts by route and calls
GET /api/flights/price/?route=DEL-BOM   (internal mock price feed, via requests)
        |
price <= threshold ?  ->  send_notification.delay(alert_id, price)
        |
send_notification (Celery worker) writes a NotificationLog row
and marks the alert as "triggered"
        |
GET /api/admin/summary/  ->  admin sees platform-wide stats
```

## Tech stack

Django, Django REST Framework, SimpleJWT (authentication), Celery + Celery Beat, Redis (broker), PostgreSQL, `requests`, Docker Compose, python-dotenv.

## Project structure

```
pulsenotify-project/
├── docker-compose.yml                   # PostgreSQL + Redis
├── manage.py
├── requirements.txt                     # pinned dependencies
├── .env.example                         # required environment variables
├── PulseNotify.postman_collection.json  # all 13 scenarios
├── pulsenotify/
│   ├── __init__.py                      # exposes the Celery app
│   ├── celery.py                        # Celery app + task autodiscovery
│   ├── urls.py
│   └── settings/
│       ├── base.py                      # shared config: apps, JWT, Celery, Beat schedule
│       ├── local.py                     # DEBUG=True, local database
│       └── production.py                # DEBUG=False, production database
└── pulse/
    ├── models.py                        # UserProfile, PriceAlert, NotificationLog
    ├── signals.py                       # post_save on User -> creates UserProfile
    ├── apps.py                          # connects the signal in ready()
    ├── serializers.py
    ├── views.py                         # all 7 endpoints
    ├── permissions.py                   # IsAdminUser (checks profile.role)
    ├── tasks.py                         # check_prices, send_notification
    ├── tests.py
    └── migrations/
```

## Setup

### Prerequisites

Python 3.10+, Docker Desktop, and Git.

### 1. Clone and enter the project

```
git clone <your-repo-url>
cd pulsenotify-project
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in real values. The real `.env` is git-ignored and must never be committed.

| Variable | Purpose | Example |
|---|---|---|
| `DB_NAME` | PostgreSQL database name | `pulsenotify_db` |
| `DB_USER` | PostgreSQL user | `pulsenotify_user` |
| `DB_PASSWORD` | PostgreSQL password | `pulsenotify_pass` |
| `DB_HOST` | Database host | `localhost` |
| `DB_PORT` | Database port | `5432` |
| `SECRET_KEY` | Django secret key | any long random string |
| `DJANGO_SETTINGS_MODULE` | Which settings file to use | `pulsenotify.settings.local` |

Set `DJANGO_SETTINGS_MODULE` to `pulsenotify.settings.production` when deploying.

### 3. Start PostgreSQL and Redis

```
docker compose up -d
docker ps
```

Both `pulsenotify_postgres` and `pulsenotify_redis` should show as `Up`.

### 4. Create a virtual environment and install dependencies

```
python -m venv venv
.\venv\Scripts\Activate.ps1        # Windows PowerShell
source venv/bin/activate           # macOS / Linux
pip install -r requirements.txt
```

### 5. Apply migrations

```
python manage.py migrate
```

## Running the project

PulseNotify needs **three processes running at the same time**. Open three terminals, activate the virtual environment in each, and run one command per terminal.

| Terminal | Command | What to watch |
|---|---|---|
| 1 - API server | `python manage.py runserver` | Requests, including the internal call to `/api/flights/price/` |
| 2 - Celery worker | `celery -A pulsenotify worker --loglevel=info --pool=solo` | `send_notification` tasks arriving and succeeding |
| 3 - Celery beat | `celery -A pulsenotify beat --loglevel=info` | `check_prices` being sent every 60 seconds |

On Windows the `--pool=solo` flag is required because Celery's default worker pool is not reliable there. On macOS or Linux it can be omitted.

### Seeing it work end to end

1. Register and log in (see the endpoints below).
2. Create an alert for `DEL-BOM` with `threshold_price` of `9000`. The mock price for this route is always between 3000 and 7000, so it will always trigger.
3. Within 60 seconds, Terminal 3 sends `check_prices`, Terminal 1 logs the price feed request, and Terminal 2 runs `send_notification`.
4. Check the database:

```sql
SELECT id, alert_id, triggered_price, message, notified_at FROM pulse_notificationlog;
SELECT id, origin, destination, threshold_price, status FROM pulse_pricealert;
```

You should see a new notification row, and the alert's status changed to `triggered`.

## API endpoints

| # | Method | Endpoint | Auth | Description |
|---|---|---|---|---|
| 1 | POST | `/api/auth/register/` | Public | Create a user. A `UserProfile` is created automatically by a `post_save` signal. Returns a JWT access token. |
| 2 | POST | `/api/auth/login/` | Public | Validate credentials with `authenticate()` and return a fresh JWT access token. |
| 3 | POST | `/api/alerts/` | JWT | Create a price alert for the logged-in user. The user is taken from the token, never from the request body. |
| 4 | GET | `/api/alerts/` | JWT | List the logged-in user's own alerts only. Returns an empty list, not a 404, when there are none. |
| 5 | DELETE | `/api/alerts/<id>/` | JWT | Deactivate an alert (status becomes `inactive`). The row is not deleted. Returns 404 if the alert does not exist or belongs to another user. |
| 6 | GET | `/api/flights/price/?route=DEL-BOM` | Public | Internal mock price feed used by the Celery task. Returns a random price in the route's range, or 404 for an unknown route. |
| 7 | GET | `/api/admin/summary/` | JWT, admin only | Platform-wide statistics. Returns 403 for regular users. |

Supported mock routes: `DEL-BOM`, `BLR-HYD`, `DEL-BLR`, `BOM-GOA`.

### Sample requests and responses

**Register** - `POST /api/auth/register/`

```json
{ "username": "alice", "password": "securepass", "email": "alice@example.com" }
```
Response `201`:
```json
{ "username": "alice", "access": "eyJ...", "role": "user" }
```
A duplicate username returns `400`. A `role` field in the request body is ignored; new users are always `user`.

**Login** - `POST /api/auth/login/` returns `200` with `{ "access": "eyJ...", "role": "user" }`, or `401` for invalid credentials.

**Create an alert** - `POST /api/alerts/` with header `Authorization: Bearer <access token>`

```json
{ "origin": "DEL", "destination": "BOM", "threshold_price": 4500 }
```
Response `201`:
```json
{ "id": 1, "origin": "DEL", "destination": "BOM", "threshold_price": "4500.00", "status": "active", "created_at": "..." }
```

**Deactivate an alert** - `DELETE /api/alerts/1/` returns `200` with `{ "status": "inactive" }`.

**Mock price feed** - `GET /api/flights/price/?route=DEL-BOM` returns `{ "route": "DEL-BOM", "price": 4200 }`.

**Admin summary** - `GET /api/admin/summary/` returns `200`:
```json
{
  "total_alerts": 24,
  "active_alerts": 18,
  "triggered_alerts": 4,
  "total_notifications": 11,
  "top_routes": [
    { "route": "DEL-BOM", "alert_count": 8 },
    { "route": "BLR-HYD", "alert_count": 6 }
  ]
}
```

### Creating an admin user

Every new user starts with role `user`. To make an admin, register a user normally and promote it from the Django shell:

```
python manage.py shell
```
```python
from pulse.models import UserProfile
p = UserProfile.objects.get(user__username='adminuser')
p.role = 'admin'
p.save()
```
The permission class reads the role from the database on every request, so the promotion takes effect immediately with the existing token.

## Background jobs

- **`check_prices`** (scheduled by Celery Beat every 60 seconds, configured in `CELERY_BEAT_SCHEDULE` in `settings/base.py`): collects the distinct routes that have active alerts, calls the internal price feed once per route with `requests.get()`, and calls `send_notification.delay()` for every alert whose threshold is met (price less than or equal to the threshold).
- **`send_notification`** (runs asynchronously in the Celery worker): creates a `NotificationLog` row and marks the alert `triggered` so it does not fire again.

## Tests

```
python manage.py test
```

The suite covers the threshold comparison, `NotificationLog` creation, and alert scoping between users, plus tests for the Celery tasks and API behaviour (alert ownership, admin permission, and role handling on registration).

## Postman collection

Import `PulseNotify.postman_collection.json`. It contains all 13 required scenarios, plus two clearly named helper requests, and each request has test scripts that assert the expected status code.

- Collection variables: `base_url` (preset to `http://127.0.0.1:8000`), `user_token`, `admin_token`, `alert_id`. The tokens and `alert_id` are filled in automatically by the test scripts.
- Run the requests in order, with the server, worker and beat all running.
- Scenario 1 returns `201` only on a fresh database. Re-running it returns `400`, because the user already exists.
- Scenario 12 needs `adminuser` to have been promoted to admin once (see "Creating an admin user").
- Scenario 13 is a database check. After the alert from scenario 6 has been processed by Celery, confirm a row exists in `pulse_notificationlog` using the SQL in the "Seeing it work end to end" section.

## Design decisions

**1. Notifications are sent with `.delay()`, not called directly.** `check_prices` runs on a schedule and loops over every active route. If it waited for each notification to be written, one slow task would delay the whole scan. `.delay()` puts the work on the queue and returns immediately, so the scheduler stays fast and the notification work is spread across the worker.

**2. One price lookup per route, not per alert.** `check_prices` gets the distinct `(origin, destination)` pairs first and fetches each route's price once, then compares it against all alerts for that route. With many users watching DEL-BOM, that is one internal HTTP call instead of one per alert.

**3. Alerts are deactivated, never deleted.** `DELETE /api/alerts/<id>/` sets the status to `inactive`. The row, and any `NotificationLog` entries attached to it, are preserved for the admin statistics, while the Beat job stops checking it because it only reads `active` alerts. Triggered alerts are marked `triggered` for the same reason: they must not fire a second notification.

**4. Another user's alert looks exactly like a missing alert.** Both cases return `404` with the same message, so a user cannot discover whether a given alert ID exists in someone else's account.

**5. Roles are server-controlled.** The `UserProfile` is created by a `post_save` signal with the default role `user`, and the register endpoint never reads a role from the request. The admin check lives in a custom `IsAdminUser` permission that reads `request.user.profile.role` rather than Django's `is_staff`, which is a separate concept for the Django admin site.

**6. The price feed is unauthenticated.** The mock price endpoint is called by the Celery task over HTTP and needs no token. It overrides the global JWT requirement with empty authentication and permission classes.

## Known limitations

- `send_notification` only writes a `NotificationLog` row. It does not send an email or push notification.
- An alert stays `active` until the worker processes `send_notification`. If a worker is backed up for longer than 60 seconds, the next `check_prices` run could queue a second notification for the same alert. A production version would mark the alert as triggered inside `check_prices` before queuing, or use a database lock.
- The price feed URL in `tasks.py` is `http://localhost:8000`. It should be moved to an environment variable before deploying anywhere other than a local machine.
- Prices come from a mock endpoint with random values, not a real flight API.
