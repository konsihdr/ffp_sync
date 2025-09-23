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


def create_post_with_media_http(post_data, media_data, filename, media_type='image'):
    """Create post with media (image or video) using direct HTTP request (workaround for SDK issue)"""
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

        # Check file size
        media_data.seek(0, 2)  # Seek to end
        file_size = media_data.tell()
        media_data.seek(0)  # Reset to beginning

        # File size limits (configurable)
        MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
        MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

        if media_type == 'video' and file_size > MAX_VIDEO_SIZE:
            raise Exception(f"Video file too large: {file_size} bytes (max: {MAX_VIDEO_SIZE} bytes)")
        elif media_type == 'image' and file_size > MAX_IMAGE_SIZE:
            raise Exception(f"Image file too large: {file_size} bytes (max: {MAX_IMAGE_SIZE} bytes)")

        print(f"INFO: Uploading {media_type} file: {filename} ({file_size} bytes)")

        # Prepare files for upload
        if media_type == 'video':
            files = {'video': (filename, media_data, 'video/mp4')}
        else:
            files = {'image': (filename, media_data, 'image/jpeg')}

        # Create post with media
        print(f"INFO: Creating post with {media_type} via HTTP...")
        create_response = requests.post(
            f'{POCKETBASE_URL}/api/collections/ffp_posts/records',
            headers=headers,
            data=post_data,
            files=files,
            timeout=120  # 2 minute timeout for large files
        )

        print(f"INFO: HTTP Response Status: {create_response.status_code}")

        if create_response.status_code == 200:
            result = create_response.json()
            print(f"INFO: Post created successfully. ID: {result.get('id')}")

            # Verify that the media field was actually set
            expected_field = 'video' if media_type == 'video' else 'image'
            media_filename = result.get(expected_field, '')

            print(f"INFO: Checking {expected_field} field in response...")
            print(f"INFO: {expected_field} field value: '{media_filename}'")

            if not media_filename:
                print(f"ERROR: {expected_field} field is empty in response! Upload may have failed silently.")
                print(f"DEBUG: Full response data: {result}")
                raise Exception(f"{media_type} upload failed: {expected_field} field is empty")

            # Immediately update displayUrl with the correct PocketBase file URL
            display_url = f"{POCKETBASE_URL}/api/files/{result['collectionId']}/{result['id']}/{media_filename}"
            print(f"INFO: Generated display URL: {display_url}")

            update_data = {'displayUrl': display_url}
            update_response = requests.patch(
                f"{POCKETBASE_URL}/api/collections/ffp_posts/records/{result['id']}",
                headers=headers,
                json=update_data
            )

            if update_response.status_code == 200:
                result['displayUrl'] = display_url
                print(f"INFO: Updated displayUrl successfully: {display_url}")
            else:
                print(f"WARNING: Failed to update displayUrl: {update_response.status_code} - {update_response.text}")

            return result
        else:
            error_text = create_response.text
            print(f"ERROR: Post creation failed with status {create_response.status_code}")
            print(f"ERROR: Response body: {error_text}")
            raise Exception(f"Post creation failed: HTTP {create_response.status_code} - {error_text}")

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
                
                # Download media (image or video) from displayUrl and videoUrl
                image_data = None
                video_data = None

                # Download image if displayUrl exists
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

                # Download video if videoUrl exists
                if post.get('videoUrl'):
                    try:
                        response = requests.get(post['videoUrl'], timeout=60)  # Longer timeout for videos
                        if response.status_code == 200:
                            video_data = BytesIO(response.content)
                            print(f"INFO: Downloaded video for: {post['shortCode']}")
                        else:
                            print(f"ERROR: Failed to download video for {post['shortCode']}: HTTP {response.status_code}")
                    except Exception as e:
                        print(f"ERROR: Error downloading video for {post['shortCode']}: {str(e)}")
                
                # Prepare post data (using camelCase for PocketBase creation)
                post_data = {
                    'shortCode': post.get('shortCode', ''),
                    'alt': post.get('alt') or '',  # Handle None values
                    'caption': post.get('caption', ''),
                    'url': post.get('url', ''),
                    'displayUrl': post.get('displayUrl', '')  # Will be replaced with PocketBase URL
                }
                
                # Handle postDate as date field (convert timestamp if needed)
                timestamp = post.get('timestamp', '')
                if timestamp:
                    try:
                        # Handle ISO format like "2025-09-21T10:43:59.000Z"
                        if 'T' in timestamp and ('Z' in timestamp or '+' in timestamp):
                            from datetime import datetime
                            # Parse ISO format timestamp
                            if timestamp.endswith('Z'):
                                date_obj = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            else:
                                date_obj = datetime.fromisoformat(timestamp)
                            post_data['postDate'] = date_obj.strftime('%Y-%m-%d')
                        # If timestamp is a string like "2024-01-01", use as-is
                        elif timestamp.isdigit():
                            from datetime import datetime
                            date_obj = datetime.fromtimestamp(int(timestamp))
                            post_data['postDate'] = date_obj.strftime('%Y-%m-%d')
                        else:
                            # Assume it's already in YYYY-MM-DD format
                            post_data['postDate'] = timestamp[:10]  # Take first 10 chars
                    except Exception as e:
                        # If conversion fails, use current date
                        print(f"WARNING: Could not parse timestamp '{timestamp}': {e}")
                        from datetime import datetime
                        post_data['postDate'] = datetime.now().strftime('%Y-%m-%d')
                
                # Create post in PocketBase with media files if available
                created_post = None

                # Strategy: Try video first, fallback to image, then no media
                if video_data:
                    print(f"INFO: Attempting video upload for {post['shortCode']}")
                    filename = f"{post.get('shortCode', 'unknown')}.mp4"
                    created_post = create_post_with_media_http(post_data, video_data, filename, 'video')

                    if not created_post:
                        print(f"WARNING: Video upload failed for {post['shortCode']}, trying image fallback...")
                        # Fallback to image if video fails and image is available
                        if image_data:
                            print(f"INFO: Falling back to image upload for {post['shortCode']}")
                            filename = f"{post.get('shortCode', 'unknown')}.jpg"
                            created_post = create_post_with_media_http(post_data, image_data, filename, 'image')
                            if not created_post:
                                print(f"ERROR: Both video and image upload failed for {post['shortCode']}, creating post without media")
                        else:
                            print(f"ERROR: Video upload failed and no image available for {post['shortCode']}")
                    else:
                        print(f"INFO: Video upload successful for {post['shortCode']}")

                elif image_data:
                    print(f"INFO: Uploading image for {post['shortCode']} (no video available)")
                    filename = f"{post.get('shortCode', 'unknown')}.jpg"
                    created_post = create_post_with_media_http(post_data, image_data, filename, 'image')
                    if not created_post:
                        print(f"ERROR: Image upload failed for {post['shortCode']}")

                # Final fallback: create post without media if all uploads failed
                if not created_post:
                    print(f"WARNING: Creating post without media for {post['shortCode']}")
                    try:
                        created_post = pb.collection('ffp_posts').create(post_data)
                        print(f"INFO: Post created without media. ID: {created_post.id}")

                        # Update displayUrl for posts without media to use original URL
                        if post.get('url'):
                            pb.collection('ffp_posts').update(created_post.id, {'displayUrl': post['url']})
                            print(f"INFO: Updated displayUrl for post without media: {post['url']}")
                    except Exception as fallback_error:
                        print(f"ERROR: Failed to create post even without media for {post['shortCode']}: {fallback_error}")
                        continue

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
                video_file = post.get('video', '')
                current_display_url = post.get('displayUrl', '')

                # Determine the correct displayUrl based on whether there's a video or image file
                if video_file and video_file.strip():
                    # Generate PocketBase file URL for posts with videos
                    pocketbase_url = f"{POCKETBASE_URL}/api/files/{post['collectionId']}/{post['id']}/{video_file}"
                elif image_file and image_file.strip():
                    # Generate PocketBase file URL for posts with images
                    pocketbase_url = f"{POCKETBASE_URL}/api/files/{post['collectionId']}/{post['id']}/{image_file}"
                else:
                    # For posts without media, use the original URL from the post data
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
                        if video_file and video_file.strip():
                            print(f"INFO: Updated displayUrl for {short_code} (video): {pocketbase_url}")
                        elif image_file and image_file.strip():
                            print(f"INFO: Updated displayUrl for {short_code} (image): {pocketbase_url}")
                        else:
                            print(f"INFO: Updated displayUrl for {short_code} (no media): {pocketbase_url}")
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