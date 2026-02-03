import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import quote

class ThreeAsqProvider:
    def __init__(self):
        self.api = "https://3asq.org"
        # Using the exact User-Agent from index.ts
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.api + "/",
            "X-Requested-With": "XMLHttpRequest"
        }

    def _get_soup(self, html):
        return BeautifulSoup(html, 'html.parser')

    def search(self, query):
        """
        Searches for manga based on query.
        Replicates the search logic from index.ts.
        """
        print(f"Searching for: {query}...")
        url = f"{self.api}/?s={quote(query)}&post_type=wp-manga"
        
        try:
            resp = requests.get(url, headers=self.headers)
            soup = self._get_soup(resp.text)
            
            results = []
            seen_slugs = set()

            # Selectors from index.ts
            containers = soup.select(".c-tabs-item__content, .tab-content-wrap, .c-tabs-item, .row.c-tabs-item__content")
            
            for el in containers:
                # Find title anchor
                title_el = el.select_one(".post-title h3 a, .post-title h4 a, .post-title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get('href')
                
                # Extract slug
                slug_match = re.search(r'/manga/([^/]+)/', href)
                if not slug_match:
                    continue
                slug = slug_match.group(1)

                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                results.append({
                    'title': title,
                    'slug': slug,
                    'url': href
                })
                
            return results

        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def get_chapters(self, manga_slug):
        """
        Fetches chapters for a specific manga.
        Implements the 3-step fallback logic (SSR -> Admin Ajax -> Direct Ajax) found in index.ts.
        """
        manga_url = f"{self.api}/manga/{manga_slug}/"
        print(f"Fetching chapters from: {manga_url}")
        
        resp = requests.get(manga_url, headers=self.headers)
        html = resp.text
        soup = self._get_soup(html)
        
        # 1. Try finding chapters directly in the HTML (SSR)
        chapters = self._parse_chapters(soup, manga_slug)
        
        # 2. AJAX Fallback if no chapters found
        if not chapters:
            print("No chapters found in initial page, trying AJAX...")
            
            # Find post ID
            post_id_match = re.search(r'postid-(\d+)', html) or re.search(r'data-id="(\d+)"', html)
            
            if post_id_match:
                post_id = post_id_match.group(1)
                
                # Try standard AJAX first
                ajax_url = f"{self.api}/wp-admin/admin-ajax.php"
                try:
                    ajax_resp = requests.post(
                        ajax_url, 
                        headers={**self.headers, "Content-Type": "application/x-www-form-urlencoded"},
                        data=f"action=manga_get_chapters&manga={post_id}"
                    )
                    
                    if len(ajax_resp.text) > 5 and ajax_resp.text != "0":
                        ajax_soup = self._get_soup(ajax_resp.text)
                        chapters = self._parse_chapters(ajax_soup, manga_slug)
                    else:
                        # Try direct AJAX URL fallback
                        print("Standard AJAX failed, trying direct AJAX...")
                        direct_ajax_url = f"{self.api}/manga/{manga_slug}/ajax/chapters/"
                        direct_resp = requests.post(direct_ajax_url, headers=self.headers)
                        direct_soup = self._get_soup(direct_resp.text)
                        chapters = self._parse_chapters(direct_soup, manga_slug)
                        
                except Exception as e:
                    print(f"AJAX error: {e}")

        # Reverse to show oldest to newest? Or keep newest first?
        # index.ts reverses them to assign indices, usually implies Source provides Newest -> Oldest
        return chapters

    def _parse_chapters(self, soup, manga_slug):
        chapters = []
        # Selectors from index.ts
        elements = soup.select(".wp-manga-chapter, .chapter-li, .listing-chapters_wrap li")
        
        for el in elements:
            a_tag = el.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href')
            if not href or manga_slug not in href:
                continue

            # Extract chapter slug
            slug_match = re.search(r'/manga/[^/]+/([^/]+)/', href)
            if not slug_match:
                continue
            
            chapter_slug = slug_match.group(1)
            title = a_tag.get_text(strip=True)
            
            chapters.append({
                'title': title,
                'slug': chapter_slug,
                'url': href
            })
            
        return chapters

    def get_pages(self, manga_slug, chapter_slug):
        """
        Fetches image URLs for a specific chapter.
        """
        url = f"{self.api}/manga/{manga_slug}/{chapter_slug}/"
        print(f"Fetching images from: {url}")
        
        resp = requests.get(url, headers=self.headers)
        soup = self._get_soup(resp.text)
        
        pages = []
        # Selectors from index.ts
        images = soup.select(".wp-manga-chapter-img")
        
        for img in images:
            # Check data-src, data-lazy-src, then src
            src = img.get('data-src') or img.get('data-lazy-src') or img.get('src')
            if src:
                pages.append(src.strip())
                
        return pages

    def download_chapter(self, manga_title, chapter_title, pages):
        """
        Downloads images to a folder.
        """
        # Sanitize folder names
        safe_manga = "".join([c for c in manga_title if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        safe_chapter = "".join([c for c in chapter_title if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        
        path = os.path.join("downloads", safe_manga, safe_chapter)
        os.makedirs(path, exist_ok=True)
        
        print(f"Downloading {len(pages)} pages to {path}...")
        
        for i, url in enumerate(pages):
            ext = url.split('.')[-1]
            filename = f"{i+1:03d}.{ext}"
            filepath = os.path.join(path, filename)
            
            if os.path.exists(filepath):
                continue
                
            try:
                # Need to use the headers to avoid 403 Forbidden on images
                img_resp = requests.get(url, headers=self.headers, stream=True)
                if img_resp.status_code == 200:
                    with open(filepath, 'wb') as f:
                        for chunk in img_resp.iter_content(1024):
                            f.write(chunk)
            except Exception as e:
                print(f"Failed to download page {i+1}: {e}")
                
        print("Download complete!")

# --- Main Execution Flow ---
if __name__ == "__main__":
    app = ThreeAsqProvider()
    
    # 1. Search
    query = input("Enter manga name to search: ")
    results = app.search(query)
    
    if not results:
        print("No results found.")
        exit()
        
    print(f"\nFound {len(results)} results:")
    for i, res in enumerate(results):
        print(f"{i + 1}. {res['title']}")
        
    # 2. Select Manga
    choice = int(input("\nSelect manga (number): ")) - 1
    selected_manga = results[choice]
    
    # 3. Get Chapters
    chapters = app.get_chapters(selected_manga['slug'])
    
    if not chapters:
        print("No chapters found.")
        exit()
        
    print(f"\nFound {len(chapters)} chapters.")
    # Show first 5 as example
    for i, chap in enumerate(chapters[:5]):
        print(f"{i + 1}. {chap['title']}")
    print("...")
    
    # 4. Select Chapter
    print("\nOptions:")
    print("1. Download specific chapter")
    print("2. Download all chapters (careful!)")
    opt = input("Choice: ")
    
    if opt == "1":
        # Simplified selection: asking for index in the full list
        # Note: Chapters are usually returned Newest -> Oldest. 
        # The prompt implies simple usage, so we'll just ask for the index from the internal list.
        # A more robust script would print all chapters or allow range selection.
        print("\n(Enter 1 for the first/newest chapter shown above)")
        chap_idx = int(input("Enter chapter number from list: ")) - 1
        target_chapters = [chapters[chap_idx]]
    elif opt == "2":
        target_chapters = chapters
    else:
        exit()
        
    # 5. Download
    for chap in target_chapters:
        pages = app.get_pages(selected_manga['slug'], chap['slug'])
        if pages:
            app.download_chapter(selected_manga['title'], chap['title'], pages)
        else:
            print(f"No pages found for {chap['title']}")