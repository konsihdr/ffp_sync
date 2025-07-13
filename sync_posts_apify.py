import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from pocketbase import PocketBase
from io import BytesIO

# Load environment variables from .env file
load_dotenv()

# PocketBase setup
POCKETBASE_URL = "https://base.hdr-it.de"
pb = PocketBase(POCKETBASE_URL)

def log_message(level, message):
    """Log messages with timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}")

def create_post_with_image_http(post_data, image_data, filename):
    """Create post with image using direct HTTP request (workaround for SDK issue)"""
    try:
        # Get auth token from current PocketBase session
        auth_response = requests.post(f'{POCKETBASE_URL}/api/collections/users/auth-with-password', json={
            'identity': os.environ['POCKETBASE_EMAIL'],
            'password': os.environ['POCKETBASE_PASSWORD']
        })
        
        if auth_response.status_code != 200:
            raise Exception(f"Authentication failed: {auth_response.text}")
        
        token = auth_response.json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        
        # Prepare files for upload
        image_data.seek(0)
        files = {'image': (filename, image_data, 'image/jpeg')}
        
        # Create post with image
        create_response = requests.post(
            f'{POCKETBASE_URL}/api/collections/ffp_posts/records',
            headers=headers,
            data=post_data,
            files=files
        )
        
        if create_response.status_code == 200:
            result = create_response.json()
            log_message("INFO", f"Post created with ID: {result['id']}, image: {result.get('image', 'MISSING')}")
            return result
        else:
            raise Exception(f"Post creation failed: {create_response.text}")
            
    except Exception as e:
        log_message("ERROR", f"HTTP post creation failed: {e}")
        return None

def fetch_data():
    """Fetch data from Apify Instagram scraper"""
    url = f"https://api.apify.com/v2/actor-tasks/konsihdr~instagram-scraper-task/run-sync-get-dataset-items?token={os.environ['APIFY_TOKEN']}"

    response = requests.get(url)
    data = response.json()

    if isinstance(data, list) and len(data) > 0 and "error" in data[0]:
        if data[0]["error"] == "no_items":
            log_message("INFO", "Keine neuen Daten verfügbar.")
        else:
            log_message("ERROR", f"Fehler: {data[0]['error']} - {data[0].get('errorDescription', 'Keine Beschreibung')}")
        exit(0)
    else:
        return data

def save_to_pocketbase(data):
    """Save posts to PocketBase with image file storage"""
    try:
        # Authenticate with PocketBase user
        pb.collection('users').auth_with_password(os.environ['POCKETBASE_EMAIL'], os.environ['POCKETBASE_PASSWORD'])
        log_message("INFO", "Authenticated with PocketBase")
        
        for post in data:
            try:
                # Check if post already exists - simpler approach
                current_shortcode = post.get('shortCode')
                try:
                    # Get all posts and check manually (more reliable)
                    all_posts = pb.collection('ffp_posts').get_full_list()
                    
                    duplicate_found = False
                    
                    for existing_post in all_posts:
                        # Access shortCode using snake_case (PocketBase field name)
                        existing_shortcode = getattr(existing_post, 'short_code', None)
                        
                        if existing_shortcode == current_shortcode:
                            duplicate_found = True
                            log_message("INFO", f"Found existing post with shortCode: {current_shortcode}")
                            break
                    
                    if duplicate_found:
                        log_message("WARNING", f"Duplicate post skipped: {current_shortcode}")
                        continue
                    else:
                        log_message("INFO", f"New post found: {current_shortcode}")
                        
                except Exception as check_error:
                    log_message("WARNING", f"Could not check for duplicates, proceeding anyway: {check_error}")
                    log_message("INFO", f"Processing post: {current_shortcode}")
                
                # Download image from displayUrl
                image_data = None
                if post.get('displayUrl'):
                    try:
                        response = requests.get(post['displayUrl'], timeout=30)
                        if response.status_code == 200:
                            image_data = BytesIO(response.content)
                            log_message("INFO", f"Downloaded image for: {post['shortCode']}")
                        else:
                            log_message("ERROR", f"Failed to download image for {post['shortCode']}: HTTP {response.status_code}")
                    except Exception as e:
                        log_message("ERROR", f"Error downloading image for {post['shortCode']}: {str(e)}")
                
                # Prepare post data (using camelCase for PocketBase creation)
                post_data = {
                    'shortCode': post.get('shortCode', ''),
                    'alt': post.get('alt', ''),
                    'caption': post.get('caption', ''),
                    'url': post.get('url', ''),
                    'displayUrl': post.get('displayUrl', '')  # Will be replaced with PocketBase URL
                }
                
                # Handle postDate as date field (convert timestamp if needed)
                timestamp = post.get('timestamp', '')
                if timestamp:
                    try:
                        # If timestamp is a string like "2024-01-01", use as-is
                        # If it's a Unix timestamp, convert it
                        if timestamp.isdigit():
                            from datetime import datetime
                            date_obj = datetime.fromtimestamp(int(timestamp))
                            post_data['postDate'] = date_obj.strftime('%Y-%m-%d')
                        else:
                            # Assume it's already in YYYY-MM-DD format
                            post_data['postDate'] = timestamp[:10]  # Take first 10 chars
                    except:
                        # If conversion fails, use current date
                        from datetime import datetime
                        post_data['postDate'] = datetime.now().strftime('%Y-%m-%d')
                
                # Create post in PocketBase with image file if available
                if image_data:
                    log_message("INFO", f"Uploading image for {post['shortCode']}, size: {len(image_data.getvalue())} bytes")
                    filename = f"{post.get('shortCode', 'unknown')}.jpg"
                    created_post = create_post_with_image_http(post_data, image_data, filename)
                    if not created_post:
                        log_message("ERROR", f"Failed to create post with image for {post['shortCode']}")
                        continue
                else:
                    log_message("WARNING", f"No image data for {post['shortCode']}")
                    created_post = pb.collection('ffp_posts').create(post_data)
                    log_message("INFO", f"Post created with ID: {created_post.id}")
                log_message("INFO", f"Saved post: {post['shortCode']}")
                
            except Exception as e:
                log_message("ERROR", f"Error saving post {post.get('shortCode', 'unknown')}: {str(e)}")
                continue
                
    except Exception as e:
        log_message("ERROR", f"PocketBase authentication or general error: {str(e)}")

def update_display_urls():
    """Second job: Update all posts with PocketBase file URLs using HTTP"""
    try:
        # Get auth token
        auth_response = requests.post(f'{POCKETBASE_URL}/api/collections/users/auth-with-password', json={
            'identity': os.environ['POCKETBASE_EMAIL'],
            'password': os.environ['POCKETBASE_PASSWORD']
        })
        
        if auth_response.status_code != 200:
            raise Exception(f"Authentication failed: {auth_response.text}")
        
        token = auth_response.json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        log_message("INFO", "Authenticated with PocketBase for URL updates")
        
        # Get all posts using HTTP
        list_response = requests.get(f'{POCKETBASE_URL}/api/collections/ffp_posts/records', headers=headers)
        if list_response.status_code != 200:
            raise Exception(f"Failed to fetch posts: {list_response.text}")
        
        posts = list_response.json()['items']
        updated_count = 0
        
        for post in posts:
            try:
                short_code = post.get('shortCode', 'unknown')
                image_file = post.get('image', '')
                current_display_url = post.get('displayUrl', '')
                
                # Only process posts that have an image file uploaded and don't already have a PocketBase URL
                if image_file and image_file.strip():
                    # Generate PocketBase file URL
                    pocketbase_url = f"{POCKETBASE_URL}/api/files/{post['collectionId']}/{post['id']}/{image_file}"
                    
                    # Only update if displayUrl is not already a PocketBase URL
                    if not current_display_url.startswith(POCKETBASE_URL):
                        # Update the displayUrl field
                        update_data = {'displayUrl': pocketbase_url}
                        update_response = requests.patch(
                            f"{POCKETBASE_URL}/api/collections/ffp_posts/records/{post['id']}",
                            headers=headers,
                            json=update_data
                        )
                        
                        if update_response.status_code == 200:
                            log_message("INFO", f"Updated displayUrl for {short_code}: {pocketbase_url}")
                            updated_count += 1
                        else:
                            log_message("ERROR", f"Failed to update {short_code}: {update_response.text}")
                    else:
                        log_message("INFO", f"DisplayUrl already updated for {short_code}")
                else:
                    log_message("WARNING", f"No image file for post: {short_code}")
            except Exception as update_error:
                log_message("ERROR", f"Error updating URL for {short_code}: {update_error}")
                continue
        
        log_message("INFO", f"Updated {updated_count} post URLs")
        return True
        
    except Exception as e:
        log_message("ERROR", f"Error updating display URLs: {str(e)}")
        return False

def main():
    log_message("INFO", "Starting Instagram posts sync...")
    
    # Step 1: Fetch and save posts with images
    log_message("INFO", "Fetching data from Instagram...")
    data = fetch_data()
    if data:
        log_message("INFO", "Data fetched successfully.")
        save_to_pocketbase(data)
        log_message("INFO", "Posts saved to PocketBase.")
        
        # Step 2: Update displayUrls with PocketBase file URLs
        log_message("INFO", "Updating displayUrls with PocketBase file URLs...")
        url_success = update_display_urls()
        
        if url_success:
            log_message("INFO", "Complete posts sync finished successfully.")
        else:
            log_message("WARNING", "Posts saved but URL updates failed.")
    else:
        log_message("INFO", "No data to save.")

if __name__ == "__main__":
    main()