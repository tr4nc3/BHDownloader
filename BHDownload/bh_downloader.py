import os
import time
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import logging
from collections import deque
import re
import sys
import argparse
from urllib.robotparser import RobotFileParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type
from requests.exceptions import RequestException
from selenium.common.exceptions import WebDriverException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fake_useragent import UserAgent

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Base configuration
BASE_URL = "https://www.blackhat.com/us-25/briefings/schedule/"
DOWNLOAD_DIR = "downloaded_pdfs"
MAX_WORKERS = 5  # Number of threads for downloading PDFs
REQUEST_TIMEOUT = 10  # Timeout for HTTP requests in seconds
USER_AGENT = UserAgent().random  # Random user agent for each session
HEADERS = {'User-Agent': USER_AGENT}

# Allowed domains to process
allow_domains = ["blackhat.com", "*.blackhat.com"]  # Add domains here as needed

# Initialize a requests session with retries
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)


def create_download_dir():
    """Create the download directory if it doesn't exist."""
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


def is_valid_pdf_url(url):
    """Check if the URL is valid and belongs to an allowed domain."""
    parsed_url = urlparse(url)
    return (url.lower().endswith('.pdf') and
            any(domain in parsed_url.netloc for domain in allow_domains))


def is_allowed_by_robots(url):
    """Check if the URL is allowed by the robots.txt file."""
    return True
    # parsed_url = urlparse(url)
    # robots_url = urljoin(f"{parsed_url.scheme}://{parsed_url.netloc}", '/robots.txt')
    # rp = RobotFileParser()
    # try:
    #     rp.set_url(robots_url)
    #     rp.read()
    #     return rp.can_fetch('*', url)
    # except Exception as e:
    #     logger.error(f"Error reading robots.txt: {e}")
    #     return True  # Default to allowing if robots.txt cannot be read


def get_pdf_links_from_page(url):
    """Extract PDF links from a given page URL."""
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        pdf_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(url, href)
            if is_valid_pdf_url(full_url) and is_allowed_by_robots(full_url):
                pdf_links.append(full_url)
        return pdf_links
    except RequestException as e:
        logger.error(f"Error fetching {url}: {e}")
        return []


def is_domain_allowed(url):
    """Check if the URL's domain is in the allow list."""
    parsed_url = urlparse(url)
    return any(domain in parsed_url.netloc for domain in allow_domains)


def download_pdf(url):
    """Download a PDF file from the given URL."""
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        parsed_url = urlparse(url)
        path = parsed_url.path.lstrip('/')
        file_path = os.path.join(DOWNLOAD_DIR, path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'wb') as f:
            f.write(response.content)
        logger.info(f"Downloaded: {file_path}")
    except RequestException as e:
        logger.error(f"Failed to download {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error downloading {url}: {e}")


def crawl_and_download_pdfs(start_url):
    """Crawl the website and download all PDF files based on allowed domains."""
    create_download_dir()
    visited_urls = set()
    urls_to_visit = deque([start_url])

    while urls_to_visit:
        url = urls_to_visit.popleft()
        if url in visited_urls  or not is_domain_allowed(url):
            continue
        visited_urls.add(url)

        logger.info(f"Processing: {url}")
        pdf_links = get_pdf_links_from_page(url)

        for pdf_link in pdf_links:
            download_pdf(pdf_link)
            time.sleep(1)  # Be polite to the server

        try:
            response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']
                full_url = urljoin(url, href)
                if full_url not in visited_urls and full_url not in urls_to_visit:
                    urls_to_visit.append(full_url)
        except RequestException as e:
            logger.error(f"Error processing {url}: {e}")


def main():
    """Parse command line arguments and start the crawling process."""
    parser = argparse.ArgumentParser(description="Download all PDF files from specified domains")
    parser.add_argument('--start-url', type=str, default=BASE_URL, help='The starting URL to crawl')
    args = parser.parse_args()

    start_url = args.start_url
    if not start_url.endswith('/'):
        start_url += '/'

    if not is_allowed_by_robots(start_url):
        logger.error(f"Starting URL {start_url} is not allowed by robots.txt")
        sys.exit(1)

    crawl_and_download_pdfs(start_url)
    logger.info("Crawling and downloading completed.")


if __name__ == "__main__":
    main()