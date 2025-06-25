# PocketBase Setup Instructions

## 1. PocketBase Collections Setup

### Events Collection
Create a collection named `ffp_events` with the following fields:

| Field Name | Type | Required | Description |
|------------|------|----------|-------------|
| `summary` | Text | Yes | Event title/summary |
| `start` | Text | Yes | Event start date/time (ISO format) |
| `end` | Text | Yes | Event end date/time (ISO format) |
| `is_youth_event` | Bool | No | Flag for youth training events |

**Collection Settings:**
- List Rule: `@request.auth.id != null || @collection.ffp_events.id != ""`
- View Rule: `@request.auth.id != null || @collection.ffp_events.id != ""`
- Create Rule: `@request.auth.id != null`
- Update Rule: `@request.auth.id != null`
- Delete Rule: `@request.auth.id != null`

### Posts Collection
Create a collection named `ffp_posts` with the following fields:

| Field Name | Type | Required | Description |
|------------|------|----------|-------------|
| `alt` | Text | No | Alt text for image |
| `caption` | Text | No | Post caption |
| `url` | Text | No | Original post URL |
| `displayUrl` | Text | No | Display image URL |

**Collection Settings:**
- List Rule: `@request.auth.id != null || @collection.ffp_posts.id != ""`
- View Rule: `@request.auth.id != null || @collection.ffp_posts.id != ""`
- Create Rule: `@request.auth.id != null`
- Update Rule: `@request.auth.id != null`
- Delete Rule: `@request.auth.id != null`

## 2. User Setup

### Option A: Admin User (Recommended for sync script)
1. Access PocketBase admin panel at `https://base.hdr-it.de/_/`
2. Create an admin account if not already created
3. Use admin credentials in your sync script

### Option B: Regular User
1. Create a new user in the `users` collection
2. Set appropriate permissions for the sync operations
3. Use these credentials in your sync script

## 3. Authentication Configuration

### Environment Variables
Add these environment variables to your system:

```bash
export POCKETBASE_EMAIL="your-admin@email.com"
export POCKETBASE_PASSWORD="your-password"
```

### Update sync_script.py
Uncomment and modify the authentication line in `sync_script.py`:

```python
# In the main() function, replace:
# pb.auth_with_password('your_email', 'your_password')

# With:
pb.auth_with_password(os.environ['POCKETBASE_EMAIL'], os.environ['POCKETBASE_PASSWORD'])
```

## 4. API Access for Other Applications

Once data is synced, other applications can access:

### Events API Endpoints:
- **All events**: `GET https://base.hdr-it.de/api/collections/events/records`
- **Single event**: `GET https://base.hdr-it.de/api/collections/events/records/{id}`
- **Filter youth events**: `GET https://base.hdr-it.de/api/collections/events/records?filter=(is_youth_event=true)`
- **Upcoming events**: `GET https://base.hdr-it.de/api/collections/events/records?filter=(start>='2024-01-01')&sort=start`

### Posts API Endpoints:
- **All posts**: `GET https://base.hdr-it.de/api/collections/posts/records`
- **Latest posts**: `GET https://base.hdr-it.de/api/collections/posts/records?sort=-timestamp&perPage=12`
- **Single post**: `GET https://base.hdr-it.de/api/collections/posts/records/{id}`

## 5. Scheduling the Sync Script

### Using Cron (Linux/macOS):
```bash
# Edit crontab
crontab -e

# Add daily sync at 6 AM
0 6 * * * cd /path/to/ffp_api && python3 sync_script.py
```

### Using Task Scheduler (Windows):
1. Open Task Scheduler
2. Create Basic Task
3. Set trigger to "Daily" at desired time
4. Set action to start `python3 sync_script.py` in the project directory

## 6. Testing the Setup

1. Run the sync script manually:
   ```bash
   python3 sync_script.py
   ```

2. Check PocketBase admin panel to verify data was synced

3. Test API endpoints in browser or with curl:
   ```bash
   curl "https://base.hdr-it.de/api/collections/events/records"
   curl "https://base.hdr-it.de/api/collections/posts/records"
   ```

4. Get only latest entry after today
   ```bash
   curl "https://base.hdr-it.de/api/collections/events/records?filter=(start>=@now)&sort=start&perPage=1"
   ```

## 7. Migration Notes

- MongoDB connection is kept only for initial data migration
- After successful migration, MongoDB dependency can be removed
- The sync script will overwrite all data daily to ensure freshness
- Consider backing up PocketBase data before major changes