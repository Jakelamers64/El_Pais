import random
import string
import glob
import os
import requests
from datetime import datetime, timedelta
from ebooklib import epub
from bs4 import BeautifulSoup
from newspaper import Article
from tqdm import tqdm
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_image(url):
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        filename = ''.join(random.choice(string.ascii_letters) for x in range(10))

        with open(f"{filename}.jpeg", 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)

        return f"{filename}.jpeg"
    except requests.exceptions.RequestException as e:
        print(f"Error downloading image: {e}")

def create_session_with_retries():
    """Create a requests session with retry strategy"""
    session = requests.Session()
    retries = Retry(
        total=5,  # number of retries
        backoff_factor=1,  # wait 1, 2, 4, 8, 16 seconds between retries
        status_forcelist=[500, 502, 503, 504],  # retry on these status codes
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def download_article_with_retry(url, max_retries=3, timeout=30):
    """Download article with retries and timeout"""
    for attempt in range(max_retries):
        try:
            article = Article(url)
            article.download()
            article.parse()
            return article
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                logger.error(f"Failed to download article after {max_retries} attempts: {url}")
                logger.error(f"Error: {str(e)}")
                return None
            logger.warning(f"Attempt {attempt + 1} failed for {url}. Retrying...")
            time.sleep(2 ** attempt)  # Exponential backoff
    return None

def create_epub(rss_feed, output_filename):
    """Create EPUB book from RSS feed with error handling"""
    session = create_session_with_retries()

    try:
        r = session.get(rss_feed, timeout=30)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch RSS feed: {str(e)}")
        return False

    soup = BeautifulSoup(r.content, features="xml")
    items = soup.find_all('item')
    articles = [(item.find('link').text,item.find('category').text) for item in items]
    articles.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"Found {len(articles)} articles")

    # Create book and set metadata
    book = epub.EpubBook()
    book.set_identifier('id123456')
    book.set_title('El País Articles')
    book.set_language('es')
    book.add_author('RSS Feed Generator')

    chapters = []

    # Process articles with progress bar
    for url, cat in tqdm(articles, desc="Processing articles"):
        article = download_article_with_retry(url)

        if article is None:
            logger.warning(f"Skipping article: {url}")
            continue

        print(
            f"""
            pub date: {article.publish_date.date()}
            pub date type: {type(article.publish_date.date())}
            
            today date: {datetime.today().date()}
            today date type: {type(datetime.today().date())}
            
            test: {article.publish_date.date() == datetime.today().date()}
            """
        )

        if article.publish_date.date() != datetime.today().date():
            continue

        try:
            # Get the article HTML and parse it
            article_html = article.article_html
            if article_html:
                soup = BeautifulSoup(article_html, 'html.parser')
                paragraphs = soup.find_all('p')
                article_content = '\n'.join([f'<p>{p.get_text()}</p>' for p in paragraphs])
            else:
                paragraphs = article.text.split('\n\n')
                article_content = '\n'.join([f'<p>{p.strip()}</p>' for p in paragraphs if p.strip()])

            # Create chapter
            chapter_name = article.title.replace(' ', '_').replace('/', '_')[:30]
            chap = epub.EpubHtml(
                title=article.title,
                file_name=f'{chapter_name}.xhtml',
                lang='es'
            )

            epubtop_image_path = download_image(article.top_img)

            chap.content = f'''
            <html>
                <head>
                    <title>{article.title}</title>
                </head>
                <body>
                    <h1>{article.title}</h1>
                    <h3>{cat}</h3>
                    <img src="{epubtop_image_path}" alt="{article.top_img}"/>  {article_content}
                </body>
            </html>
            '''

            # Assuming book and chapters are already initialized

            # Embed the downloaded image in the epub
            with open(epubtop_image_path, 'rb') as f:
                b_image1 = f.read()

            image1_item = epub.EpubItem(
                uid=epubtop_image_path,
                file_name=epubtop_image_path,
                media_type='image/jpeg',
                content=b_image1
            )

            # Add the image and chapter to the epub
            book.add_item(image1_item)
            book.add_item(chap)
            chapters.append(chap)

        except Exception as e:
            logger.error(f"Error processing article {url}: {str(e)}")
            continue

    if not chapters:
        logger.error("No articles were successfully processed")
        return False

    # Create table of contents
    book.toc = [(epub.Section('Articles'), chapters)]

    # Add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define CSS style
    style = '''
        @namespace epub "http://www.idpf.org/2007/ops";
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 2em;
        }
        h1 {
            text-align: center;
            padding: 20px;
            margin-bottom: 1.5em;
        }
        p {
            margin-bottom: 1em;
            text-align: justify;
        }
    '''

    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)

    # Create spine
    book.spine = ['nav'] + chapters

    try:
        # Write epub file
        epub.write_epub(output_filename, book, {})
        logger.info("EPUB file generated successfully!")
        return True
    except Exception as e:
        logger.error(f"Error writing EPUB file: {str(e)}")
        return False


if __name__ == "__main__":
    RSS_FEED = "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada"
    create_epub(RSS_FEED, 'el_pais.epub')

    removing_files = glob.glob(f'{os.getcwd()}/*.jpeg')
    for i in removing_files:
        os.remove(i)