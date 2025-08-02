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
            image_filename = result.get('image', '')
                        
            # Immediately update displayUrl with the correct PocketBase file URL
            if image_filename:
                display_url = f"{POCKETBASE_URL}/api/files/{result['collectionId']}/{result['id']}/{image_filename}"
                update_data = {'displayUrl': display_url}
                update_response = requests.patch(
                    f"{POCKETBASE_URL}/api/collections/ffp_posts/records/{result['id']}",
                    headers=headers,
                    json=update_data
                )
                
                if update_response.status_code == 200:
                    result['displayUrl'] = display_url
                    print(f"INFO: Updated displayUrl immediately: {display_url}")
                else:
                    print(f"WARNING: Failed to update displayUrl immediately: {update_response.text}")
            
            return result
        else:
            raise Exception(f"Post creation failed: {create_response.text}")
            
    except Exception as e:
        print(f"ERROR: HTTP post creation failed: {e}")
        return None

def fetch_data():
    """Fetch data from Apify Instagram scraper"""
    url = f"https://api.apify.com/v2/actor-tasks/konsihdr~instagram-scraper-task/run-sync-get-dataset-items?token={os.environ['APIFY_TOKEN']}"

    response = requests.get(url)
    data = response.json()

    if isinstance(data, list) and len(data) > 0 and "error" in data[0]:
        if data[0]["error"] == "no_items":
            print("INFO: Keine neuen Daten verfügbar.")
        else:
            print(f"ERROR: Fehler: {data[0]['error']} - {data[0].get('errorDescription', 'Keine Beschreibung')}")
        exit(0)
    else:
        return data

def save_to_pocketbase(data):
    """Save posts to PocketBase with image file storage"""
    try:
        # Authenticate with PocketBase user
        pb.collection('users').auth_with_password(os.environ['POCKETBASE_EMAIL'], os.environ['POCKETBASE_PASSWORD'])
        print("INFO: Authenticated with PocketBase")
        
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
                            print(f"INFO: Found existing post with shortCode: {current_shortcode}")
                            break
                    
                    if duplicate_found:
                        print(f"WARNING: Duplicate post skipped: {current_shortcode}")
                        continue
                    else:
                        print(f"INFO: New post found: {current_shortcode}")
                        
                except Exception as check_error:
                    print(f"WARNING: Could not check for duplicates, proceeding anyway: {check_error}")
                    print(f"INFO: Processing post: {current_shortcode}")
                
                # Download image from displayUrl
                image_data = None
                if post.get('displayUrl'):
                    try:
                        response = requests.get(post['displayUrl'], timeout=30)
                        if response.status_code == 200:
                            image_data = BytesIO(response.content)
                            print(f"INFO: Downloaded image for: {post['shortCode']}")
                        else:
                            print(f"ERROR: Failed to download image for {post['shortCode']}: HTTP {response.status_code}")
                    except Exception as e:
                        print(f"ERROR: Error downloading image for {post['shortCode']}: {str(e)}")
                
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
                    print(f"INFO: Uploading image for {post['shortCode']}, size: {len(image_data.getvalue())} bytes")
                    filename = f"{post.get('shortCode', 'unknown')}.jpg"
                    created_post = create_post_with_image_http(post_data, image_data, filename)
                    if not created_post:
                        print(f"ERROR: Failed to create post with image for {post['shortCode']}")
                        continue
                else:
                    print(f"WARNING: No image data for {post['shortCode']}")
                    created_post = pb.collection('ffp_posts').create(post_data)
                    print(f"INFO: Post created with ID: {created_post.id}")
                    
                    # Update displayUrl for posts without images to use original URL
                    if post.get('url'):
                        pb.collection('ffp_posts').update(created_post.id, {'displayUrl': post['url']})
                        print(f"INFO: Updated displayUrl for post without image: {post['url']}")
                print(f"INFO: Saved post: {post['shortCode']}")
                
            except Exception as e:
                print(f"ERROR: Error saving post {post.get('shortCode', 'unknown')}: {str(e)}")
                continue
                
    except Exception as e:
        print(f"ERROR: PocketBase authentication or general error: {str(e)}")

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
        print("INFO: Authenticated with PocketBase for URL updates")
        
        # Get all posts using HTTP - fetch ALL records with pagination
        list_response = requests.get(f'{POCKETBASE_URL}/api/collections/ffp_posts/records?perPage=500', headers=headers)
        
        if list_response.status_code != 200:
            raise Exception(f"Failed to fetch posts: {list_response.text}")
        
        response_data = list_response.json()
        posts = response_data['items']
        total_items = response_data.get('totalItems', len(posts))
        
        # If there are more posts, fetch all pages
        if total_items > len(posts):
            page = 2
            while len(posts) < total_items:
                page_response = requests.get(f'{POCKETBASE_URL}/api/collections/ffp_posts/records?perPage=500&page={page}', headers=headers)
                if page_response.status_code == 200:
                    page_data = page_response.json()
                    posts.extend(page_data['items'])
                    page += 1
                else:
                    print(f"WARNING: Failed to fetch page {page}: {page_response.text}")
                    break
        
        updated_count = 0
        
        for post in posts:
            try:
                short_code = post.get('shortCode', 'unknown')
                image_file = post.get('image', '')
                current_display_url = post.get('displayUrl', '')
                
                # Determine the correct displayUrl based on whether there's an image file
                if image_file and image_file.strip():
                    # Generate PocketBase file URL for posts with images
                    pocketbase_url = f"{POCKETBASE_URL}/api/files/{post['collectionId']}/{post['id']}/{image_file}"
                else:
                    # For posts without images, use the original URL from the post data
                    pocketbase_url = post.get('url', '')
                    
                # Only update if displayUrl is not already correct
                if current_display_url != pocketbase_url:
                    # Update the displayUrl field
                    update_data = {'displayUrl': pocketbase_url}
                    update_response = requests.patch(
                        f"{POCKETBASE_URL}/api/collections/ffp_posts/records/{post['id']}",
                        headers=headers,
                        json=update_data
                    )
                    
                    if update_response.status_code == 200:
                        if image_file and image_file.strip():
                            print(f"INFO: Updated displayUrl for {short_code}: {pocketbase_url}")
                        else:
                            print(f"INFO: Updated displayUrl for {short_code} (no image): {pocketbase_url}")
                        updated_count += 1
                    else:
                        print(f"ERROR: Failed to update {short_code}: {update_response.text}")
                else:
                    print(f"INFO: DisplayUrl already correct for {short_code}")
            except Exception as update_error:
                print(f"ERROR: Error updating URL for {short_code}: {update_error}")
                continue
        
        print(f"INFO: Updated {updated_count} post URLs")
        return True
        
    except Exception as e:
        print(f"ERROR: Error updating display URLs: {str(e)}")
        return False

def main():
    print("INFO: Starting Instagram posts sync...")
    
    # Step 1: Fetch and save posts with images
    print("INFO: Fetching data from Instagram...")
    data = fetch_data()
    if data:
        print("INFO: Data fetched successfully.")
        save_to_pocketbase(data)
        print("INFO: Posts saved to PocketBase.")
        
        # Step 2: Wait briefly for S3 uploads to complete, then update any remaining displayUrls
        print("INFO: Waiting 10 seconds for S3 uploads to complete...")
        import time
        time.sleep(10)
        
        print("INFO: Updating any remaining displayUrls with PocketBase file URLs...")
        url_success = update_display_urls()
        
        if url_success:
            print("INFO: Complete posts sync finished successfully.")
        else:
            print("WARNING: Posts saved but URL updates failed.")
    else:
        print("INFO: No data to save.")

if __name__ == "__main__":
    main()