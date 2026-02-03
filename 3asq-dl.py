import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import quote

class ThreeAsqProvider:
    def __init__(self):
        self.api = "https://3asq.org"
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
        """
        print(f"Searching for: {query}...")
        url = f"{self.api}/?s={quote(query)}&post_type=wp-manga"
        
        try:
            resp = requests.get(url, headers=self.headers)
            soup = self._get_soup(resp.text)
            
            results = []
            seen_slugs = set()

            containers = soup.select(".c-tabs-item__content, .tab-content-wrap, .c-tabs-item, .row.c-tabs-item__content")
            
            for el in containers:
                title_el = el.select_one(".post-title h3 a, .post-title h4 a, .post-title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get('href')
                
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
        Fetches chapters and sorts them OLDEST to NEWEST.
        """
        manga_url = f"{self.api}/manga/{manga_slug}/"
        print(f"Fetching chapters from: {manga_url}")
        
        resp = requests.get(manga_url, headers=self.headers)
        html = resp.text
        soup = self._get_soup(html)
        
        # 1. Try finding chapters directly (SSR)
        chapters = self._parse_chapters(soup, manga_slug)
        
        # 2. AJAX Fallback
        if not chapters:
            print("No chapters found in initial page, trying AJAX...")
            post_id_match = re.search(r'postid-(\d+)', html) or re.search(r'data-id="(\d+)"', html)
            
            if post_id_match:
                post_id = post_id_match.group(1)
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
                        print("Standard AJAX failed, trying direct AJAX...")
                        direct_ajax_url = f"{self.api}/manga/{manga_slug}/ajax/chapters/"
                        direct_resp = requests.post(direct_ajax_url, headers=self.headers)
                        direct_soup = self._get_soup(direct_resp.text)
                        chapters = self._parse_chapters(direct_soup, manga_slug)
                        
                except Exception as e:
                    print(f"AJAX error: {e}")

        # REVERSE the list so it is Oldest -> Newest (Chapter 1, 2, 3...)
        # Websites usually provide Newest -> Oldest.
        if chapters:
            chapters.reverse()
            
        return chapters

    def _parse_chapters(self, soup, manga_slug):
        chapters = []
        elements = soup.select(".wp-manga-chapter, .chapter-li, .listing-chapters_wrap li")
        
        for el in elements:
            a_tag = el.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href')
            if not href or manga_slug not in href:
                continue

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
        url = f"{self.api}/manga/{manga_slug}/{chapter_slug}/"
        # print(f"Fetching images from: {url}") # Reduced noise
        
        resp = requests.get(url, headers=self.headers)
        soup = self._get_soup(resp.text)
        
        pages = []
        images = soup.select(".wp-manga-chapter-img")
        
        for img in images:
            src = img.get('data-src') or img.get('data-lazy-src') or img.get('src')
            if src:
                pages.append(src.strip())
                
        return pages

    def download_chapter(self, manga_title, chapter_title, pages):
        safe_manga = "".join([c for c in manga_title if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        safe_chapter = "".join([c for c in chapter_title if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        
        path = os.path.join("downloads", safe_manga, safe_chapter)
        os.makedirs(path, exist_ok=True)
        
        print(f"Downloading {len(pages)} pages to: {safe_chapter}")
        
        for i, url in enumerate(pages):
            ext = url.split('.')[-1]
            filename = f"{i+1:03d}.{ext}"
            filepath = os.path.join(path, filename)
            
            if os.path.exists(filepath):
                continue
                
            try:
                img_resp = requests.get(url, headers=self.headers, stream=True)
                if img_resp.status_code == 200:
                    with open(filepath, 'wb') as f:
                        for chunk in img_resp.iter_content(1024):
                            f.write(chunk)
            except Exception as e:
                print(f"Failed to download page {i+1}: {e}")

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
        
    print(f"\nFound {len(chapters)} chapters (Sorted Oldest -> Newest).")
    print(f"1. {chapters[0]['title']}")
    if len(chapters) > 1:
        print(f"2. {chapters[1]['title']}")
    print("...")
    print(f"{len(chapters)}. {chapters[-1]['title']}")
    
    # 4. Select Chapter Mode
    print("\nOptions:")
    print("1. Download specific chapter")
    print("2. Download range (e.g. 10 to 20)")
    print("3. Download all")
    opt = input("Choice: ")
    
    target_chapters = []

    if opt == "1":
        idx = int(input(f"Enter chapter index (1 - {len(chapters)}): ")) - 1
        if 0 <= idx < len(chapters):
            target_chapters = [chapters[idx]]
        else:
            print("Invalid index.")

    elif opt == "2":
        start = int(input("Start from chapter index: "))
        end = int(input("Till chapter index: "))
        
        # Adjust for 0-based index (User inputs 10, we want index 9)
        start_idx = max(0, start - 1)
        end_idx = min(len(chapters), end)
        
        if start_idx < end_idx:
            target_chapters = chapters[start_idx:end_idx]
            print(f"Queued {len(target_chapters)} chapters for download.")
        else:
            print("Invalid range.")

    elif opt == "3":
        target_chapters = chapters
    
    # 5. Download
    if not target_chapters:
        print("No chapters selected.")
        exit()

    for chap in target_chapters:
        pages = app.get_pages(selected_manga['slug'], chap['slug'])
        if pages:
            app.download_chapter(selected_manga['title'], chap['title'], pages)
        else:
            print(f"No pages found for {chap['title']}")

    print("\nAll tasks finished.")
