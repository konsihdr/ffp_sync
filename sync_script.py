from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from icalendar import Calendar
import requests
from pocketbase import PocketBase
import os

# Load environment variables from .env file
load_dotenv()

# Import posts sync function from separate script
from sync_posts_apify import main as sync_posts_from_apify

# URL des öffentlichen Google Kalenders im iCal-Format (ICS)
CALENDAR_URL="https://calendar.google.com/calendar/ical/74ba620d6f97d3d076e54247195ee2b2c927e257967c3d71c735e40d95dd8359%40group.calendar.google.com/private-c7ea8ddcff03ae10cb2593e1820e4d55/basic.ics"

# PocketBase setup
POCKETBASE_URL = "https://base.hdr-it.de"
pb = PocketBase(POCKETBASE_URL)

# Funktion zum Abrufen und Verarbeiten der Ereignisse im ICS-Format
def get_calendar_events():
    response = requests.get(CALENDAR_URL)
    if response.status_code == 200:
        ics_content = response.content
        calendar = Calendar.from_ical(ics_content)

        events = []
        for event in calendar.walk('vevent'):
            event_data = {
                'summary': event.get('summary').to_ical().decode('utf-8'),
                'start': event.get('dtstart').dt.isoformat(),
                'end': event.get('dtend').dt.isoformat()
            }
            events.append(event_data)

        return events
    else:
        return None

def sync_events_to_pocketbase():
    """Sync calendar events to PocketBase"""
    events = get_calendar_events()
    if events is None:
        print("ERROR: Failed to fetch calendar events")
        return False

    try:
        # Authenticate with PocketBase user
        pb.collection('users').auth_with_password(os.environ['POCKETBASE_EMAIL'], os.environ['POCKETBASE_PASSWORD'])
        
        # Fetch existing events from PocketBase
        existing_events = pb.collection('ffp_events').get_full_list()
        existing_events_dict = {
            (e.summary, e.start, e.end): e for e in existing_events
        }
        # Also index by summary for update checks
        existing_by_summary = {e.summary: e for e in existing_events}

        updated = 0
        created = 0
        for event in events:
            summary = event['summary']
            start = event['start']
            end = event['end']
            is_youth_event = 'Jugenduebung' in summary

            # Check if event with same summary exists
            existing = existing_by_summary.get(summary)
            if existing:
                # Check if start or end has changed
                if existing.start != start or existing.end != end:
                    # Update event
                    pb.collection('ffp_events').update(existing.id, {
                        'start': start,
                        'end': end,
                        'is_youth_event': is_youth_event
                    })
                    updated += 1
                # else: no change needed
            else:
                # Create new event
                pb.collection('ffp_events').create({
                    'summary': summary,
                    'start': start,
                    'end': end,
                    'is_youth_event': is_youth_event
                })
                created += 1

        print(f"INFO: Successfully synced events to PocketBase: {created} created, {updated} updated")
        return True
    except Exception as e:
        print(f"ERROR: Error syncing events to PocketBase: {e}")
    return False

def main():
    """Main sync function - runs both calendar and posts sync"""
    print(f"INFO: Starting complete data sync to PocketBase at {datetime.now()}")
    print("INFO: " + "=" * 60)
    
    # Authenticate with PocketBase if needed
    # pb.collection('users').auth_with_password(os.environ['POCKETBASE_EMAIL'], os.environ['POCKETBASE_PASSWORD'])
    
    # Sync calendar events
    print("INFO: 1. Syncing calendar events...")
    events_success = sync_events_to_pocketbase()
    
    # Sync posts from Apify
    print("INFO: 2. Syncing posts from Apify...")
    try:
        sync_posts_from_apify()
        posts_success = True
    except Exception as e:
        print(f"ERROR: Error running posts sync: {e}")
        posts_success = False
    
    # Summary
    print("INFO: " + "=" * 60)
    print("INFO: SYNC SUMMARY:")
    print(f"INFO: Calendar Events: {'✓ SUCCESS' if events_success else '✗ FAILED'}")
    print(f"INFO: Instagram Posts: {'✓ SUCCESS' if posts_success else '✗ FAILED'}")
    
    if events_success and posts_success:
        print("INFO: 🎉 All data synced successfully!")
    elif events_success or posts_success:
        print("WARNING: ⚠️  Partial sync completed. Check logs above for errors.")
    else:
        print("ERROR: ❌ All sync operations failed. Check logs above for errors.")
    
    print(f"INFO: Complete sync finished at {datetime.now()}")
    print("INFO: " + "=" * 60)

if __name__ == '__main__':
    main()
